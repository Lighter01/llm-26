"""One loopback Streamable HTTP MCP server, shared by both agents."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from dnd_rag.config import read_yaml
from dnd_rag.contracts import RagError


@dataclass
class ToolServices:
    retriever: object
    catalog: object | None = None
    citations: object | None = None


def create_mcp_server(services, descriptions=None, *, host='127.0.0.1', port=8765):
    descriptions = descriptions or read_yaml(Path(__file__).with_name('descriptions.yaml'))
    from dnd_rag.agent.citations import CitationRegistry

    registry = services.citations or CitationRegistry(
        Path(__file__).resolve().parents[3] / '.runtime/citations'
    )
    mcp = FastMCP('D&D DM tools', host=host, port=port, stateless_http=True, json_response=True)

    @mcp.tool(
        description=descriptions['search_rules'],
        structured_output=True,
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    def search_rules(
        query: Annotated[str, Field(min_length=1)], limit: Annotated[int, Field(ge=1, le=10)] = 5
    ) -> dict[str, Any]:
        try:
            result = services.retriever.retrieve(query, limit=limit)
            data = result.model_dump(mode='json')
            try:
                request = mcp.get_context().request_context.request
                scope = request.headers.get('x-dnd-session-id') if request else None
            except (ValueError, AttributeError):
                scope = None
            if scope:
                refs = registry.register(scope, result.hits)
                # Source text is already in hits: do not duplicate it in the model payload.
                data['citations'] = [
                    {
                        'number': ref.number,
                        'source_id': ref.source_id,
                        'chunk_id': ref.source.provenance['chunk_id'],
                    }
                    for ref in refs
                ]
            else:
                data['citations'] = []
                data['citation_status'] = 'missing_transport_scope'
            return data
        except RagError as exc:
            return {'error': exc.as_dict()}

    if services.catalog is not None:
        from typing import Literal

        from dnd_rag.game.contracts import MonsterCount
        from dnd_rag.game.encounters import build_encounter as build
        from dnd_rag.game.encounters import evaluate_encounter as evaluate
        from dnd_rag.game.loot import generate_loot as loot

        def guarded(function, **kwargs):
            try:
                return function(services.catalog, **kwargs).model_dump(mode='json')
            except RagError as exc:
                return {'error': exc.as_dict()}

        annotation = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

        @mcp.tool(
            description=descriptions['lookup_monsters'],
            structured_output=True,
            annotations=annotation,
        )
        def lookup_monsters(
            query: str | None = None,
            habitat: str | None = None,
            creature_type: str | None = None,
            limit: Annotated[int, Field(ge=1, le=10)] = 5,
        ) -> dict[str, Any]:
            found = services.catalog.lookup_monsters(
                query, habitat=habitat, creature_type=creature_type, limit=limit
            )
            cards = []
            fields = {
                'size',
                'type',
                'alignment',
                'ac',
                'hp',
                'speed',
                'str',
                'dex',
                'con',
                'int',
                'wis',
                'cha',
                'save',
                'skill',
                'senses',
                'passive',
                'resist',
                'immune',
                'vulnerable',
                'conditionImmune',
                'languages',
                'trait',
                'spellcasting',
                'action',
                'bonus',
                'reaction',
                'legendary',
                'legendary_group',
            }
            for monster in found:
                card = monster.model_dump(mode='json')
                card['stat_block'] = {k: v for k, v in monster.stat_block.items() if k in fields}
                cards.append(card)
            exact = any(
                m.monster_id == query or m.name.casefold() == str(query).casefold() for m in found
            )
            return {
                'status': 'not_found'
                if not found
                else 'ambiguous'
                if query and len(found) > 1 and not exact
                else 'matched',
                'monsters': cards,
                'limit': limit,
            }

        @mcp.tool(
            description=descriptions['evaluate_encounter'],
            structured_output=True,
            annotations=annotation,
        )
        def evaluate_encounter(
            party_size: Annotated[int, Field(ge=1)],
            party_level: Annotated[int, Field(ge=1, le=20)],
            monsters: Annotated[list[MonsterCount], Field(min_length=1)],
        ) -> dict[str, Any]:
            return guarded(
                evaluate, party_size=party_size, party_level=party_level, monsters=monsters
            )

        @mcp.tool(
            description=descriptions['build_encounter'],
            structured_output=True,
            annotations=annotation,
        )
        def build_encounter(
            party_size: Annotated[int, Field(ge=1)],
            party_level: Annotated[int, Field(ge=1, le=20)],
            difficulty: Literal['low', 'moderate', 'high'],
            habitat: str | None = None,
            creature_type: str | None = None,
            total_count: Annotated[int | None, Field(ge=1)] = None,
            required_monsters: list[MonsterCount] | None = None,
        ) -> dict[str, Any]:
            return guarded(
                build,
                party_size=party_size,
                party_level=party_level,
                difficulty=difficulty,
                habitat=habitat,
                creature_type=creature_type,
                total_count=total_count,
                required_monsters=required_monsters or [],
            )

        @mcp.tool(
            description=descriptions['generate_loot'],
            structured_output=True,
            annotations=ToolAnnotations(
                readOnlyHint=True, idempotentHint=False, destructiveHint=False, openWorldHint=False
            ),
        )
        def generate_loot(
            kind: Literal['individual', 'hoard'],
            cr: float | str,
            count: Annotated[int, Field(ge=1)] = 1,
            party_level: Annotated[int | None, Field(ge=1, le=20)] = None,
            treasure_theme: Literal['Arcana', 'Armaments', 'Implements', 'Relics'] | None = None,
        ) -> dict[str, Any]:
            return guarded(
                loot,
                kind=kind,
                cr=cr,
                count=count,
                party_level=party_level,
                treasure_theme=treasure_theme,
            )

    return mcp


def run_mcp_server(*, host='127.0.0.1', port=8765):
    from dnd_rag.config import load_rag_config, load_settings
    from dnd_rag.runtime.index import prepare_retriever
    from dnd_rag.runtime.processes import RuntimeSession

    root = Path(__file__).resolve().parents[3]
    settings = load_settings(root)
    with RuntimeSession(root) as session:
        retriever = prepare_retriever(load_rag_config(None, project_root=root), settings, session)
        from dnd_rag.game.prepare import ensure_game_catalog

        catalog = ensure_game_catalog(root)
        create_mcp_server(ToolServices(retriever, catalog), host=host, port=port).run(
            transport='streamable-http'
        )


if __name__ == '__main__':
    run_mcp_server()
