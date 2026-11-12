import json
from types import SimpleNamespace

from dnd_rag.agent.config import AgentConfig
from dnd_rag.experiments.commands import experiment_provenance


def test_tool_descriptions_and_catalog_exporter_change_the_frozen_fingerprint(tmp_path):
    instance = tmp_path / '.runtime/llama/instance.json'
    instance.parent.mkdir(parents=True)
    instance.write_text('{}')
    descriptions = tmp_path / 'src/dnd_rag/tools/descriptions.yaml'
    descriptions.parent.mkdir(parents=True)
    descriptions.write_text('search_rules: first description')
    exporter = tmp_path / 'src/dnd_rag/game/export.mjs'
    exporter.parent.mkdir(parents=True)
    exporter.write_text('export const version = 1;')
    app = SimpleNamespace(
        retriever=SimpleNamespace(index=SimpleNamespace(index_id='index', build_id='build')),
        catalog=SimpleNamespace(manifest={}),
        profile=AgentConfig(),
    )
    dataset = SimpleNamespace(fingerprint='dataset', items=[])

    def freeze():
        return experiment_provenance(tmp_path, app, dataset, AgentConfig())

    first = freeze()
    descriptions.write_text('search_rules: revised description')
    second = freeze()
    assert first['common_fingerprint'] != second['common_fingerprint']
    exporter.write_text('export const version = 2;')
    assert second['common_fingerprint'] != freeze()['common_fingerprint']


def test_shared_default_leaves_room_for_large_native_tool_results():
    from dnd_rag.__main__ import PROJECT_ROOT, parser
    from dnd_rag.agent.contracts import ContextStats
    from dnd_rag.experiments.codex import CodexRunner

    # Measured regression: at 11K Codex sent 14,686 input tokens after a search,
    # exceeding the 16,384 window with its 2,048-token output reserve.
    assert AgentConfig().context_limit == ContextStats().agent_limit == 9500
    assert parser().parse_args(['run']).context_limit == 9500
    assert (
        parser().parse_args(['evaluate-agents', '--agent', 'codex', '--mode', 'off']).context_limit
        == 9500
    )
    assert CodexRunner(PROJECT_ROOT).context_limit == 9500
    catalog = json.loads((PROJECT_ROOT / 'configs/baseline/models.json').read_text())
    assert catalog['models'][0]['auto_compact_token_limit'] == 9500
