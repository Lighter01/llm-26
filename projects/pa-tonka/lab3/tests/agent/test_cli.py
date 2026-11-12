import asyncio
from io import StringIO

from rich.console import Console

from dnd_rag.agent.contracts import AgentEvent, AgentReply, ContextStats


class ScriptedPrompt:
    def __init__(self, lines):
        self.lines = iter(lines)

    async def prompt_async(self, *args, **kwargs):
        value = next(self.lines, EOFError())
        if isinstance(value, BaseException):
            raise value
        return value


class Adapter:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, sid, text, **kwargs):
        self.calls.append((sid, text))
        kwargs['on_event'](
            AgentEvent(kind='compaction_completed', payload={'before': 11200, 'after': 3400})
        )
        kwargs['on_event'](AgentEvent(kind='tool_error', payload={'name': 'lookup_monsters'}))
        return AgentReply(
            text='Answer',
            status='completed',
            trace_id='abc',
            context=ContextStats(input_tokens=4200, agent_limit=11000),
        )


def test_terminal_sessions_context_and_events_are_actual(tmp_path):
    from dnd_rag.cli import run_cli

    adapter = Adapter()
    output = StringIO()
    asyncio.run(
        run_cli(
            adapter,
            prompt=ScriptedPrompt(['Hello', '/status', '/new', 'Again', '/exit']),
            console=Console(file=output, color_system=None, width=140),
            model='local',
            trace_url=lambda t: 'http://local/' + t,
            history_path=tmp_path / 'history',
        )
    )
    assert len(adapter.calls) == 2 and adapter.calls[0][0] != adapter.calls[1][0]
    text = output.getvalue()
    for value in [
        '4200/11000',
        '38%',
        '16384',
        '11200',
        '3400',
        'lookup_monsters',
        'http://local/abc',
    ]:
        assert value in text


def test_eof_and_ctrl_c_exit_without_invoking_model(tmp_path):
    from dnd_rag.cli import run_cli

    for stop in [EOFError(), KeyboardInterrupt()]:
        adapter = Adapter()
        assert (
            asyncio.run(
                run_cli(
                    adapter,
                    prompt=ScriptedPrompt([stop]),
                    console=Console(file=StringIO()),
                    history_path=tmp_path / 'history',
                )
            )
            == 0
        )
        assert not adapter.calls


def test_real_pty_preserves_rich_ansi_without_escaped_question_marks(tmp_path):
    import os
    import pty
    import select
    import subprocess
    import sys
    import time

    master, slave = pty.openpty()
    code = """
import asyncio,sys
from pathlib import Path
from rich.console import Console
from dnd_rag.cli import run_cli
from tests.agent.test_cli import Adapter
asyncio.run(run_cli(Adapter(),console=Console(force_terminal=True),history_path=Path(sys.argv[1])))
"""
    process = subprocess.Popen(
        [sys.executable, '-c', code, str(tmp_path / 'history')],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**os.environ, 'TERM': 'xterm-256color', 'PROMPT_TOOLKIT_NO_CPR': '1'},
    )
    os.close(slave)
    output = bytearray()

    def read_until(marker):
        deadline = time.monotonic() + 15
        while marker not in output:
            assert time.monotonic() < deadline, bytes(output)
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break

    try:
        read_until(b'You')
        os.write(master, b'Hello\r')
        read_until(b'completed')
        os.write(master, b'/exit\r')
        process.wait(timeout=10)
        assert b'?[2m' not in output and b'?[1m' not in output, bytes(output)
        assert b'\x1b[' in output and b'Context summary' in output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
