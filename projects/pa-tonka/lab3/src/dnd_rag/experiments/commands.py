"""CLI orchestration; the runner itself has no model/server/TTY dependency."""

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from hashlib import sha256

from dnd_rag.agent.config import AgentConfig
from dnd_rag.agent.observability import ObservationRecorder
from dnd_rag.agent.service import AgentService
from dnd_rag.config import load_llm_profile, load_rag_config, load_settings, resolve_path
from dnd_rag.contracts import RagError
from dnd_rag.experiments.artifacts import (
    export_comparison,
    freeze_fingerprint,
    load_reviews,
    read_jsonl,
    recompute,
    save_json,
)
from dnd_rag.experiments.codex import CodexRunner
from dnd_rag.experiments.dataset import load_dataset
from dnd_rag.experiments.runner import ExperimentTracker, run_dataset
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.runtime.application import application_stack


def experiment_provenance(root, app, dataset, agent_config):
    instance = json.loads((root / '.runtime/llama/instance.json').read_text())
    paths = []
    for name in ('agent', 'runtime', 'tools', 'game', 'indexing'):
        paths.extend(
            p
            for p in (root / 'src/dnd_rag' / name).rglob('*')
            if p.suffix in ('.py', '.txt', '.yaml', '.json', '.toml', '.mjs')
        )
    paths += [
        root / 'src/dnd_rag/config.py',
        root / 'src/dnd_rag/retrieval.py',
        root / 'src/dnd_rag/contracts.py',
        root / 'src/dnd_rag/experiments/codex.py',
        root / 'uv.lock',
        root / 'pyproject.toml',
    ]
    paths += [p for p in (root / 'configs').rglob('*') if p.suffix in ('.yaml', '.json', '.toml')]
    common = {
        'dataset_sha256': dataset.fingerprint,
        'selection': [item.id for item in dataset.items],
        'files': freeze_fingerprint(root, paths),
        'model_sha256': instance.get('model_sha256'),
        'template_sha256': instance.get('template_sha256'),
        'index_id': app.retriever.index.index_id,
        'build_id': app.retriever.index.build_id,
        'catalog': app.catalog.manifest,
        'agent_config': agent_config.model_dump(mode='json'),
    }
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {
        'common_fingerprint': sha256(json.dumps(common, sort_keys=True).encode()).hexdigest(),
        'common': common,
        'effective_profile': app.profile.model_dump(mode='json'),
        'model_instance': instance,
        'git_head': commit,
        'local_api_cost': 0.0,
        'codex_plugin_commit': 'e1d02be28e6bacbfe350a1bc1ccf861e54edee17',
    }


def evaluate_command(root, args):
    config = load_rag_config(args.config, project_root=root)
    dataset = load_dataset(
        resolve_path(args.dataset, root), load_corpus(config.corpus.directory), require_shape=True
    )
    if args.only:
        if set(args.only) - {i.id for i in dataset.items}:
            raise RagError('invalid_selection', 'Unknown dataset item ID')
        dataset = dataset.model_copy(
            update={'items': [i for i in dataset.items if i.id in args.only]}
        )
    profile = load_llm_profile(
        resolve_path(args.llm_profile or f'configs/llm/{args.mode}.yaml', root)
    )
    if profile.thinking != (args.mode == 'budgeted'):
        raise RagError('invalid_mode', 'Profile thinking must match the declared run mode')
    agent_config = AgentConfig(context_limit=args.context_limit, timeout_seconds=args.timeout)
    run_id = (
        args.run_id or f'{args.agent}-{args.mode}-{datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")}'
    )
    output = resolve_path(args.results_dir, root)
    if (output / run_id).exists():
        raise RagError('run_exists', 'Existing run ID is never overwritten')
    with application_stack(
        load_settings(root),
        agent_config,
        profile,
        rag_config=config,
        rebuild=args.rebuild,
        on_stage=lambda s: print('Preparing ' + s, flush=True),
    ) as app:
        tracker = ExperimentTracker(root, dataset, run_id, agent=args.agent, mode=args.mode)
        adapter = (
            AgentService(
                native_llm=app.native,
                config=agent_config,
                recorder=ObservationRecorder(output / run_id / 'raw/own', project_root=root),
            )
            if args.agent == 'own'
            else CodexRunner(
                root,
                mode=args.mode,
                artifacts_dir=output / run_id / 'raw/codex',
                context_limit=agent_config.context_limit,
                timeout_seconds=args.timeout,
            )
        )
        provenance = experiment_provenance(root, app, dataset, agent_config)
        provenance['selection'] = [i.id for i in dataset.items]

        async def run():
            try:
                return await run_dataset(
                    dataset,
                    adapter,
                    run_id=run_id,
                    mode=args.mode,
                    agent=args.agent,
                    artifacts_dir=output,
                    manifest=app.retriever.store.manifest(app.retriever.index),
                    provenance=provenance,
                    tracker=tracker,
                )
            finally:
                await adapter.aclose()
                if adapter is not app.service:
                    await app.service.aclose()

        summary = asyncio.run(run())
    print(summary.model_dump_json(indent=2))
    return 0 if summary.status == 'completed' else 1


def score_command(root, args):
    directory = resolve_path(args.run, root)
    review = resolve_path(args.review, root) if args.review else directory / 'review.csv'
    metrics = recompute(directory, review_path=review, write=True)
    run = json.loads((directory / 'run.json').read_text())
    run['evaluation_status'] = 'pending' if metrics['pending_executions'] else 'completed'
    run['review_file'] = str(review)
    run['evaluation_provenance'] = {
        'method': 'explicit-criterion-review',
        'review_sha256': sha256(review.read_bytes()).hexdigest(),
        'files': freeze_fingerprint(
            root,
            [
                root / 'src/dnd_rag/experiments/scoring.py',
                root / 'src/dnd_rag/experiments/artifacts.py',
                root / 'src/dnd_rag/experiments/contracts.py',
                root / 'src/dnd_rag/evaluation/evidence.py',
                root / 'src/dnd_rag/evaluation/metrics.py',
            ],
        ),
    }
    if review != directory / 'review.csv':
        import shutil

        shutil.copyfile(review, directory / 'review.csv')
    if args.upload_scores:
        client = ObservationRecorder(root / '.runtime/sessions', project_root=root).client
        if client is None:
            raise RagError('observability_config', 'Score upload requires Langfuse credentials')
        import uuid

        annotations = load_reviews(review)
        for record in read_jsonl(directory / 'scored_turns.jsonl'):
            for name, value in record['scores']['values'].items():
                if value is None:
                    continue
                annotation = annotations.get((record['case_id'], record['turn']), {}).get(name, {})
                client.create_score(
                    name=name,
                    value=value,
                    trace_id=record['reply'].get('trace_id'),
                    score_id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            run['run_id']
                            + '/'
                            + record['case_id']
                            + '/'
                            + str(record['turn'])
                            + '/'
                            + name,
                        )
                    ),
                    comment=json.dumps(annotation or {'method': 'formal'}),
                )
        if metrics['task_success_rate'] is not None:
            client.create_score(
                name='task_success_rate',
                value=metrics['task_success_rate'],
                dataset_run_id=run.get('experiment_id'),
                score_id=str(
                    uuid.uuid5(uuid.NAMESPACE_URL, run['run_id'] + '/run/task_success_rate')
                ),
                comment='Reviewed all mandatory criteria',
            )
        client.flush()
    save_json(directory / 'run.json', run)
    print(json.dumps(metrics, indent=2))
    return 0 if run['evaluation_status'] == 'completed' else 1


def summarize_command(root, args):
    path = export_comparison([resolve_path(p, root) for p in args.runs])
    print(path)
    return 0
