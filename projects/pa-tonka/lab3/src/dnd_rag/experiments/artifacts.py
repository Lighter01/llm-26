"""Portable JSON/CSV artifacts and deterministic recomputation without model calls."""

import csv
import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from statistics import mean, median

from dnd_rag.contracts import ChunkRef, RagError
from dnd_rag.evaluation.metrics import aggregate_metrics
from dnd_rag.experiments.contracts import AgentDataset
from dnd_rag.experiments.scoring import (
    evaluate_retrieval_calls,
    evaluate_turn,
    normalized_tools,
    recover_wire_tools,
)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    temp.replace(path)


def append_jsonl(path, data):
    with Path(path).open('a') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, default=str) + '\n')


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def load_reviews(path):
    if not Path(path).exists():
        return {}
    result = {}
    with Path(path).open(newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('value', '') == '':
                continue
            key = (row['case_id'], int(row['turn']))
            if row['criterion'] in result.setdefault(key, {}):
                raise RagError('invalid_review', 'Duplicate criterion')
            if (
                row['value'] not in ('0', '1')
                or row['method'] not in ('human', 'agent-assisted')
                or not row['evidence'].strip()
            ):
                raise RagError(
                    'invalid_review',
                    'Scored criteria require0/1, human/agent-assisted method and trace evidence',
                )
            result[key][row['criterion']] = {
                'value': int(row['value']),
                'method': row['method'],
                'evidence': row['evidence'],
                'category': row.get('category', ''),
            }
    return result


def write_review(path, dataset, records):
    with Path(path).open('w', newline='') as stream:
        fields = [
            'case_id',
            'turn',
            'criterion',
            'description',
            'value',
            'method',
            'evidence',
            'category',
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        lookup = {i.id: i for i in dataset.items}
        for record in records:
            case = lookup[record['case_id']].turns[record['turn'] - 1]
            criteria = [(f'rubric_{n}', d) for n, d in enumerate(case.rubric)]
            if case.checks.get('history_correctness'):
                criteria.append(
                    (
                        'history_correctness',
                        'Preserve current party and the actual accepted encounter/loot; respect explicit updates and distinguish comparisons',
                    )
                )
            for criterion, description in criteria:
                writer.writerow(
                    dict(
                        case_id=record['case_id'],
                        turn=record['turn'],
                        criterion=criterion,
                        description=description,
                        value='',
                        method='',
                        evidence='',
                        category='',
                    )
                )


def score_records(dataset, records, manifest, review=None):
    review = review or {}
    lookup = {i.id: i for i in dataset.items}
    histories = defaultdict(list)
    scored = []
    valid = {
        (item.id, n): {f'rubric_{k}' for k in range(len(turn.rubric))}
        | ({'history_correctness'} if turn.checks.get('history_correctness') else set())
        for item in dataset.items
        for n, turn in enumerate(item.turns, 1)
    }
    for key, annotations in review.items():
        if key not in valid or set(annotations) - valid[key]:
            raise RagError('invalid_review', 'Review refers to an unknown turn or criterion')
    seen = set()
    for raw in records:
        key = (raw['case_id'], raw['turn'])
        if key not in valid or key in seen:
            raise RagError('invalid_artifacts', 'Unknown or duplicate saved turn')
        seen.add(key)
        restored_tools = normalized_tools(raw.get('raw_records', {}).get('tools', raw['tools']))
        recovered = recover_wire_tools(raw.get('raw_records', {}).get('wire', []))
        reply = raw['reply']
        if len(recovered) > len(restored_tools):
            restored_tools = recovered
            reply = {**reply, 'usage': {**reply.get('usage', {}), 'tool_calls': len(recovered)}}
        record = {
            **raw,
            'reply': reply,
            'tools': restored_tools,
            'history': histories[raw['case_id']],
        }
        case = lookup[raw['case_id']].turns[raw['turn'] - 1]
        scores = evaluate_turn(case, record, annotation=review.get((raw['case_id'], raw['turn'])))
        retrieval = evaluate_retrieval_calls(case, record['tools'], manifest)
        retrieval_metrics = aggregate_metrics(retrieval) if retrieval else None
        searches = [t for t in record['tools'] if t['name'] == 'search_rules']
        scored.append(
            {
                **raw,
                'reply': reply,
                'tools': restored_tools,
                'scores': {**scores.model_dump(), 'success': scores.success},
                'retrieval_metrics': retrieval_metrics,
                'retrieval_status': 'missing_expected_call'
                if case.evidence and not searches
                else 'observed'
                if case.evidence
                else 'not_annotated',
                'retrieval_calls': [
                    {
                        'requested_limit': t['arguments'].get('limit', 5),
                        'returned_limit': len(t['result'].get('hits', [])),
                    }
                    for t in searches
                ],
            }
        )
        histories[raw['case_id']].append({**raw, 'tools': restored_tools})
    return scored


def summarize_records(dataset, records):
    grouped = defaultdict(list)
    for row in records:
        grouped[row['case_id']].append(row)
    executions = []
    for item in dataset.items:
        rows = grouped[item.id]
        complete = len(rows) == len(item.turns) and all(
            r['reply']['status'] == 'completed'
            and r['reply'].get('trace_id')
            and all(
                type(r['reply'].get('usage', {}).get(k)) is int
                for k in ('input_tokens', 'output_tokens')
            )
            for r in rows
        )
        decisions = [r['scores']['success'] for r in rows]
        success = (
            False
            if any(x is False for x in decisions)
            else None
            if len(rows) != len(item.turns) or any(x is None for x in decisions)
            else True
        )
        executions.append(
            {'id': item.id, 'completed': bool(complete), 'success': success, **item.metadata}
        )

    def total(key):
        values = [r['reply'].get('usage', {}).get(key) for r in records]
        return sum(values) if values and all(type(v) in (int, float) for v in values) else None

    latency = [r['reply'].get('usage', {}).get('latency_ms') for r in records]
    latency = [x for x in latency if isinstance(x, (int, float))]
    retrieval = [r['retrieval_metrics'] for r in records if r.get('retrieval_metrics') is not None]
    breakdown = {}
    for field in ('type', 'difficulty'):
        for value in sorted({e[field] for e in executions}):
            selected = [e for e in executions if e[field] == value]
            breakdown[f'{field}:{value}'] = {
                'executions': len(selected),
                'completed': sum(e['completed'] for e in selected),
                'success_rate': sum(e['success'] is True for e in selected) / len(selected)
                if all(e['success'] is not None for e in selected)
                else None,
            }
    history_groups = {'before': [], 'after': []}
    compacted_sessions = set()
    tool_correctness = []
    for row in records:
        if any(
            e.get('kind', e.get('type'))
            in ('compaction_completed', 'compacted', 'context_compacted')
            for e in row.get('events', [])
        ):
            compacted_sessions.add(row['session_id'])
        values = row['scores']['values']
        if 'history_correctness' in values:
            history_groups['after' if row['session_id'] in compacted_sessions else 'before'].append(
                values['history_correctness']
            )
        formal = [
            v
            for k, v in values.items()
            if row['scores']['method'][k] == 'formal'
            and k
            not in (
                'completed',
                'loot_amount_reported',
                'loot_amount_recalled',
                'observed_compaction',
                'recalled_encounter_names',
            )
        ]
        if formal:
            tool_correctness.append(mean(formal))

    def total_usage(key):
        values = [r['reply'].get('usage', {}).get(key) for r in records]
        return sum(values) if values and all(type(v) is int for v in values) else None

    contexts = [r['reply'].get('usage', {}).get('max_context_tokens') for r in records]
    citations = [r['reply'].get('citation_validation') or {} for r in records]
    valid_citations = sum(len(c.get('valid_numbers', [])) for c in citations)
    unknown_citations = sum(len(c.get('unknown_numbers', [])) for c in citations)
    return {
        'citation_references': valid_citations + unknown_citations,
        'unknown_citations': unknown_citations,
        'citation_validity': valid_citations / (valid_citations + unknown_citations)
        if valid_citations + unknown_citations
        else None,
        'model_calls': total_usage('model_calls'),
        'max_native_input_tokens': max((v for v in contexts if type(v) is int), default=None),
        'tool_correctness': mean(tool_correctness) if tool_correctness else None,
        'tool_correctness_turns': len(tool_correctness),
        'history_correctness': {
            key: {
                'samples': len(values),
                'score': mean(values) if values and all(v is not None for v in values) else None,
            }
            for key, values in history_groups.items()
        },
        'error_rate': mean(r['reply']['status'] != 'completed' for r in records)
        if records
        else None,
        'step_limit_rate': mean(r['reply']['status'] == 'step_limit' for r in records)
        if records
        else None,
        'executions': len(executions),
        'turns': len(records),
        'expected_turns': sum(len(i.turns) for i in dataset.items),
        'completed_executions': sum(e['completed'] for e in executions),
        'completion_rate': mean(e['completed'] for e in executions) if executions else 0.0,
        'task_success_rate': mean(e['success'] for e in executions)
        if executions and all(e['success'] is not None for e in executions)
        else None,
        'known_failed_executions': sum(e['success'] is False for e in executions),
        'pending_executions': sum(
            any(r['scores']['pending'] for r in grouped[e['id']]) or not grouped[e['id']]
            for e in executions
        ),
        'input_tokens': total('input_tokens'),
        'output_tokens': total('output_tokens'),
        'api_cost': total('api_cost'),
        'total_latency_ms': sum(latency) if len(latency) == len(records) else None,
        'mean_latency_ms': mean(latency) if latency else None,
        'median_latency_ms': median(latency) if latency else None,
        'tool_calls': sum(len(r['tools']) for r in records),
        'tool_errors': sum(
            t.get('status') == 'error' or bool(t.get('result', {}).get('error'))
            for r in records
            for t in r['tools']
        ),
        'compactions': sum(
            e.get('kind', e.get('type'))
            in ('compaction_completed', 'compacted', 'context_compacted')
            for r in records
            for e in r.get('events', [])
        ),
        'statuses': dict(Counter(r['reply']['status'] for r in records)),
        'missing_retrieval_calls': sum(
            r.get('retrieval_status') == 'missing_expected_call' for r in records
        ),
        'annotated_retrieval_turns': len(retrieval),
        'retrieval': {k: mean(r[k] for r in retrieval) for k in retrieval[0]}
        if retrieval
        else None,
        'breakdown': breakdown,
        'items': executions,
    }


def recompute(directory, *, review_path=None, write=False):
    directory = Path(directory)
    run = json.loads((directory / 'run.json').read_text())
    dataset = AgentDataset.model_validate(run['dataset'])
    manifest = [
        ChunkRef.model_validate(r)
        for r in json.loads((directory / 'manifest.json').read_text()).get('chunks', [])
    ]
    records = score_records(
        dataset,
        read_jsonl(directory / 'turns.jsonl'),
        manifest,
        load_reviews(review_path or directory / 'review.csv'),
    )
    metrics = summarize_records(dataset, records)
    if write:
        save_json(directory / 'metrics.json', metrics)
        with (directory / 'scored_tool_calls.jsonl').open('w') as stream:
            for row in records:
                for tool in row['tools']:
                    stream.write(
                        json.dumps(
                            {
                                'case_id': row['case_id'],
                                'turn': row['turn'],
                                'session_id': row['session_id'],
                                **tool,
                            },
                            ensure_ascii=False,
                        )
                        + '\n'
                    )
        with (directory / 'scored_turns.jsonl').open('w') as stream:
            for row in records:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    return metrics


def freeze_fingerprint(root, paths):
    return {
        str(Path(p).relative_to(root)): sha256(Path(p).read_bytes()).hexdigest()
        for p in sorted(paths)
        if Path(p).is_file()
    }


def export_comparison(run_dirs):
    directories = [Path(p) for p in run_dirs]
    rows = []
    fingerprints = []
    for directory in directories:
        run = json.loads((directory / 'run.json').read_text())
        metrics = recompute(directory)
        fingerprints.append(run['manifest'].get('common_fingerprint'))
        rows.append(
            {
                'run_id': run['run_id'],
                'agent': run['agent'],
                'mode': run['mode'],
                **{k: v for k, v in metrics.items() if not isinstance(v, (dict, list))},
            }
        )
    if len(set(fingerprints)) > 1:
        raise RagError(
            'incompatible_runs', 'Dataset/tools/prompts/model/catalog fingerprints differ'
        )
    path = directories[0].parent / 'comparison.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save_json(path.with_suffix('.json'), rows)
    return path
