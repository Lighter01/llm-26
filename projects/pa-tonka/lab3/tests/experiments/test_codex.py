import json
from pathlib import Path


def test_codex_argv_isolated_exact_resume_and_no_gold(tmp_path):
    from dnd_rag.experiments.codex import CodexRunner

    root = Path(__file__).resolve().parents[2]
    runner = CodexRunner(root, mode='off', artifacts_dir=tmp_path)
    first = runner.command('session-a', 'Find a rule')
    assert '--ignore-user-config' in first and '--json' in first
    assert '--skip-git-repo-check' in first and '--strict-config' in first
    assert 'resume' not in first and '--last' not in first
    runner.sessions['session-a'] = {'id': 'specific-session', 'turns': 1}
    second = runner.command('session-a', 'Remember it')
    assert 'resume' in second and 'specific-session' in second and '--last' not in second
    assert all('expected_output' not in a and 'gold' not in a for a in second)
    assert not any('none' == a for a in runner.command('b', 'Ready', mode='budgeted'))


def test_codex_events_missing_usage_stays_unknown_and_last_reply_is_kept(tmp_path):
    from dnd_rag.experiments.codex import parse_events

    rows = [
        {'type': 'thread.started', 'thread_id': 'sid'},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'final answer'}},
    ]
    result = parse_events('\n'.join(json.dumps(r) for r in rows))
    assert result['text'] == 'final answer' and result['session_id'] == 'sid'
    assert result['usage'] is None
    rows.append(
        {
            'type': 'turn.completed',
            'usage': {'input_tokens': 20, 'output_tokens': 5, 'cached_input_tokens': 3},
        }
    )
    assert parse_events('\n'.join(json.dumps(r) for r in rows))['usage']['input_tokens'] == 20


def test_missing_final_generation_or_usage_is_not_trace_success():
    import pytest

    from dnd_rag.experiments.codex import validate_trace_observations

    rows = [
        {
            'type': 'GENERATION',
            'output': 'final text',
            'input': 'full prompt',
            'usageDetails': {'input': 10, 'output': 2},
        },
        {'type': 'TOOL', 'name': 'mcp__dnd__search_rules', 'output': {'hits': []}},
    ]
    validate_trace_observations(rows, final_text='final text', expected_tools=['search_rules'])
    with pytest.raises(ValueError):
        validate_trace_observations([], final_text='final text', expected_tools=[])
    with pytest.raises(ValueError):
        validate_trace_observations(
            [{**rows[0], 'usageDetails': {}}], final_text='final text', expected_tools=[]
        )
    with pytest.raises(ValueError):
        validate_trace_observations(rows, final_text='lost final reply', expected_tools=[])
    with pytest.raises(ValueError):
        validate_trace_observations(
            rows, final_text='final text', expected_tools=['lookup_monsters']
        )


def test_rollout_discovery_respects_existing_codex_storage_root(tmp_path):
    from dnd_rag.experiments.codex import CodexRunner

    root = Path(__file__).resolve().parents[2]
    runner = CodexRunner(root, artifacts_dir=tmp_path / 'artifacts')
    store = tmp_path / 'codex-store'
    (store / 'sessions/2026/11/13').mkdir(parents=True)
    expected = store / 'sessions/2026/11/13/rollout-known-session.jsonl'
    expected.write_text('{}\n')
    runner.values['CODEX_HOME'] = str(store)
    assert runner._rollout('known-session') == expected


def test_cancel_stops_owned_codex_process_and_propagates(tmp_path, monkeypatch):
    import asyncio
    import os
    import sys

    import pytest

    from dnd_rag.experiments.codex import CodexRunner

    runner = CodexRunner(Path(__file__).resolve().parents[2], artifacts_dir=tmp_path / 'artifacts')
    pid_file = tmp_path / 'pid'
    code = (
        'import os,time;from pathlib import Path;'
        + 'print('
        + repr(json.dumps({'type': 'thread.started', 'thread_id': 'cancel-native'}))
        + ',flush=True);Path('
        + repr(str(pid_file))
        + ').write_text(str(os.getpid()));time.sleep(30)'
    )
    original = tmp_path / 'closed-rollout.jsonl'
    original.write_text('{"native": "original transcript"}\n')
    monkeypatch.setattr(runner, '_rollout', lambda sid: original)
    monkeypatch.setattr(runner, 'command', lambda *a, **k: [sys.executable, '-c', code])

    async def run():
        task = asyncio.create_task(runner.ainvoke('cancel', 'Hello', turn_id='one'))
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
        assert runner.sessions['cancel']['id'] == 'cancel-native'
        assert (tmp_path / 'artifacts/cancel/rollout.jsonl').read_bytes() == original.read_bytes()

    asyncio.run(run())


def test_trace_validation_reads_complete_json_encoded_output():
    from dnd_rag.experiments.codex import validate_trace_observations

    rows = [
        {
            'type': 'GENERATION',
            'input': 'prompt',
            'output': 'final',
            'usageDetails': {'input': 1, 'output': 1},
        },
        {'type': 'AGENT', 'output': json.dumps({'text': 'Full\nfinal reply.'})},
    ]
    validate_trace_observations(rows, final_text='Full\nfinal reply.', expected_tools=[])


def test_trace_readback_follows_sdk_pages_without_truncating_first_generations(
    tmp_path, monkeypatch
):
    import asyncio
    from types import SimpleNamespace as NS

    import langfuse

    from dnd_rag.experiments.codex import CodexRunner

    first = [
        {
            'type': 'GENERATION',
            'input': 'prompt',
            'output': 'earlier',
            'usageDetails': {'input': 1, 'output': 1},
        }
        for _ in range(100)
    ]
    last = {
        'type': 'GENERATION',
        'input': 'last prompt',
        'output': 'last reply',
        'usageDetails': {'input': 2, 'output': 3},
    }

    def page(rows, cursor=None):
        return NS(model_dump=lambda **k: {'data': rows, 'meta': {'cursor': cursor}})

    sdk = NS(
        api=NS(observations=NS(get_many=lambda **k: page(first, 'page2'))),
        iter_observation_pages=lambda **k: iter([page(first, 'page2'), page([last])]),
    )
    monkeypatch.setattr(langfuse, 'Langfuse', lambda **k: sdk)

    async def no_sleep(*args):
        pass

    monkeypatch.setattr(asyncio, 'sleep', no_sleep)
    runner = CodexRunner(Path(__file__).resolve().parents[2], artifacts_dir=tmp_path)
    rows = asyncio.run(runner.verify_trace('trace', 'last reply', []))
    assert len(rows) == 101 and rows[-1]['output'] == 'last reply'


def test_adapter_construction_does_not_claim_runner_run_directory(tmp_path):
    from dnd_rag.experiments.codex import CodexRunner

    runner = CodexRunner(
        Path(__file__).resolve().parents[2], artifacts_dir=tmp_path / 'run' / 'raw' / 'codex'
    )
    assert not (tmp_path / 'run').exists()
    assert runner.directory == tmp_path / 'run' / 'raw' / 'codex'


def test_native_wire_usage_includes_compaction_and_missing_response_is_unknown():
    from dnd_rag.experiments.codex import wire_usage

    rows = [
        {'kind': 'request', 'id': 'a', 'input_tokens': 100},
        {
            'kind': 'response',
            'id': 'a',
            'response': {'usage': {'input_tokens': 100, 'output_tokens': 12}},
        },
        {'kind': 'request', 'id': 'summary', 'input_tokens': 200},
        {
            'kind': 'response',
            'id': 'summary',
            'response': {'usage': {'input_tokens': 200, 'output_tokens': 30}},
        },
    ]
    assert wire_usage(rows)['input_tokens'] == 300 and wire_usage(rows)['output_tokens'] == 42
    assert wire_usage(rows[:-1])['output_tokens'] is None


def _capture_runner(tmp_path, monkeypatch, rows, *, timeout=2):
    import sys

    from dnd_rag.experiments.codex import CodexRunner

    runner = CodexRunner(tmp_path, artifacts_dir=tmp_path / 'results', timeout_seconds=timeout)
    code = 'import time;' + ''.join(
        'print(' + repr(json.dumps(row)) + ',flush=True);' for row in rows
    )
    if timeout < 1:
        code += 'time.sleep(3)'
    monkeypatch.setattr(runner, 'command', lambda *a, **kw: [sys.executable, '-c', code])
    source = tmp_path / 'original-rollout.jsonl'
    source.write_text('{"original":"closed native rollout"}\n')
    monkeypatch.setattr(runner, '_rollout', lambda sid: source)

    async def export(*args):
        return 'f' * 32, 'real export stdout', ''

    async def verify(*args):
        return []

    monkeypatch.setattr(runner, 'export', export)
    monkeypatch.setattr(runner, 'verify_trace', verify)
    return runner, source


def test_timeout_keeps_flushed_tools_and_exact_native_session(tmp_path, monkeypatch):
    import asyncio

    rows = [
        {'type': 'thread.started', 'thread_id': 'native'},
        {
            'type': 'item.completed',
            'item': {
                'type': 'mcp_tool_call',
                'tool': 'lookup_monsters',
                'arguments': {'query': 'Troll'},
                'result': {'status': 'matched', 'monsters': []},
                'status': 'completed',
            },
        },
    ]
    runner, source = _capture_runner(tmp_path, monkeypatch, rows, timeout=0.2)
    reply = asyncio.run(runner.ainvoke('scope', 'Question', turn_id='turn'))
    assert reply.status == 'timeout'
    assert len(runner.last_records['scope']['tools']) == 1
    assert runner.sessions['scope']['id'] == 'native'


def test_original_rollout_is_archived_even_when_trace_readback_fails(tmp_path, monkeypatch):
    import asyncio

    runner, source = _capture_runner(
        tmp_path,
        monkeypatch,
        [
            {'type': 'thread.started', 'thread_id': 'native'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'answer'}},
        ],
    )

    async def fail(*args):
        raise RuntimeError('readback unavailable')

    monkeypatch.setattr(runner, 'verify_trace', fail)
    reply = asyncio.run(runner.ainvoke('scope', 'Question', turn_id='turn'))
    assert reply.status == 'incomplete'
    archived = tmp_path / 'results/scope/rollout.jsonl'
    assert archived.read_bytes() == source.read_bytes()
    assert runner.last_records['scope']['rollout'] == str(archived)


def _export_runner(tmp_path, source):
    import sys

    from dnd_rag.experiments.codex import CodexRunner

    runner = CodexRunner(tmp_path, artifacts_dir=tmp_path / 'results')
    runner.node = sys.executable
    runner.plugin = tmp_path / 'exporter.py'
    runner.plugin.write_text(source)
    runner.sessions['scope'] = {'id': 'native', 'turns': 1}
    return runner


def test_failed_export_keeps_complete_stdout_and_stderr(tmp_path):
    import asyncio

    import pytest

    runner = _export_runner(
        tmp_path,
        "import sys;sys.stdin.read();print('export stdout');print('x'*5000,file=sys.stderr);sys.exit(1)",
    )
    with pytest.raises(RuntimeError, match='export failed'):
        asyncio.run(runner.export('scope', tmp_path / 'rollout.jsonl', 1))
    log = (tmp_path / 'results/scope/1.export.log').read_text()
    assert 'export stdout' in log and 'x' * 5000 in log


def test_cancelling_export_stops_its_owned_child_and_keeps_log(tmp_path):
    import asyncio
    import os
    import signal

    import pytest

    pid_file = tmp_path / 'export-pid'
    runner = _export_runner(
        tmp_path,
        'import os,time;from pathlib import Path;Path('
        + repr(str(pid_file))
        + ").write_text(str(os.getpid()));print('before cancel',flush=True);time.sleep(30)",
    )

    async def run():
        task = asyncio.create_task(runner.export('scope', tmp_path / 'rollout.jsonl', 1))
        for _ in range(200):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        pid = int(pid_file.read_text())
        try:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        assert 'before cancel' in (tmp_path / 'results/scope/1.export.log').read_text()

    asyncio.run(run())
