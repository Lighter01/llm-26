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
        'import os,time;from pathlib import Path;Path('
        + repr(str(pid_file))
        + ').write_text(str(os.getpid()));time.sleep(30)'
    )
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
