"""Audit explicitly selected real measurement artifacts without calling a model."""

import json
import os
from collections import defaultdict
from pathlib import Path

import pytest

from dnd_rag.experiments.artifacts import read_jsonl, recompute


def _assert_effective_profile(payload, mode, reserve):
    assert payload['model'] == 'dnd-nemotron'
    assert payload['chat_template_kwargs']['enable_thinking'] is (mode == 'budgeted')
    assert payload['reasoning_budget_tokens'] == (512 if mode == 'budgeted' else 0)
    if mode == 'off':
        assert payload['reasoning_effort'] == 'none'
    assert payload.get('max_completion_tokens', payload.get('max_output_tokens')) == reserve


@pytest.mark.skipif(
    not os.getenv('DM_SAVED_RUNS'), reason='Set DM_SAVED_RUNS to the four retained run directories'
)
def test_saved_matrix_is_referentially_complete_and_recomputes():
    directories = [Path(p) for p in os.environ['DM_SAVED_RUNS'].split(os.pathsep)]
    assert len(directories) == 4
    pairs = set()
    fingerprints = set()
    all_sessions = set()
    executions = turns = 0
    for directory in directories:
        run = json.loads((directory / 'run.json').read_text())
        dataset = run['dataset']
        original = read_jsonl(directory / 'turns.jsonl')
        records = read_jsonl(directory / 'scored_turns.jsonl')
        assert (
            run['status'] in ('completed', 'incomplete') and run['evaluation_status'] == 'completed'
        )
        pairs.add((run['agent'], run['mode']))
        fingerprints.add(run['manifest']['common_fingerprint'])
        assert len(dataset['items']) == 15 and len(records) == 47
        experiment_items = json.loads((directory / 'experiment-items.json').read_text())
        assert len(experiment_items) == 47
        assert all(item['experimentId'] == run['experiment_id'] for item in experiment_items)
        assert {item['traceId'] for item in experiment_items} == {
            record['reply']['trace_id'] for record in records
        }
        assert len({item['experimentItemId'] for item in experiment_items}) == 47
        if run['agent'] == 'own':
            for journal in (directory / 'raw/own').glob('*/turns.jsonl'):
                rows = read_jsonl(journal)
                requests = [r for r in rows if r['kind'] == 'wire_input']
                responses = [r for r in rows if r['kind'] == 'model_response']
                assert len(requests) == len(responses)
                for request, response in zip(requests, responses):
                    reserve = 1024 if request['phase'] == 'summary' else 2048
                    _assert_effective_profile(request['payload'], run['mode'], reserve)
                    assert request['input_tokens'] == response['response']['usage']['prompt_tokens']
                    assert request['input_tokens'] + reserve + 256 <= 16384
        else:
            for record in records:
                wire = record['raw_records'].get('wire', [])
                responses = {r['id']: r['response'] for r in wire if r.get('kind') == 'response'}
                for request in (r for r in wire if r.get('kind') == 'request'):
                    _assert_effective_profile(request['effective'], run['mode'], 2048)
                    assert request['input_tokens'] + 2048 + 256 <= 16384
                    if request['id'] in responses:
                        assert (
                            request['input_tokens']
                            == responses[request['id']]['usage']['input_tokens']
                        )
        expected = {i['id']: len(i['turns']) for i in dataset['items']}
        grouped = defaultdict(list)
        manifest = {
            r['chunk_id']: r
            for r in json.loads((directory / 'manifest.json').read_text())['chunks']
        }
        tools = read_jsonl(directory / 'tool_calls.jsonl')
        # The receipt table predates offline recovery; preserve that original
        # view, while auditing restored references from the scored view.
        assert len(tools) == sum(
            len(r.get('raw_records', {}).get('tools', r['tools'])) for r in original
        )
        assert len(read_jsonl(directory / 'scored_tool_calls.jsonl')) == sum(
            len(r['tools']) for r in records
        )
        allowed = defaultdict(dict)
        for record in records:
            grouped[record['case_id']].append(record)
            if record['reply']['status'] == 'completed':
                assert record['reply']['trace_id']
                assert all(
                    type(record['reply']['usage'].get(k)) is int
                    for k in ('input_tokens', 'output_tokens')
                )
                observed = (
                    directory / 'observations' / record['case_id'] / f'{record["turn"]}.json'
                    if run['agent'] == 'own'
                    else directory
                    / 'raw/codex'
                    / record['session_id']
                    / f'{record["turn"]}.observations.json'
                )
                observations = json.loads(observed.read_text())
                assert all(o['traceId'] == record['reply']['trace_id'] for o in observations)
                generations = [o for o in observations if o['type'] == 'GENERATION']
                assert len(generations) == record['reply']['usage']['model_calls']
                assert len({o['id'] for o in observations}) == len(observations)
                assert all(
                    o.get('input') and o.get('output') and o.get('usageDetails')
                    for o in generations
                )
                for field, native in [('input', 'input_tokens'), ('output', 'output_tokens')]:
                    assert (
                        sum(o['usageDetails'][field] for o in generations)
                        == record['reply']['usage'][native]
                    )
            for tool in record['tools']:
                if tool['name'] != 'search_rules':
                    continue
                hits = tool['result'].get('hits', [])
                citations = tool['result'].get('citations', [])
                assert len(citations) == len(hits)
                for hit, citation in zip(hits, citations):
                    meta = hit['chunk']['metadata']
                    reference = manifest[meta['chunk_id']]
                    assert all(meta[k] == reference[k] for k in reference)
                    assert citation['source_id'] == f'rag:{meta["index_id"]}:{meta["chunk_id"]}'
                    previous = allowed[record['session_id']].setdefault(
                        citation['number'], citation['source_id']
                    )
                    assert previous == citation['source_id']
            validation = record['reply'].get('citation_validation') or {}
            assert set(validation.get('valid_numbers', [])) <= set(allowed[record['session_id']])
        assert set(grouped) == set(expected)
        for key, count in expected.items():
            rows = grouped[key]
            assert [r['turn'] for r in rows] == list(range(1, count + 1))
            sessions = {r['session_id'] for r in rows}
            assert len(sessions) == 1
            assert not sessions & all_sessions
            all_sessions.update(sessions)
            if count == 9:
                assert any(
                    e.get('kind', e.get('type'))
                    in ('compaction_completed', 'compacted', 'context_compacted')
                    for r in rows
                    for e in r['events']
                )
            registry = directory / 'citations' / f'{rows[0]["session_id"]}.json'
            assert registry.exists()
            assert {
                r['number']: r['source_id'] for r in json.loads(registry.read_text())
            } == allowed[rows[0]['session_id']]
        assert recompute(directory) == json.loads((directory / 'metrics.json').read_text())
        assert recompute(directory)['pending_executions'] == 0
        executions += len(grouped)
        turns += len(records)
    assert len(fingerprints) == 1 and pairs == {
        ('own', 'off'),
        ('own', 'budgeted'),
        ('codex', 'off'),
        ('codex', 'budgeted'),
    }
    assert executions == 60 and turns == 188 and len(all_sessions) == 60
