"""Mode-specific preflight and ready-or-full-build orchestration."""

import json
import re
import subprocess
import sys
import uuid
from time import monotonic, perf_counter, sleep

import httpx

from dnd_rag.contracts import EnsureResult, RagError, ReadyIndex, StageEvent
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.identity import library_versions, make_identity
from dnd_rag.indexing.store import QdrantStore


def ensure_qdrant(settings, session):
    session.require_active()
    store = QdrantStore(settings)
    try:
        server = store.server_version()
    except RagError:
        if settings.qdrant_url.rstrip('/') not in (
            'http://127.0.0.1:6333',
            'http://localhost:6333',
        ):
            raise
        try:
            process = subprocess.run(
                [
                    'docker',
                    'compose',
                    '-f',
                    str(settings.project_root / 'compose.yaml'),
                    'up',
                    '-d',
                    'qdrant',
                ],
                cwd=settings.project_root,
                capture_output=True,
                text=True,
                env={
                    **__import__('os').environ,
                    'QDRANT_STORAGE_VOLUME': settings.qdrant_storage_volume,
                },
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RagError('qdrant_startup', f'Cannot start Qdrant Compose: {exc}') from exc
        if process.returncode:
            raise RagError('qdrant_startup', f'Qdrant Compose failed: {process.stderr[-2000:]}')
        deadline = monotonic() + 60
        while True:
            try:
                server = store.server_version()
                break
            except RagError:
                if monotonic() >= deadline:
                    raise RagError('qdrant_startup', 'Qdrant readiness timed out after 60 seconds')
                sleep(0.25)
    if server != '1.20.0':
        raise RagError('qdrant_version', f'Expected Qdrant 1.20.0; got {server}')
    return store


def _check_gpu_conflict(settings):
    native = settings.llm_base_url.removesuffix('/v1').rstrip('/')
    try:
        response = httpx.get(native + '/health', timeout=1)
    except httpx.TransportError:
        return
    if response.status_code in (200, 503):
        raise RagError(
            'gpu_conflict',
            'A llama-server is running at the configured endpoint; '
            'stop it before GPU document preparation',
        )


def run_build_worker(config, settings, identity, session, on_stage):
    directory = settings.project_root / '.runtime/builds' / str(uuid.uuid4())
    directory.mkdir(parents=True)
    request = {
        'config': config.model_dump(mode='json'),
        'settings': settings.model_dump(mode='json'),
        'identity': identity.model_dump(mode='json'),
        'result_path': str(directory / 'result.json'),
        'stages_path': str(directory / 'stages.jsonl'),
    }
    request_path = directory / 'request.json'
    request_path.write_text(json.dumps(request), encoding='utf-8')
    events, consumed = [], 0
    with (directory / 'worker.log').open('w', encoding='utf-8') as log:
        process = session.spawn(
            [sys.executable, '-m', 'dnd_rag.indexing.build', '--request', str(request_path)],
            stdout=log,
        )
        while True:
            path = directory / 'stages.jsonl'
            lines = path.read_text().splitlines() if path.exists() else []
            for line in lines[consumed:]:
                try:
                    event = StageEvent.model_validate_json(line)
                except ValueError:
                    break  # A concurrent final line may not have been flushed yet.
                events.append(event)
                on_stage(event)
                consumed += 1
            if process.poll() is not None:
                break
            sleep(0.1)
    result_path = directory / 'result.json'
    if not result_path.exists():
        raise RagError(
            'build_worker_failed',
            f'GPU worker exited {process.returncode}; see {directory}/worker.log',
        )
    result = json.loads(result_path.read_text())
    if process.returncode or 'error' in result:
        error = result.get('error', {'code': 'build_worker_failed', 'message': 'GPU worker failed'})
        raise RagError(
            error['code'],
            error['message'],
            {'worker_directory': str(directory), 'cause': error.get('details')},
        )
    # Read any final event appended between the last poll and worker exit.
    all_events = [StageEvent.model_validate(e) for e in result['stages']]
    for event in all_events[consumed:]:
        events.append(event)
        on_stage(event)
    return ReadyIndex.model_validate(result['index']), events


def ensure_index(config, settings, session, *, rebuild=False, on_stage=None):
    session.require_active()
    stages = []

    def record(event):
        stages.append(event)
        if on_stage is not None:
            on_stage(event)

    before = perf_counter()
    corpus = load_corpus(config.corpus.directory)
    record(
        StageEvent(
            name='corpus_validation', status='executed', elapsed_ms=(perf_counter() - before) * 1000
        )
    )
    before = perf_counter()
    store = ensure_qdrant(settings, session)
    record(
        StageEvent(
            name='qdrant_readiness', status='executed', elapsed_ms=(perf_counter() - before) * 1000
        )
    )
    identity = make_identity(config, corpus, library_versions(store.server_version()))
    before = perf_counter()
    inspection = store.inspect(identity)
    record(
        StageEvent(
            name='index_inspection', status='executed', elapsed_ms=(perf_counter() - before) * 1000
        )
    )
    if inspection.status == 'ready' and not rebuild:
        for name in (
            'tokenizer_load',
            'splitting',
            'document_model_load',
            'embedding',
            'upload',
            'index_wait',
        ):
            record(StageEvent(name=name, status='reused', elapsed_ms=None))
        record(
            StageEvent(
                name='bm25_index',
                status='reused' if config.retrieval.mode == 'hybrid' else 'skipped',
                elapsed_ms=None,
            )
        )
        return EnsureResult(
            index=inspection.index, action='reused', reason=inspection.reason, stages=stages
        )
    _check_gpu_conflict(settings)
    ready, _ = run_build_worker(config, settings, identity, session, record)
    action = 'built' if inspection.status == 'missing' else 'rebuilt'
    reason = 'Forced full rebuild' if rebuild else inspection.reason
    return EnsureResult(index=ready, action=action, reason=reason, stages=stages)


def reset_index(settings, session, *, config=None, index_id=None):
    if (config is None) == (index_id is None):
        raise RagError('invalid_selector', 'Exactly one of config or index_id is required')
    if index_id is not None and not re.fullmatch('[a-f0-9]{64}', index_id):
        raise RagError('invalid_index_id', 'Expected a full lowercase SHA256 index_id')
    session.require_active()
    store = ensure_qdrant(settings, session)
    if config is not None:
        corpus = load_corpus(config.corpus.directory)
        index_id = make_identity(config, corpus, library_versions(store.server_version())).index_id
    return store.reset(index_id)
