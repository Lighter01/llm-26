"""Launch one owned llama.cpp server; placement and timeouts are explicit."""

import json
import math
import shutil
import subprocess
from hashlib import file_digest, sha256
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlparse

import httpx

from dnd_rag.contracts import RagError
from dnd_rag.runtime.llm import LLMClient
from dnd_rag.runtime.preflight import connection_refused


def resolve_binary(settings):
    value = str(Path(settings.llama_server_bin).expanduser())
    resolved = shutil.which(value)
    if resolved is None:
        candidate = (settings.project_root / value).resolve()
        if candidate.is_file():
            resolved = str(candidate)
    if not resolved:
        raise RagError('llama_binary_missing', f'llama-server executable not found: {value}')
    return resolved


def binary_version(binary, profile):
    command = [binary, 'version'] if profile.server_subcommand else [binary, '--version']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RagError(
            'llama_binary_invalid', f'Cannot inspect llama.cpp executable: {exc}'
        ) from exc
    if result.returncode:
        raise RagError('llama_binary_invalid', result.stderr[-1000:])
    return (result.stdout + result.stderr).strip()


def server_argv(settings, profile):
    placement = ('gpu_layers', 'batch_size', 'ubatch_size', 'cache_type_k', 'cache_type_v')
    if any(getattr(profile, key) is None for key in placement):
        raise RagError(
            'invalid_llm_profile',
            'Set explicit GPU layers, batch/ubatch and KV types before launch',
        )
    url = urlparse(settings.llm_base_url)
    if (
        url.scheme != 'http'
        or url.hostname not in ('127.0.0.1', 'localhost', '::1')
        or url.path.rstrip('/') != '/v1'
    ):
        raise RagError(
            'invalid_llm_url', 'Managed llama.cpp requires a loopback http://HOST:PORT/v1 URL'
        )
    binary = resolve_binary(settings)
    argv = [binary]
    if profile.server_subcommand:
        argv.append(profile.server_subcommand)
    argv.extend(
        [
            '--model',
            str(settings.model_path),
            '--alias',
            profile.model_alias,
            '--host',
            url.hostname,
            '--port',
            str(url.port or 8080),
            '--ctx-size',
            str(profile.context_size),
            '--n-predict',
            str(profile.max_output_tokens),
            '--parallel',
            '1',
            '--gpu-layers',
            str(profile.gpu_layers),
            '--batch-size',
            str(profile.batch_size),
            '--ubatch-size',
            str(profile.ubatch_size),
            '--cache-type-k',
            profile.cache_type_k,
            '--cache-type-v',
            profile.cache_type_v,
            '--kv-offload' if profile.kv_offload else '--no-kv-offload',
            '--flash-attn',
            profile.flash_attention,
            '--fit',
            'off',
            '--no-context-shift',
            '--reasoning',
            'off',
            '--jinja',
            '--chat-template-kwargs',
            '{"enable_thinking":false}',
            '--threads',
            str(profile.threads),
            '--threads-batch',
            str(profile.threads),
            '--temp',
            str(profile.temperature),
            '--top-p',
            str(profile.top_p),
            '--top-k',
            str(profile.top_k),
            '--min-p',
            str(profile.min_p),
            '--seed',
            str(profile.seed),
            '--no-cache-prompt',
            '--metrics',
            '--no-webui',
            '--timeout',
            str(math.ceil(profile.http_timeout_seconds)),
        ]
    )
    return argv


def _verify_server(client, settings, profile):
    props = client._request('GET', '/props')
    if (
        Path(props.get('model_path', '')).resolve() != settings.model_path.resolve()
        or props.get('default_generation_settings', {}).get('n_ctx') != profile.context_size
        or props.get('total_slots') != 1
        or not props.get('chat_template')
    ):
        raise RagError(
            'llm_conflict',
            'Running llama.cpp model/context/template does not match the selected profile',
        )
    return props


def start_llama(settings, profile, session, *, http_client=None):
    session.require_active()
    client = LLMClient(settings, profile, http_client=http_client)
    try:
        try:
            response = client.http.get(client.native_url + '/health', timeout=2)
        except httpx.TransportError as exc:
            if not connection_refused(exc):
                raise RagError(
                    'llm_preflight_failed',
                    'Cannot verify that the LLM endpoint is free; no server was started',
                ) from exc
            response = None
        if response is not None:
            raise RagError(
                'llm_conflict',
                'The configured LLM endpoint is already occupied; '
                'its complete launch profile cannot be verified. Stop that server before this managed launch.',
            )
        argv = server_argv(settings, profile)
        if not settings.model_path.is_file():
            raise RagError('llm_model_missing', f'GGUF not found: {settings.model_path}')
        version = binary_version(argv[0], profile)
        with settings.model_path.open('rb') as model_file:
            model_sha256 = file_digest(model_file, 'sha256').hexdigest()
        directory = settings.project_root / '.runtime/llama'
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / 'server.log'
        with log_path.open('w') as log:
            process = session.spawn(argv, stdout=log)
        deadline = monotonic() + profile.startup_timeout_seconds
        while not client.is_ready():
            if process.poll() is not None:
                raise RagError(
                    'llm_startup_failed', f'llama.cpp exited {process.returncode}; see {log_path}'
                )
            if monotonic() >= deadline:
                raise RagError(
                    'llm_startup_timeout', f'llama.cpp readiness timed out; see {log_path}'
                )
            sleep(0.1)
        props = _verify_server(client, settings, profile)
        client.server_provenance = {
            'binary_version': version,
            'argv': argv,
            'profile': profile.model_dump(),
            'model_path': str(settings.model_path),
            'model_size_bytes': settings.model_path.stat().st_size,
            'model_sha256': model_sha256,
            'template_sha256': sha256(props['chat_template'].encode()).hexdigest(),
            'pid': process.pid,
            'server_props': props,
        }
        (directory / 'instance.json').write_text(
            json.dumps(client.server_provenance, indent=2), encoding='utf-8'
        )
        return client
    except BaseException:
        client.close()
        raise
