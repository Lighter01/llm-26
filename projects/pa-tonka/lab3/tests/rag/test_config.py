import subprocess
import sys

import pytest

from dnd_rag.config import load_llm_profile, load_rag_config, load_settings
from dnd_rag.contracts import RagError
from tests.rag.fixtures import baseline_data, write_yaml


@pytest.mark.parametrize(
    'section,values',
    [
        ('chunking', {'chunk_size': 99}),
        ('chunking', {'chunk_size': 1001}),
        ('chunking', {'chunk_overlap': 512}),
        ('chunking', {'max_heading_level': 7}),
        ('embedding', {'document_dtype': 'float16'}),
        ('embedding', {'dimension': 42}),
        ('retrieval', {'mode': 'hybrid', 'hybrid_candidates_per_branch': 9}),
        ('bm25', {'b': 1.1}),
        ('bm25', {'unknown': True}),
    ],
)
def test_duplicate_unknown_and_bounds_rejected(tmp_path, section, values):
    data = baseline_data()
    data.setdefault(section, {}).update(values)
    with pytest.raises(RagError):
        load_rag_config(write_yaml(tmp_path / 'bad.yaml', data), project_root=tmp_path)


def test_yaml_duplicate_rejected(tmp_path):
    path = tmp_path / 'bad.yaml'
    path.write_text('schema_version: 1\nschema_version: 1\n')
    with pytest.raises(RagError, match='[Dd]uplicate'):
        load_rag_config(path, project_root=tmp_path)


def test_env_priority_and_paths(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://process:8080/v1')
    monkeypatch.delenv('EMBEDDING_CACHE_DIR', raising=False)
    monkeypatch.delenv('LLM_MODEL_PATH', raising=False)
    (tmp_path / '.env').write_text(
        'LLM_BASE_URL=http://dotenv:8080/v1\nLLM_MODEL_PATH=~/model.gguf\nEMBEDDING_CACHE_DIR=\n'
    )
    settings = load_settings(tmp_path)
    assert settings.llm_base_url == 'http://process:8080/v1'
    assert settings.model_path == __import__('pathlib').Path.home() / 'model.gguf'
    assert settings.embedding_cache_dir is None
    data = baseline_data()
    config = load_rag_config(write_yaml(tmp_path / 'config.yaml', data), project_root=tmp_path)
    assert config.corpus.directory == tmp_path / 'data/corpus'


def test_baseline_contract(tmp_path):
    cfg = load_rag_config(
        write_yaml(tmp_path / 'config.yaml', baseline_data()), project_root=tmp_path
    )
    assert (cfg.chunking.chunk_size, cfg.chunking.chunk_overlap) == (512, 64)
    assert cfg.embedding.dimension == 768
    profile = load_llm_profile(write_yaml(tmp_path / 'llm.yaml', {}))
    assert profile.context_size - profile.max_output_tokens - profile.safety_margin == 6400


def test_config_import_does_not_load_models():
    code = (
        'import sys; import dnd_rag.config; '
        'assert "sentence_transformers" not in sys.modules; '
        'assert "torch" not in sys.modules'
    )
    subprocess.run([sys.executable, '-c', code], check=True)


def test_rag_profile_selection_from_other_cwd(tmp_path, monkeypatch):
    import dnd_rag.config as module

    root = __import__('pathlib').Path(__file__).resolve().parents[2]
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('RAG_CONFIG_PATH', raising=False)
    default = module.load_rag_config(None, project_root=root)
    assert not default.embedding.strip_markdown_headings
    assert default.retrieval.limit == 10
    monkeypatch.setenv('RAG_CONFIG_PATH', 'configs/rag/r9.yaml')
    assert module.load_rag_config(None, project_root=root).embedding.strip_markdown_headings
    assert not module.load_rag_config(
        'configs/rag/r3.yaml', project_root=root
    ).embedding.strip_markdown_headings
    monkeypatch.setenv('RAG_CONFIG_PATH', 'does-not-exist.yaml')
    with pytest.raises(RagError, match='does-not-exist'):
        module.load_rag_config(None, project_root=root)


def test_core_without_gold_or_llm(tmp_path):
    import dnd_rag.config as module

    settings = module.RuntimeSettings(project_root=tmp_path)
    assert settings.project_root == tmp_path
    config = module.load_rag_config(
        write_yaml(tmp_path / 'rag.yaml', baseline_data()), project_root=tmp_path
    )
    assert not hasattr(config, 'evaluation')
    assert config.retrieval.limit == 10
