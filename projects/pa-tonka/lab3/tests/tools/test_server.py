import asyncio
from types import SimpleNamespace as NS

import pytest

from dnd_rag.contracts import RetrievalResult
from tests.rag.fixtures import make_hits


def test_search_contract_and_validation_before_encoder():
    import dnd_rag.tools.server as server

    calls = []

    def retrieve(question, limit=None):
        calls.append(limit)
        return RetrievalResult(
            question=question,
            index_id='a' * 64,
            build_id='build1',
            mode='dense',
            hits=make_hits(1),
            timings_ms={'search': 1.0},
        )

    mcp = server.create_mcp_server(server.ToolServices(NS(retrieve=retrieve)))

    async def check():
        tools = await mcp.list_tools()
        assert [t.name for t in tools] == ['search_rules']
        result = await mcp.call_tool('search_rules', {'query': 'Armor Class'})
        payload = result[1]
        assert payload['hits'][0]['chunk']['page_content'].startswith('Passage 1:')
        assert payload['hits'][0]['chunk']['metadata']['body_sha256'] == 'b' * 64
        assert payload['index_id'] == 'a' * 64 and payload['build_id'] == 'build1'
        for limit in [1, 10]:
            await mcp.call_tool('search_rules', {'query': 'rule', 'limit': limit})
        for limit in [0, 11]:
            with pytest.raises(Exception):
                await mcp.call_tool('search_rules', {'query': 'rule', 'limit': limit})

    asyncio.run(check())
    assert calls == [5, 1, 10]


def test_empty_hits_and_retrieval_failure_differ():
    import dnd_rag.tools.server as server
    from dnd_rag.contracts import RagError

    def retrieve(question, limit=None):
        if question == 'broken':
            raise RagError('qdrant_timeout', 'timed out')
        return RetrievalResult(
            question=question, index_id='a' * 64, build_id='b', mode='dense', hits=[], timings_ms={}
        )

    mcp = server.create_mcp_server(server.ToolServices(NS(retrieve=retrieve)))

    async def check():
        empty = (await mcp.call_tool('search_rules', {'query': 'empty'}))[1]
        assert empty['hits'] == [] and 'error' not in empty
        broken = (await mcp.call_tool('search_rules', {'query': 'broken'}))[1]
        assert broken['error']['code'] == 'qdrant_timeout'

    asyncio.run(check())


def test_five_real_tools_share_catalog_and_return_structured_conflicts():
    import dnd_rag.tools.server as server
    from tests.game.fixtures import catalog

    mcp = server.create_mcp_server(
        server.ToolServices(NS(retrieve=lambda *a, **k: None), catalog=catalog())
    )

    async def check():
        tools = await mcp.list_tools()
        assert {t.name for t in tools} == {
            'search_rules',
            'lookup_monsters',
            'evaluate_encounter',
            'build_encounter',
            'generate_loot',
        }
        monsters = (await mcp.call_tool('lookup_monsters', {'query': 'Mage'}))[1]
        assert monsters['monsters'][0]['xp'] == 2300
        result = (
            await mcp.call_tool(
                'evaluate_encounter',
                {
                    'party_size': 4,
                    'party_level': 6,
                    'monsters': [{'monster_id': 'mage', 'count': 2}],
                },
            )
        )[1]
        assert result['total_xp'] == 4600 and result['difficulty'] == 'high'
        conflict = (
            await mcp.call_tool(
                'build_encounter',
                {
                    'party_size': 4,
                    'party_level': 1,
                    'difficulty': 'low',
                    'required_monsters': [{'monster_id': 'mage', 'count': 1}],
                },
            )
        )[1]
        assert conflict['status'] == 'conflict'
        unknown = (
            await mcp.call_tool(
                'evaluate_encounter',
                {
                    'party_size': 4,
                    'party_level': 6,
                    'monsters': [{'monster_id': 'No Such Monster', 'count': 1}],
                },
            )
        )[1]
        assert unknown['error']['code'] == 'unknown_monster'
        loot = (await mcp.call_tool('generate_loot', {'kind': 'individual', 'cr': 1, 'count': 2}))[
            1
        ]
        assert 6 <= loot['coins']['gp'] <= 36 and loot['count'] == 2

    asyncio.run(check())
