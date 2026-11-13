"""Isolated Codex exec/resume adapter and pinned closed-rollout exporter."""

import asyncio
import json
import os
import shutil
import signal
import tempfile
import tomllib
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from dotenv import dotenv_values

from dnd_rag.agent.contracts import AgentReply, ContextStats
from dnd_rag.agent.service import SYSTEM_PROMPT


def parse_events(stdout):
    result = {
        'text': '',
        'session_id': None,
        'usage': None,
        'error': None,
        'tools': [],
        'events': [],
    }
    for line in stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        result['events'].append(row)
        kind = row.get('type')
        if kind == 'thread.started':
            result['session_id'] = row.get('thread_id')
        elif kind == 'item.completed':
            item = row.get('item', {})
            if item.get('type') == 'agent_message':
                result['text'] = item.get('text', '')
            elif item.get('type') == 'mcp_tool_call':
                result['tools'].append(item)
        elif kind == 'turn.completed':
            result['usage'] = row.get('usage')
        elif kind in ('error', 'turn.failed'):
            result['error'] = row.get('error', row.get('message', row))
    return result


def validate_trace_observations(rows, *, final_text, expected_tools):
    generations = [r for r in rows if r.get('type', '').upper() == 'GENERATION']
    if not generations or any(
        not r.get('usageDetails') or r.get('input') is None or r.get('output') is None
        for r in generations
    ):
        raise ValueError('Missing generation input/output or usage in Langfuse export')

    def strings(value):
        if isinstance(value, str):
            yield value
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                decoded = None
            if isinstance(decoded, (dict, list)):
                yield from strings(decoded)
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    if final_text and not any(
        final_text in text for r in rows for text in strings(r.get('output'))
    ):
        raise ValueError('Last assistant reply is missing from Langfuse export')
    for tool in expected_tools:
        if not any(tool in r.get('name', '') for r in rows):
            raise ValueError('Missing tool observation: ' + tool)


def wire_usage(rows):
    requests = [r for r in rows if r.get('kind') == 'request']
    responses = {
        r['id']: r.get('response', {}).get('usage', {}) for r in rows if r.get('kind') == 'response'
    }
    complete = bool(requests) and all(r['id'] in responses for r in requests)
    result = {
        'model_calls': len(requests),
        'max_context_tokens': max((r['input_tokens'] for r in requests), default=None),
    }
    for key in ('input_tokens', 'output_tokens'):
        values = [responses.get(r['id'], {}).get(key) for r in requests]
        result[key] = sum(values) if complete and all(type(v) is int for v in values) else None
    return result


def config_args(config, prefix=''):
    result = []
    for key, value in config.items():
        key = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            result += config_args(value, key)
        else:
            result += ['-c', key + '=' + json.dumps(value)]
    return result


async def _capture_owned(process, *, timeout, data=None):
    # Cancelling communicate discards bytes already read from its pipes. Keep one
    # capture alive through timeout/cancellation, and reap only our process group.
    capture = asyncio.create_task(process.communicate(data))
    cancelled = timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(asyncio.shield(capture), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError) as interrupted:
        cancelled = isinstance(interrupted, asyncio.CancelledError)
        timed_out = True
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            stdout, stderr = await asyncio.wait_for(asyncio.shield(capture), timeout=5)
        except TimeoutError:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            stdout, stderr = await capture
    return stdout, stderr, timed_out, cancelled


class CodexRunner:
    def __init__(
        self,
        project_root,
        *,
        mode='off',
        artifacts_dir=None,
        timeout_seconds=300,
        context_limit=9500,
    ):
        self.root = Path(project_root)
        from dnd_rag.agent.citations import CitationRegistry

        self.citations = CitationRegistry(self.root / '.runtime/citations')
        self.mode = mode
        self.directory = artifacts_dir or self.root / '.runtime/benchmark'
        self.work = Path(tempfile.mkdtemp(prefix='lab3-codex-'))
        self.timeout = timeout_seconds
        self.context_limit = context_limit
        self.sessions = {}
        self.last_records = {}
        self.values = {**dotenv_values(self.root / '.env'), **os.environ}
        self.plugin = self.root / '.runtime/codex-plugin/plugins/tracing/dist/index.mjs'
        self.node = shutil.which('node') or str(
            self.root / 'tools/ingestion/node_modules/.bin/node'
        )

    def command(self, session_id, user_text, *, mode=None):
        cfg = tomllib.loads((self.root / 'configs/baseline/codex.toml').read_text())
        cfg['model_reasoning_effort'] = 'medium' if (mode or self.mode) == 'budgeted' else 'none'
        cfg['model_auto_compact_token_limit'] = self.context_limit
        cfg['developer_instructions'] = SYSTEM_PROMPT
        cfg['model_catalog_json'] = str(self.root / 'configs/baseline/models.json')
        cfg['model_providers']['lab3']['base_url'] = 'http://127.0.0.1:8081/v1'
        turn_number = self.sessions.get(session_id, {}).get('turns', 0) + 1
        cfg['model_providers']['lab3']['http_headers'] = {
            'X-DND-Session-Id': session_id,
            'X-DND-Trace-Id': sha256(f'{session_id}:{turn_number}'.encode()).hexdigest()[:32],
        }
        cfg['mcp_servers']['dnd']['http_headers'] = {'X-DND-Session-Id': session_id}
        argv = [
            'codex',
            'exec',
            '--ignore-user-config',
            '--strict-config',
            '--skip-git-repo-check',
            '--json',
            '--color',
            'never',
            '-C',
            str(self.work),
        ]
        argv += config_args(cfg)
        current = self.sessions.get(session_id)
        if current:
            argv += ['resume', current['id'], user_text]
        else:
            argv += [user_text]
        return argv

    def _rollout(self, codex_id):
        root = Path(self.values.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'sessions'
        matches = list(root.rglob('*' + codex_id + '*.jsonl')) if root.exists() else []
        if not matches:
            raise RuntimeError('Codex rollout not found for exact session ' + codex_id)
        return max(matches, key=lambda p: p.stat().st_mtime_ns)

    async def export(self, session_id, rollout, turn_number):
        env = {
            **self.values,
            'TRACE_TO_LANGFUSE': 'true',
            'LANGFUSE_CODEX_MAX_HISTORY_CHARS': '0',
            'LANGFUSE_CODEX_USER_ID': 'lab3-local',
            'LANGFUSE_CODEX_FAIL_ON_ERROR': 'true',
            'LANGFUSE_CODEX_TRACE_SEED': session_id,
            'LANGFUSE_CODEX_ENVIRONMENT': 'lab3',
            'LANGFUSE_CODEX_TAGS': json.dumps(['lab3', 'codex', self.mode]),
        }
        process = await asyncio.create_subprocess_exec(
            self.node,
            str(self.plugin),
            env=env,
            cwd=self.work,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr, timed_out, cancelled = await _capture_owned(
            process,
            timeout=90,
            data=json.dumps(
                {
                    'transcript_path': str(rollout),
                    'session_id': self.sessions[session_id]['id'],
                    'hook_event_name': 'Stop',
                }
            ).encode(),
        )
        directory = self.directory / session_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f'{turn_number}.export.log').write_bytes(stdout + stderr)
        if cancelled:
            raise asyncio.CancelledError
        if timed_out:
            raise RuntimeError('Codex export timed out; original rollout and export log retained')
        if process.returncode:
            raise RuntimeError('Codex export failed: ' + stderr.decode(errors='replace')[-2000:])
        trace_id = sha256(f'{session_id}:{turn_number}'.encode()).hexdigest()[:32]
        return trace_id, stdout.decode(errors='replace'), stderr.decode(errors='replace')

    async def verify_trace(self, trace_id, final_text, tools):
        from langfuse import Langfuse

        client = Langfuse(
            public_key=self.values.get('LANGFUSE_PUBLIC_KEY'),
            secret_key=self.values.get('LANGFUSE_SECRET_KEY'),
            base_url=self.values.get('LANGFUSE_BASE_URL', 'http://127.0.0.1:3000'),
        )
        last = None
        for _ in range(30):
            try:

                def read_all_pages():
                    return [
                        row
                        for page in client.iter_observation_pages(
                            trace_id=trace_id,
                            fields='core,basic,io,usage,metadata,model',
                            from_start_time=datetime.now(UTC) - timedelta(days=1),
                            to_start_time=datetime.now(UTC) + timedelta(minutes=1),
                            limit=100,
                        )
                        for row in page.model_dump(mode='json')['data']
                    ]

                rows = await asyncio.to_thread(read_all_pages)
                validate_trace_observations(rows, final_text=final_text, expected_tools=tools)
                return rows
            except Exception as exc:
                last = exc
                await asyncio.sleep(1)
        raise RuntimeError('Mandatory Langfuse trace readback failed: ' + str(last))

    async def ainvoke(self, session_id, user_text, *, turn_id, on_event=None):
        before = perf_counter()
        directory = self.directory / session_id
        directory.mkdir(parents=True, exist_ok=True)
        current = self.sessions.get(session_id)
        number = (current['turns'] if current else 0) + 1
        wire_path = self.root / '.runtime/codex-wire' / session_id / 'wire.jsonl'
        wire_offset = wire_path.stat().st_size if wire_path.exists() else 0
        argv = self.command(session_id, user_text)
        (directory / f'{number}.argv.json').write_text(json.dumps(argv, indent=2))
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self.work,
            env={
                k: v
                for k, v in os.environ.items()
                if k not in ('CODEX_THREAD_ID', 'CODEX_SESSION_ID')
            },
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr, timed_out, cancelled = await _capture_owned(process, timeout=self.timeout)
        out, err = stdout.decode(errors='replace'), stderr.decode(errors='replace')
        (directory / f'{number}.stdout.jsonl').write_text(out)
        (directory / f'{number}.stderr.log').write_text(err)
        parsed = parse_events(out)
        sid = parsed['session_id'] or (current['id'] if current else None)
        self.last_records[session_id] = {'tools': parsed['tools'], 'events': parsed['events']}
        status = (
            'timeout'
            if timed_out
            else ('error' if process.returncode or parsed['error'] else 'completed')
        )
        error = (
            {'code': status, 'message': str(parsed['error'] or err[-2000:])}
            if status != 'completed'
            else None
        )
        trace_id = None
        if sid:
            self.sessions[session_id] = {'id': sid, 'turns': number}
            try:
                rollout = self._rollout(sid)
                shutil.copyfile(rollout, directory / 'rollout.jsonl')
                self.last_records[session_id]['rollout'] = str(directory / 'rollout.jsonl')
                if not cancelled:
                    trace_id, export_out, export_err = await self.export(
                        session_id, rollout, number
                    )
                    (directory / f'{number}.export.log').write_text(export_out + export_err)
                    observations = await self.verify_trace(
                        trace_id, parsed['text'], [t.get('tool', '') for t in parsed['tools']]
                    )
                    (directory / f'{number}.observations.json').write_text(
                        json.dumps(observations, indent=2)
                    )
            except Exception as exc:
                if status == 'completed':
                    status = 'incomplete'
                error = {'code': 'trace_export', 'message': str(exc)}
        wire = []
        if wire_path.exists():
            with wire_path.open('rb') as stream:
                stream.seek(wire_offset)
                for line in stream:
                    try:
                        wire.append(json.loads(line))
                    except ValueError:
                        pass
        self.last_records[session_id]['wire'] = wire
        if cancelled:
            raise asyncio.CancelledError
        usage = {
            **wire_usage(wire),
            'codex_cli_usage': parsed['usage'],
            'tool_calls': len(parsed['tools']),
            'api_cost': 0.0,
            'latency_ms': (perf_counter() - before) * 1000,
        }
        from dnd_rag.agent.citations import validate_citations

        citation_validation = validate_citations(parsed['text'], self.citations, session_id)
        # Internal Codex token_count is not identical to the own native counter.
        return AgentReply(
            text=parsed['text'],
            status=status,
            context=ContextStats(
                input_tokens=next(
                    (r['input_tokens'] for r in reversed(wire) if r.get('kind') == 'request'), None
                ),
                agent_limit=self.context_limit,
            ),
            trace_id=trace_id,
            usage=usage,
            error=error,
            sources=citation_validation.sources,
            citation_validation=citation_validation.model_dump(mode='json'),
        )

    async def close_session(self, session_id):
        # Each turn already exports the closed rollout; preserve exact ID for audit/resume.
        return self.sessions.get(session_id)

    async def aclose(self):
        pass
