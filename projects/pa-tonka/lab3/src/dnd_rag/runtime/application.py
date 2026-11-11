"""Mode-specific preflight and ready-or-full-build orchestration."""

import json
import os
import re
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from threading import Event, Thread
from time import monotonic, perf_counter, sleep
from urllib.parse import urlparse

import httpx

from dnd_rag.contracts import EnsureResult, RagError, ReadyIndex, StageEvent
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.identity import library_versions, make_identity
from dnd_rag.indexing.store import QdrantStore
from dnd_rag.runtime.preflight import connection_refused, native_llm_url


def ensure_qdrant(settings, session):
    session.require_active()
    store = QdrantStore(settings)
    try:
        server = store.server_version()
    except RagError as exc:
        if not connection_refused(exc) or settings.qdrant_url.rstrip('/') not in (
            'http://127.0.0.1:6343',
            'http://localhost:6343',
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
    native = native_llm_url(settings.llm_base_url)
    try:
        response = httpx.get(native + '/health', timeout=1)
    except httpx.TransportError as exc:
        if connection_refused(exc):
            return
        raise RagError(
            'llm_preflight_failed',
            'Cannot verify that the LLM endpoint is free; GPU preparation was not started',
        ) from exc
    raise RagError(
        'gpu_conflict',
        f'The configured LLM endpoint responded with HTTP {response.status_code}; '
        'stop that service before GPU document preparation',
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


def _api_address(settings):
    url = urlparse(settings.rag_api_url)
    if (
        url.scheme != 'http'
        or url.hostname not in ('127.0.0.1', 'localhost')
        or url.path not in ('', '/')
        or url.query
        or url.fragment
        or url.username
    ):
        raise RagError('invalid_api_url', 'RAG_API_URL must be a local http://host:port URL')
    try:
        return url.hostname, url.port or 8000
    except ValueError as exc:
        raise RagError('invalid_api_url', 'RAG_API_URL must have a valid port') from exc


def _preflight_http(settings, *, demo):
    addresses = [_api_address(settings)]
    if demo:
        addresses.append(('127.0.0.1', 8501))
    if len({port for host, port in addresses}) != len(addresses):
        raise RagError('invalid_api_url', 'API and UI must use different ports')
    for host, port in addresses:
        try:
            with socket.socket() as probe:
                # Match Uvicorn's bind: TIME_WAIT from our last run is not a listener.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind((host, port))
        except OSError as exc:
            raise RagError(
                'http_conflict', f'Cannot bind {host}:{port}; stop the conflicting service'
            ) from exc


def _load_retriever(index, config, settings):
    from dnd_rag.indexing.embedding import QueryEncoder
    from dnd_rag.retrieval import Retriever

    encoder = QueryEncoder(config.embedding, settings)
    return Retriever(index, config, encoder, QdrantStore(settings))


def _start_llm(settings, profile, session):
    from dnd_rag.runtime.llama import start_llama

    return start_llama(settings, profile, session)


def _make_app(retriever, rag):
    from dnd_rag.api import create_app

    return create_app(retriever, rag)


def _start_ui(settings, session):
    log_path = settings.project_root / '.runtime/ui.log'
    with log_path.open('a', encoding='utf-8') as stream:
        return session.spawn(
            [
                sys.executable,
                '-m',
                'streamlit',
                'run',
                str(Path(__file__).resolve().parents[1] / 'ui.py'),
                '--server.address',
                '127.0.0.1',
                '--server.port',
                '8501',
                '--server.headless',
                'true',
                '--server.fileWatcherType',
                'none',
                '--browser.gatherUsageStats',
                'false',
            ],
            env={'RAG_API_URL': settings.rag_api_url},
            stdout=stream,
        )


def _serve_http(app, settings, session, on_ready):
    import uvicorn

    host, port = _api_address(settings)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, workers=1, reload=False))
    stopped, failures = Event(), []

    def supervise():
        try:
            deadline = monotonic() + 60
            with httpx.Client(timeout=2) as client:
                while not stopped.is_set():
                    if server.started:
                        try:
                            response = client.get(settings.rag_api_url.rstrip('/') + '/health')
                            if response.status_code == 200:
                                child = on_ready()
                                break
                        except httpx.TransportError:
                            pass
                    if monotonic() >= deadline:
                        raise RagError(
                            'api_startup_timeout', 'API did not become ready within 60 seconds'
                        )
                    stopped.wait(0.1)
                else:
                    return
            while not stopped.wait(0.25):
                if child is not None and child.poll() is not None:
                    raise RagError('ui_exited', 'Streamlit exited; see .runtime/ui.log')
        except Exception as exc:
            failures.append(exc)
            server.should_exit = True

    monitor = Thread(target=supervise, name='dnd-service-supervisor', daemon=True)
    monitor.start()
    try:
        server.run()
    finally:
        stopped.set()
        monitor.join(timeout=5)
    if failures:
        raise failures[0]


def _run_service(config_path, settings, *, profile_path=None, rebuild=False, on_event=None):
    from dnd_rag.config import load_experiment, load_llm_profile, resolve_path
    from dnd_rag.runtime.processes import RuntimeSession

    config = load_experiment(config_path, project_root=settings.project_root)
    profile = (
        load_llm_profile(resolve_path(profile_path, settings.project_root))
        if profile_path is not None
        else None
    )
    events, llm = [], None
    started = perf_counter()
    report_path = settings.project_root / '.runtime/startup.json'
    report = {'mode': 'qa' if profile else 'retrieval_only', 'pid': os.getpid(), 'events': events}

    def event(name):
        item = {'name': name, 'elapsed_ms': (perf_counter() - started) * 1000}
        events.append(item)
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(item), file=sys.stderr, flush=True)
        if on_event:
            on_event(name)

    with RuntimeSession(settings.project_root) as session:
        _preflight_http(settings, demo=profile is not None)
        try:
            ensured = ensure_index(config, settings, session, rebuild=rebuild)
            report.update(
                index_action=ensured.action,
                index_id=ensured.index.index_id,
                build_id=ensured.index.build_id,
                ensure_stages=[stage.model_dump(mode='json') for stage in ensured.stages],
            )
            event('index_ready')
            # ensure_index returns only after the GPU worker exits. Reuse spawns none.
            event('gpu_worker_exited')
            retriever = _load_retriever(ensured.index, config, settings)
            event('cpu_query_loaded')
            rag = None
            if profile is not None:
                from dnd_rag.rag.service import RagService

                llm = _start_llm(settings, profile, session)
                rag = RagService(retriever, llm, profile)
                event('llm_ready')
            app = _make_app(retriever, rag)

            def ready():
                event('api_ready')
                if profile is not None:
                    process = _start_ui(settings, session)
                    event('ui_started')
                    return process
                return None

            _serve_http(app, settings, session, ready)
        finally:
            if llm is not None:
                llm.close()


def serve_retrieval(config_path, settings, *, rebuild=False, on_event=None):
    """Ensure the index, load one CPU query encoder and run a single API worker."""
    _run_service(config_path, settings, rebuild=rebuild, on_event=on_event)


def run_demo(config_path, profile_path, settings, *, rebuild=False, on_event=None):
    """Own the complete index → CPU → LLM → API → HTTP-only UI lifecycle."""
    _run_service(
        config_path, settings, profile_path=profile_path, rebuild=rebuild, on_event=on_event
    )
