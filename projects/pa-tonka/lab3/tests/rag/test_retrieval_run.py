import json
from types import SimpleNamespace as NS

import pytest

from dnd_rag.config import load_experiment, load_settings
from dnd_rag.contracts import EnsureResult, RagError, ReadyIndex, RetrievalHit, StageEvent
from dnd_rag.evaluation import retrieval_run
from dnd_rag.indexing.chunking import split_corpus
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.identity import assign_ids, make_identity
from tests.rag.fixtures import baseline_data, make_corpus, make_gold, write_yaml


@pytest.fixture
def run_inputs(tmp_path, monkeypatch):
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    gold_path = make_gold(tmp_path / 'gold', corpus)
    data = baseline_data()
    data['corpus']['directory'] = str(tmp_path / 'corpus')
    data['evaluation'] = {'questions': str(gold_path)}
    path = write_yaml(tmp_path / 'config.yaml', data)
    cfg = load_experiment(path, project_root=tmp_path)
    identity = make_identity(cfg, corpus, {'server': '1.20.0'})
    chunks = assign_ids(split_corpus(corpus, cfg.chunking, len), identity)
    index = ReadyIndex(
        **identity.model_dump(),
        build_id='build1',
        expected_points=len(chunks),
        build_provenance={'original_build_ms': 123.0},
    )
    stages = [
        StageEvent(name=n, status='reused', elapsed_ms=None)
        for n in ('splitting', 'embedding', 'upload')
    ]
    calls = []

    def ensure(*args, **kwargs):
        calls.append('ensure')
        for event in stages:
            kwargs['on_stage'](event)
        return EnsureResult(index=index, action='reused', reason='Fixture ready', stages=stages)

    monkeypatch.setattr(retrieval_run, 'ensure_index', ensure)
    monkeypatch.setattr(retrieval_run, 'QueryEncoder', lambda *a: NS(encode=lambda q: [1.0] * 768))

    class Store:
        def __init__(self, *args):
            self.fail_on = None
            self.count = 0

        def manifest(self, index):
            from dnd_rag.contracts import ChunkRef

            return [
                ChunkRef.model_validate(
                    {k: v for k, v in c.metadata.model_dump().items() if k in ChunkRef.model_fields}
                )
                for c in chunks
            ]

        def search(self, index, vector, question, config, limit):
            self.count += 1
            if self.fail_on == self.count:
                raise RagError('service_down', 'Fixture unavailable')
            return [
                RetrievalHit(rank=i + 1, score=0.5, score_kind='cosine', chunk=c)
                for i, c in enumerate(chunks[:10])
            ]

    store = Store()
    monkeypatch.setattr(retrieval_run, 'QdrantStore', lambda *a: store)
    return path, load_settings(tmp_path), calls, store


def test_existing_name_fails_before_index_side_effects(run_inputs):
    path, settings, calls, _ = run_inputs
    (settings.project_root / 'results/existing').mkdir(parents=True)
    with pytest.raises(RagError):
        retrieval_run.run_retrieval_experiment(path, 'existing', settings)
    assert calls == []


def test_reused_stage_timings_and_recompute_without_qdrant(run_inputs):
    path, settings, calls, store = run_inputs
    output = retrieval_run.run_retrieval_experiment(path, 'reuse', settings)
    metadata = json.loads((output / 'run.json').read_text())
    assert metadata['index_action'] == 'reused'
    assert metadata['stages']['embedding']['elapsed_ms'] is None
    assert metadata['build_provenance']['original_build_ms'] == 123.0
    saved = json.loads((output / 'metrics.json').read_text())
    assert saved['question_count'] == 20
    assert store.count == 20
    store.fail_on = 21
    assert retrieval_run.recompute_saved_metrics(output) == saved['metrics']
    assert store.count == 20


def test_failed_run_kept(run_inputs):
    path, settings, calls, store = run_inputs
    store.fail_on = 2
    with pytest.raises(RagError):
        retrieval_run.run_retrieval_experiment(path, 'failed', settings)
    output = settings.project_root / 'results/failed'
    data = json.loads((output / 'run.json').read_text())
    assert data['status'] == 'failed' and data['error']['code'] == 'service_down'
    assert not (output / 'metrics.json').exists()
    assert len((output / 'per_question.jsonl').read_text().splitlines()) == 2
