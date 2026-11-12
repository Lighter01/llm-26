"""Sequential fixed-input execution with per-turn traces and lossless artifacts."""

import asyncio
import json
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from langfuse import propagate_attributes

from dnd_rag.agent.contracts import AgentReply
from dnd_rag.agent.observability import ObservationRecorder
from dnd_rag.contracts import RagError
from dnd_rag.experiments.artifacts import (
    append_jsonl,
    save_json,
    score_records,
    summarize_records,
    write_review,
)
from dnd_rag.experiments.contracts import RunSummary
from dnd_rag.experiments.scoring import normalized_tools


class ExperimentTracker:
    """SDK5/Compose4 event-based Experiment association, verified by the v2 API.

    Pinned SDK exposes only a high-level run_experiment (which creates another
    trace). We write its documented OTel experiment attributes onto a small
    linking observation in the actual agent trace; no generation is fabricated.
    """

    def __init__(self, root, dataset, run_id, *, agent=None, mode=None):
        self.root = Path(root)
        self.agent, self.mode = agent, mode
        self.client = ObservationRecorder(
            self.root / '.runtime/sessions', project_root=self.root
        ).client
        if self.client is None:
            raise RagError(
                'observability_config', 'A measured run requires local Langfuse credentials'
            )
        self.dataset_name = 'lab3-' + dataset.fingerprint[:16]
        self.run_id = run_id
        self.experiment_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, 'lab3/' + run_id + '/' + dataset.fingerprint)
        )
        self.remote = self.client.create_dataset(
            name=self.dataset_name,
            metadata={'sha256': dataset.fingerprint, 'schema_version': dataset.version},
        )
        self.items = {}
        for item in dataset.items:
            for n, turn in enumerate(item.turns, 1):
                key = (item.id, n)
                identity = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL, dataset.fingerprint + '/' + item.id + '/' + str(n)
                    )
                )
                remote = self.client.create_dataset_item(
                    dataset_name=self.dataset_name,
                    id=identity,
                    input=turn.input,
                    expected_output={'rubric': turn.rubric, 'checks': turn.checks},
                    metadata={**item.metadata, 'case_id': item.id, 'turn': n},
                )
                self.items[key] = remote.id

    def link(self, record, case):
        trace = record['reply'].get('trace_id')
        sid = record['session_id']
        key = (record['case_id'], record['turn'])
        with propagate_attributes(
            session_id=sid,
            tags=['lab3', 'dataset', self.run_id, *[v for v in (self.agent, self.mode) if v]],
        ):
            with self.client.start_as_current_observation(
                name='dataset-evaluation',
                trace_context={'trace_id': trace} if trace else None,
                input=record['input'],
                output=record['reply'],
                metadata={
                    'run_id': self.run_id,
                    'case_id': key[0],
                    'turn': key[1],
                    'agent_trace_missing': not bool(trace),
                    'agent': self.agent,
                    'mode': self.mode,
                },
            ) as span:
                span._otel_span.set_attributes(
                    {
                        'langfuse.environment': 'sdk-experiment',
                        'langfuse.experiment.id': self.experiment_id,
                        'langfuse.experiment.name': self.run_id,
                        'langfuse.experiment.dataset.id': self.remote.id,
                        'langfuse.experiment.item.id': self.items[key],
                        'langfuse.experiment.item.root_observation_id': span.id,
                        'langfuse.experiment.item.expected_output': json.dumps(
                            {'rubric': case.rubric, 'checks': case.checks}
                        ),
                    }
                )
                for name, value in record['scores']['values'].items():
                    if value is not None:
                        self.client.create_score(
                            name=name,
                            value=value,
                            trace_id=trace or span.trace_id,
                            score_id=str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL,
                                    self.run_id + '/' + key[0] + '/' + str(key[1]) + '/' + name,
                                )
                            ),
                            comment='formal'
                            if record['scores']['method'][name] == 'formal'
                            else record['scores']['method'][name],
                        )
        self.client.flush()

    async def verify_turn(self, record):
        from dnd_rag.experiments.codex import CodexRunner

        checker = CodexRunner(self.root)
        return await checker.verify_trace(
            record['reply']['trace_id'],
            record['reply']['text'],
            [t['name'] for t in record['tools']],
        )

    async def finish(self, records, metrics):
        for name in ('completion_rate', 'task_success_rate'):
            if metrics.get(name) is not None:
                self.client.create_score(
                    name=name,
                    value=metrics[name],
                    dataset_run_id=self.experiment_id,
                    score_id=str(uuid.uuid5(uuid.NAMESPACE_URL, self.run_id + '/run/' + name)),
                    comment='All scheduled executions retained in denominator',
                )
        self.client.flush()
        last = None
        for _ in range(30):
            try:
                rows = []
                cursor = None
                while True:
                    response = await asyncio.to_thread(
                        self.client.api.experiments.list_items,
                        from_start_time=datetime.now(UTC) - timedelta(days=1),
                        experiment_id=self.experiment_id,
                        limit=100,
                        cursor=cursor,
                    )
                    data = response.model_dump(mode='json')
                    rows += data['data']
                    cursor = data.get('meta', {}).get('nextCursor')
                    if not cursor:
                        break
                if len(rows) < len(records):
                    raise ValueError(f'Only{len(rows)}/{len(records)} Experiment items indexed')
                return rows
            except Exception as exc:
                last = exc
                await asyncio.sleep(1)
        raise RagError('experiment_readback', str(last))


async def run_dataset(
    dataset,
    adapter,
    *,
    run_id,
    mode,
    artifacts_dir,
    agent='own',
    manifest=None,
    provenance=None,
    tracker=None,
):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,70}', run_id):
        raise RagError('invalid_run_id', 'Use1..71 letters/digits/dot/dash/underscore')
    directory = Path(artifacts_dir) / run_id
    if directory.exists():
        raise RagError('run_exists', 'Use a new run ID; existing artifacts are never overwritten')
    directory.mkdir(parents=True)
    manifest = manifest or []
    provenance = provenance or {}
    run = {
        'run_id': run_id,
        'agent': agent,
        'mode': mode,
        'status': 'running',
        'evaluation_status': 'pending',
        'started_at': datetime.now(UTC).isoformat(),
        'dataset': dataset.model_dump(mode='json'),
        'manifest': provenance,
    }
    save_json(directory / 'run.json', run)
    save_json(
        directory / 'manifest.json',
        {'chunks': [m.model_dump() for m in manifest], 'provenance': provenance},
    )
    records = []
    histories = defaultdict(list)
    seen_compactions = defaultdict(int)
    try:
        for item in dataset.items:
            sid = run_id + '-' + uuid.uuid4().hex[:12]
            for number, case in enumerate(item.turns, 1):
                turn_id = f'{run_id}/{item.id}/{number}'
                events = []
                try:
                    reply = await adapter.ainvoke(
                        sid,
                        case.input,
                        turn_id=turn_id,
                        on_event=lambda e: events.append(e.model_dump(mode='json')),
                    )
                except Exception as exc:
                    reply = AgentReply(
                        text='',
                        status='error',
                        error={'code': 'adapter_error', 'message': str(exc)},
                    )
                raw = getattr(adapter, 'last_records', {}).get(sid, {})
                tools = normalized_tools(raw.get('tools', []))
                if raw.get('rollout') and Path(raw['rollout']).exists():
                    rows = [
                        json.loads(line) for line in Path(raw['rollout']).read_text().splitlines()
                    ]
                    compactions = [
                        r
                        for r in rows
                        if r.get('type') == 'compacted'
                        or r.get('payload', {}).get('type') == 'context_compacted'
                    ]
                    events += [
                        {'kind': 'compacted', 'payload': row}
                        for row in compactions[seen_compactions[sid] :]
                    ]
                    seen_compactions[sid] = len(compactions)
                record = {
                    'case_id': item.id,
                    'turn': number,
                    'turn_id': turn_id,
                    'session_id': sid,
                    'input': case.input,
                    'reply': reply.model_dump(mode='json'),
                    'tools': tools,
                    'events': events,
                    'raw_records': raw,
                }
                if tracker and agent == 'own' and reply.trace_id:
                    try:
                        observed = await tracker.verify_turn(record)
                        save_json(directory / 'observations' / item.id / f'{number}.json', observed)
                    except Exception as exc:
                        record['reply']['status'] = 'incomplete'
                        record['reply']['error'] = {'code': 'trace_readback', 'message': str(exc)}
                scored = score_records(dataset, [*records, record], manifest)[-1]
                # Keep partial progress durable before external linkage/readback.
                append_jsonl(directory / 'turns.jsonl', scored)
                for tool in tools:
                    append_jsonl(
                        directory / 'tool_calls.jsonl',
                        {'case_id': item.id, 'turn': number, 'session_id': sid, **tool},
                    )
                records.append(scored)
                histories[item.id].append(scored)
                if tracker:
                    try:
                        tracker.link(scored, case)
                    except Exception as exc:
                        run.setdefault('observability_errors', []).append(
                            {'turn_id': turn_id, 'error': str(exc)}
                        )
                print(f'{run_id} {item.id} {number}/{len(item.turns)} {reply.status}', flush=True)
            if hasattr(adapter, 'citations'):
                save_json(
                    directory / 'citations' / f'{sid}.json',
                    [r.model_dump(mode='json') for r in adapter.citations.export(sid)],
                )
            if hasattr(adapter, 'close_session'):
                await adapter.close_session(sid)
        write_review(directory / 'review.csv', dataset, records)
        metrics = summarize_records(dataset, records)
        if tracker:
            try:
                save_json(
                    directory / 'experiment-items.json', await tracker.finish(records, metrics)
                )
            except Exception as exc:
                run.setdefault('observability_errors', []).append({'error': str(exc)})
        run['status'] = (
            'completed'
            if metrics['completion_rate'] == 1 and not run.get('observability_errors')
            else 'incomplete'
        )
        run['evaluation_status'] = 'pending' if metrics['pending_executions'] else 'completed'
        if tracker:
            run.update(experiment_id=tracker.experiment_id, dataset_name=tracker.dataset_name)
        save_json(directory / 'metrics.json', metrics)
        return RunSummary(
            run_id=run_id,
            status=run['status'],
            executions=len(dataset.items),
            metrics=metrics,
            trace_links=[r['reply'].get('trace_id') for r in records],
        )
    except BaseException as exc:
        run.update(status='failed', error=str(exc))
        raise
    finally:
        run['finished_at'] = datetime.now(UTC).isoformat()
        save_json(directory / 'run.json', run)
        if not (directory / 'tool_calls.jsonl').exists():
            (directory / 'tool_calls.jsonl').touch()
