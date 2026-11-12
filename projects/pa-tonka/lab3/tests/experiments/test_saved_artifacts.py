"""Audit explicitly selected real measurement artifacts without calling a model."""

import json
import os
from collections import defaultdict
from pathlib import Path

import pytest

from dnd_rag.experiments.artifacts import read_jsonl, recompute


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
        records = read_jsonl(directory / 'turns.jsonl')
        assert (
            run['status'] in ('completed', 'incomplete') and run['evaluation_status'] == 'completed'
        )
        pairs.add((run['agent'], run['mode']))
        fingerprints.add(run['manifest']['common_fingerprint'])
        assert len(dataset['items']) == 15 and len(records) == 47
        expected = {i['id']: len(i['turns']) for i in dataset['items']}
        grouped = defaultdict(list)
        manifest = {
            r['chunk_id']: r
            for r in json.loads((directory / 'manifest.json').read_text())['chunks']
        }
        tools = read_jsonl(directory / 'tool_calls.jsonl')
        assert len(tools) == sum(len(r['tools']) for r in records)
        allowed = defaultdict(dict)
        for record in records:
            grouped[record['case_id']].append(record)
            if record['reply']['status'] == 'completed':
                assert record['reply']['trace_id']
                assert all(
                    type(record['reply']['usage'].get(k)) is int
                    for k in ('input_tokens', 'output_tokens')
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
