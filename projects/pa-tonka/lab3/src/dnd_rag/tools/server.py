"""One loopback Streamable HTTP MCP server, shared by both agents."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from dnd_rag.config import read_yaml
from dnd_rag.contracts import RagError


@dataclass
class ToolServices:
    retriever: object


def create_mcp_server(services, descriptions=None, *, host='127.0.0.1', port=8765):
    descriptions = descriptions or read_yaml(Path(__file__).with_name('descriptions.yaml'))
    mcp = FastMCP('D&D DM tools', host=host, port=port, stateless_http=True, json_response=True)

    @mcp.tool(description=descriptions['search_rules'], structured_output=True)
    def search_rules(
        query: Annotated[str, Field(min_length=1)], limit: Annotated[int, Field(ge=1, le=10)] = 5
    ) -> dict[str, Any]:
        try:
            return services.retriever.retrieve(query, limit=limit).model_dump(mode='json')
        except RagError as exc:
            return {'error': exc.as_dict()}

    return mcp


def run_mcp_server(*, host='127.0.0.1', port=8765):
    from dnd_rag.config import load_rag_config, load_settings
    from dnd_rag.runtime.index import prepare_retriever
    from dnd_rag.runtime.processes import RuntimeSession

    root = Path(__file__).resolve().parents[3]
    settings = load_settings(root)
    with RuntimeSession(root) as session:
        retriever = prepare_retriever(load_rag_config(None, project_root=root), settings, session)
        create_mcp_server(ToolServices(retriever), host=host, port=port).run(
            transport='streamable-http'
        )


if __name__ == '__main__':
    run_mcp_server()
