from types import SimpleNamespace as NS

import pytest

from dnd_rag.config import load_rag_config, load_settings
from dnd_rag.contracts import ReadyIndex
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.identity import make_identity
from dnd_rag.runtime import index as application
from dnd_rag.runtime.processes import RuntimeSession
from tests.rag.fixtures import baseline_data, make_corpus, write_yaml


@pytest.mark.parametrize(
    'state,rebuild,action',
    [
        ('ready', False, 'reused'),
        ('ready', True, 'rebuilt'),
        ('missing', False, 'built'),
        ('own_incomplete', False, 'rebuilt'),
    ],
)
def test_reuse_never_splits_loads_or_embeds(tmp_path, monkeypatch, state, rebuild, action):
    data = baseline_data()
    data['corpus']['directory'] = str(make_corpus(tmp_path / 'corpus'))
    cfg = load_rag_config(write_yaml(tmp_path / 'config.yaml', data), project_root=tmp_path)
    settings = load_settings(tmp_path)
    versions = {'qdrant-server': '1.20.0'}
    identity = make_identity(cfg, load_corpus(cfg.corpus.directory), versions)
    ready = ReadyIndex(
        **identity.model_dump(), build_id='build1', expected_points=1, build_provenance={}
    )
    events = []

    class Store:
        def server_version(self):
            return '1.20.0'

        def inspect(self, identity):
            return NS(status=state, reason='fixture', index=ready)

    monkeypatch.setattr(application, 'ensure_qdrant', lambda *a: Store())
    monkeypatch.setattr(application, 'library_versions', lambda *a: versions)
    monkeypatch.setattr(application, '_check_gpu_conflict', lambda *a: None)

    def worker(*a, **k):
        events.extend(['split', 'embed', 'upload', 'ready', 'worker_exited'])
        return ready, []

    monkeypatch.setattr(application, 'run_build_worker', worker)
    with RuntimeSession(tmp_path) as session:
        result = application.ensure_index(cfg, settings, session, rebuild=rebuild)
    assert result.action == action
    assert events == (
        [] if action == 'reused' else ['split', 'embed', 'upload', 'ready', 'worker_exited']
    )
    if action == 'reused':
        assert all(e.elapsed_ms is None for e in result.stages if e.status == 'reused')


def test_reset_id_needs_no_corpus_or_models(tmp_path, monkeypatch):
    settings = load_settings(tmp_path)
    calls = []
    store = NS(reset=lambda id: calls.append(id) or False)
    monkeypatch.setattr(application, 'ensure_qdrant', lambda *a: store)
    with RuntimeSession(tmp_path) as session:
        assert application.reset_index(settings, session, index_id='a' * 64) is False
    assert calls == ['a' * 64]
