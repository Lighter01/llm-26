import asyncio
from types import SimpleNamespace as NS

from dnd_rag.contracts import RetrievalResult
from tests.rag.fixtures import make_hits


def test_transport_header_controls_numbering_without_model_argument(tmp_path, monkeypatch):
    from dnd_rag.agent.citations import CitationRegistry
    from dnd_rag.tools.server import ToolServices, create_mcp_server

    registry = CitationRegistry(tmp_path)

    def retrieve(q, limit=None):
        return RetrievalResult(
            question=q,
            index_id='a' * 64,
            build_id='one',
            mode='dense',
            hits=make_hits(2),
            timings_ms={},
        )

    mcp = create_mcp_server(ToolServices(NS(retrieve=retrieve), citations=registry))
    scope = ['first']
    monkeypatch.setattr(
        mcp,
        'get_context',
        lambda: NS(request_context=NS(request=NS(headers={'x-dnd-session-id': scope[0]}))),
    )

    async def run():
        tools = await mcp.list_tools()
        assert 'scope_id' not in tools[0].inputSchema.get('properties', {})
        first = (await mcp.call_tool('search_rules', {'query': 'rule'}))[1]
        second = (await mcp.call_tool('search_rules', {'query': 'other'}))[1]
        assert [c['number'] for c in first['citations']] == [1, 2]
        assert first['citations'] == second['citations']
        scope[0] = 'second'
        assert (await mcp.call_tool('search_rules', {'query': 'new'}))[1]['citations'][0][
            'number'
        ] == 1
        assert len(registry.export('first')) == 2

    asyncio.run(run())


def test_real_streamable_http_preserves_header_scope(tmp_path):
    import socket

    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from dnd_rag.agent.citations import CitationRegistry
    from dnd_rag.runtime.application import background_server
    from dnd_rag.tools.server import ToolServices, create_mcp_server

    registry = CitationRegistry(tmp_path)
    all_hits = make_hits(2)

    def retrieve(q, limit=None):
        return RetrievalResult(
            question=q,
            index_id='a' * 64,
            build_id='one',
            mode='dense',
            hits=all_hits if q == 'both' else all_hits[1:] if q == 'second' else all_hits[:1],
            timings_ms={},
        )

    mcp = create_mcp_server(ToolServices(NS(retrieve=retrieve), citations=registry))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]

    async def call(scope, query):
        async with httpx.AsyncClient(headers={'X-DND-Session-Id': scope}) as client:
            async with streamable_http_client(
                f'http://127.0.0.1:{port}/mcp', http_client=client
            ) as (read, write, *_):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return (
                        await session.call_tool('search_rules', {'query': query})
                    ).structuredContent

    async def run():
        assert (await call('real-a', 'first'))['citations'][0]['number'] == 1
        assert [c['number'] for c in (await call('real-a', 'both'))['citations']] == [1, 2]
        assert (await call('real-b', 'second'))['citations'][0]['number'] == 1
        assert registry.resolve('real-b', 1).source_id == registry.resolve('real-a', 2).source_id
        assert registry.resolve('real-b', 2) is None

    with background_server(mcp.streamable_http_app(), port=port):
        asyncio.run(run())
