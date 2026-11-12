"""One ordered lifecycle for CLI, smoke and experiments."""

import asyncio
import logging
import socket
import subprocess
import threading
from contextlib import contextmanager
from time import monotonic, sleep
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
import uvicorn

from dnd_rag.agent.observability import ObservationRecorder
from dnd_rag.agent.service import AgentService
from dnd_rag.config import load_rag_config
from dnd_rag.contracts import RagError
from dnd_rag.game.prepare import ensure_game_catalog
from dnd_rag.runtime.codex_proxy import create_codex_proxy
from dnd_rag.runtime.index import ensure_qdrant, prepare_retriever
from dnd_rag.runtime.llama import start_llama
from dnd_rag.runtime.preflight import connection_refused
from dnd_rag.runtime.processes import RuntimeSession
from dnd_rag.tools.server import ToolServices, create_mcp_server


def ensure_infrastructure(settings, runtime):
    ensure_qdrant(settings, runtime)
    recorder = ObservationRecorder(
        settings.project_root / '.runtime/sessions', project_root=settings.project_root
    )
    if recorder.client is None:
        raise RagError(
            'observability_config',
            'Set local LANGFUSE_PUBLIC_KEY/SECRET_KEY and Compose init credentials in .env',
        )
    url = recorder.base_url.rstrip('/') + '/api/public/health'
    try:
        response = httpx.get(url, timeout=5)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        if not connection_refused(exc) or urlparse(url).hostname not in ('127.0.0.1', 'localhost'):
            raise RagError('langfuse_unavailable', f'Langfuse health check failed: {exc}') from exc
        root = settings.project_root
        argv = ['docker']
        if (root / '.runtime/docker-public/config.json').exists():
            argv += ['--config', str(root / '.runtime/docker-public')]
        argv += [
            'compose',
            '--project-name',
            'dnd-rag-lab3',
            '--env-file',
            str(root / '.env'),
            '-f',
            str(root / 'compose.yaml'),
            '-f',
            str(root / 'infra/langfuse.compose.yaml'),
            'up',
            '-d',
            '--build',
            'langfuse-web',
            'langfuse-worker',
        ]
        try:
            result = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RagError('langfuse_startup', str(error)) from error
        if result.returncode:
            raise RagError('langfuse_startup', result.stderr[-2000:])
        deadline = monotonic() + 120
        while True:
            try:
                if httpx.get(url, timeout=3).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if monotonic() > deadline:
                raise RagError('langfuse_startup', 'Langfuse readiness timed out')
            sleep(0.5)
    if not recorder.client.auth_check():
        raise RagError('observability_auth', 'Local Langfuse SDK credentials were rejected')


@contextmanager
def background_server(app, *, port, host='127.0.0.1'):
    # Bind first to distinguish an occupied port; never adopt or kill foreign servers.
    with socket.socket() as probe:
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise RagError('occupied_port', f'Cannot bind {host}:{port}: {exc}') from exc
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level='warning', access_log=False)
    )
    errors = []

    def run():
        try:
            server.run()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 15
        while not server.started:
            if errors or not thread.is_alive() or monotonic() > deadline:
                raise RagError(
                    'service_startup', f'Local service on {port} failed readiness: {errors}'
                )
            sleep(0.03)
        yield server
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise RagError('service_cleanup', f'Local service on {port} did not stop')


@contextmanager
def application_stack(
    settings, agent_config, llm_profile, *, rag_config=None, rebuild=False, on_stage=None
):
    for logger in ('mcp', 'httpx', 'httpcore'):
        logging.getLogger(logger).setLevel(logging.WARNING)
    root = settings.project_root
    config = rag_config or load_rag_config(None, project_root=root)
    with RuntimeSession(root) as runtime:
        if on_stage:
            on_stage('infrastructure')
        ensure_infrastructure(settings, runtime)
        if on_stage:
            on_stage('catalog')
        catalog = ensure_game_catalog(root)
        if on_stage:
            on_stage('index')
        retriever = prepare_retriever(config, settings, runtime, rebuild=rebuild)
        # prepare_retriever returns only after the GPU document worker exits.
        if on_stage:
            on_stage('llama')
        native = start_llama(settings, llm_profile, runtime)
        recorder = ObservationRecorder(root / '.runtime/sessions', project_root=root)
        service = AgentService(native_llm=native, config=agent_config, recorder=recorder)
        mcp = create_mcp_server(ToolServices(retriever, catalog))
        port = urlparse(agent_config.mcp_url).port or 8765
        try:
            with background_server(mcp.streamable_http_app(), port=port):
                with background_server(
                    create_codex_proxy(native, root / '.runtime/codex-wire', recorder=recorder),
                    port=8081,
                ):
                    if on_stage:
                        on_stage('ready')
                    yield SimpleNamespace(
                        service=service,
                        native=native,
                        recorder=recorder,
                        retriever=retriever,
                        catalog=catalog,
                        settings=settings,
                        profile=llm_profile,
                        rag_config=config,
                    )
        finally:
            if native is not None:
                native.close()


def run_application(
    settings, agent_config, llm_profile, *, interface='cli', rebuild=False, rag_config=None
):
    from rich.console import Console

    from dnd_rag.cli import run_cli

    if interface != 'cli':
        raise RagError('invalid_interface', 'Only cli is currently implemented')
    console = Console(stderr=True)
    with application_stack(
        settings,
        agent_config,
        llm_profile,
        rag_config=rag_config,
        rebuild=rebuild,
        on_stage=lambda stage: console.print(f'[dim]Preparing {stage}…[/dim]'),
    ) as app:

        async def run():
            try:
                return await run_cli(
                    app.service,
                    model=llm_profile.model_alias,
                    trace_url=app.recorder.trace_url,
                    history_path=settings.project_root / '.runtime/cli.history',
                )
            finally:
                await app.service.aclose()

        try:
            return asyncio.run(run())
        except KeyboardInterrupt:
            return 0


def run_smoke(
    settings,
    agent_config,
    llm_profile,
    *,
    agents='both',
    output=None,
    rebuild=False,
    rag_config=None,
):
    import json
    import uuid

    from dnd_rag.experiments.codex import CodexRunner

    rows = []
    with application_stack(
        settings, agent_config, llm_profile, rebuild=rebuild, rag_config=rag_config
    ) as app:

        async def run():
            adapters = {
                'own': app.service,
                'codex': CodexRunner(
                    settings.project_root,
                    mode='budgeted' if llm_profile.thinking else 'off',
                    context_limit=agent_config.context_limit,
                ),
            }
            try:
                for name, adapter in adapters.items():
                    if agents not in ('both', name):
                        continue
                    sid = 'smoke-' + name + '-' + uuid.uuid4().hex[:12]
                    for n, text in enumerate(
                        [
                            'Remember four level-6 adventurers. Use evaluate_encounter for exactly two Mages. State the XP and category briefly.',
                            'We now have three adventurers, still level6. Re-evaluate the same enemies. State updated budgets briefly.',
                        ],
                        1,
                    ):
                        reply = await adapter.ainvoke(sid, text, turn_id=f'turn-{n}')
                        rows.append(
                            {
                                'agent': name,
                                'session_id': sid,
                                'turn': n,
                                'reply': reply.model_dump(mode='json'),
                                'records': adapter.last_records.get(sid, {}),
                            }
                        )
            finally:
                await app.service.aclose()

        asyncio.run(run())
    result = {
        'status': 'completed'
        if rows
        and all(r['reply']['status'] == 'completed' and r['reply']['trace_id'] for r in rows)
        else 'incomplete',
        'turns': rows,
    }
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized)
    print(serialized)
    return 0 if result['status'] == 'completed' else 1
