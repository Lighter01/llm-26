"""Rich terminal for the shared agent service; no retrieval/model lifecycle here."""

import uuid
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from dnd_rag.agent.contracts import ContextStats

COMMANDS = ['/help', '/new', '/status', '/exit']


def context_label(stats):
    count = stats.input_tokens
    return (
        f'Context {count}/{stats.agent_limit} ({100 * count / stats.agent_limit:.0f}%) · server {stats.server_window}'
        if count is not None
        else f'Context unknown/{stats.agent_limit} · server {stats.server_window}'
    )


async def run_cli(
    service,
    *,
    prompt=None,
    console=None,
    model='local',
    trace_url=lambda _: None,
    history_path=Path('.runtime/cli.history'),
):
    console = console or Console()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = prompt or PromptSession(
        history=FileHistory(str(history_path)), completer=WordCompleter(COMMANDS)
    )
    sid, last_trace, stats = (
        str(uuid.uuid4()),
        None,
        ContextStats(agent_limit=getattr(getattr(service, 'config', None), 'context_limit', 9500)),
    )
    console.print(
        Panel(
            f'[bold]D&D Dungeon Master Assistant[/bold]\n{model}\n/help · /new · /status · /exit',
            border_style='cyan',
        )
    )

    def event(e):
        if e.kind == 'context_measured':
            nonlocal stats
            stats = ContextStats.model_validate(e.payload)
        elif e.kind == 'compaction_started':
            console.print('[yellow]Summarizing earlier conversation…[/yellow]')
        elif e.kind == 'compaction_completed':
            console.print(
                f'[yellow]Context summary: {e.payload["before"]} → {e.payload["after"]} tokens[/yellow]'
            )
        elif e.kind in ('tool_started', 'tool_completed', 'tool_error'):
            console.print(f'[dim]{e.kind}: {e.payload.get("name", "")}[/dim]')
        elif e.kind == 'citation_warning':
            console.print(
                f'Unknown source numbers: {e.payload.get("unknown_numbers")}', style='yellow'
            )
        elif e.kind == 'error':
            console.print(f'[red]{e.payload.get("code")}: {e.payload.get("message")}[/red]')

    with patch_stdout(raw=True):
        while True:
            try:
                text = (await prompt.prompt_async('You › ')).strip()
            except (EOFError, KeyboardInterrupt):
                console.print('Session closed.')
                return 0
            if not text:
                continue
            if text == '/exit':
                return 0
            if text == '/help':
                console.print(
                    '/new starts an isolated dialog; /status shows the last measured input and trace; /exit closes owned processes.'
                )
                continue
            if text == '/new':
                sid, last_trace, stats = (
                    str(uuid.uuid4()),
                    None,
                    ContextStats(
                        agent_limit=getattr(getattr(service, 'config', None), 'context_limit', 9500)
                    ),
                )
                console.print(f'New dialog: {sid}')
                continue
            if text == '/status':
                console.print(
                    f'Model: {model}\nSession: {sid}\n{context_label(stats)}\nTrace: {trace_url(last_trace) or last_trace or "none"}'
                )
                continue
            if text.startswith('/'):
                console.print('[yellow]Unknown command; use /help.[/yellow]')
                continue
            try:
                reply = await service.ainvoke(sid, text, turn_id=str(uuid.uuid4()), on_event=event)
            except KeyboardInterrupt:
                console.print('Session interrupted.')
                return 0
            stats, last_trace = reply.context, reply.trace_id
            console.print(
                Panel(
                    Markdown(reply.text or (reply.error or {}).get('message', reply.status)),
                    title='DM Assistant',
                    border_style='cyan' if reply.status == 'completed' else 'red',
                )
            )
            for number, source in zip(
                (reply.citation_validation or {}).get('valid_numbers', []), reply.sources
            ):
                source = source.model_dump(mode='json') if hasattr(source, 'model_dump') else source
                sections = source['provenance'].get('sections', [])
                section = ' / '.join(sections[0].get('heading_path', [])) if sections else ''
                console.print(
                    f'[{number}] {source["book_id"]} · {source["source_file"]} · {section}',
                    markup=False,
                    style='dim',
                )
            console.print(f'[dim]{context_label(stats)} · {reply.status}[/dim]')
