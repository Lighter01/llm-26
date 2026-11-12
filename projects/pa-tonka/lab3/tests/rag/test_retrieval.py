from types import SimpleNamespace as NS

import pytest

from dnd_rag.config import load_rag_config, load_settings
from dnd_rag.contracts import RagError
from dnd_rag.indexing.chunking import split_corpus
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.embedding import EmbeddedBatch
from dnd_rag.indexing.identity import assign_ids, make_identity
from dnd_rag.indexing.store import QdrantStore
from dnd_rag.retrieval import Retriever
from tests.rag.fixtures import baseline_data, make_corpus, write_yaml
from tests.rag.test_store import FakeClient


@pytest.fixture
def inputs(tmp_path):
    config = load_rag_config(
        write_yaml(tmp_path / 'c.yaml', baseline_data()), project_root=tmp_path
    )
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    client = FakeClient()
    store = QdrantStore(load_settings(tmp_path), client=client)

    def retriever(mode='dense', quant='none'):
        cfg = config.model_copy(
            update={
                'retrieval': config.retrieval.model_copy(update={'mode': mode}),
                'index': config.index.model_copy(update={'quantization': quant}),
            }
        )
        identity = make_identity(cfg, corpus, {'server': '1.20.0'})
        chunks = assign_ids(split_corpus(corpus, cfg.chunking, len), identity)
        ready = store.build(
            identity,
            chunks,
            [EmbeddedBatch(chunks, [[1.0] * 768] * len(chunks), 0.0)],
            on_stage=lambda e: None,
        )
        points = [NS(id=c.metadata.chunk_id, score=0.5, payload=c.model_dump()) for c in chunks[:2]]
        requests = []

        def query_points(**kwargs):
            requests.append(kwargs)
            return NS(points=[points[0], points[0], points[1]])

        client.query_points = query_points
        return Retriever(ready, cfg, NS(encode=lambda q: [1.0] * 768), store), requests, client

    return retriever


@pytest.mark.parametrize('mode', ['dense', 'hybrid'])
@pytest.mark.parametrize('quant', ['none', 'scalar_int8', 'turboquant_4bit'])
def test_dense_and_hybrid_requests(inputs, mode, quant):
    retriever, requests, _ = inputs(mode, quant)
    result = retriever.retrieve('What is armor?')
    request = requests[-1]
    assert 'score_threshold' not in request
    if mode == 'dense':
        assert request['using'] == 'dense'
        dense_params = request['search_params']
    else:
        assert [p.limit for p in request['prefetch']] == [20, 20]
        assert request['limit'] == 10
        dense_params = request['prefetch'][0].params
        assert request['prefetch'][1].using == 'page_content'
        assert request['prefetch'][1].query.text.scoring.bm25.k == 1.2
        assert request['prefetch'][1].query.text.scoring.bm25.b == 0.75
        assert request['query'].rrf.k == 2
        assert request['query'].rrf.weights == [1.0, 1.0]
    assert dense_params.hnsw_ef == 128
    if quant != 'none':
        assert dense_params.quantization.rescore is False
        assert dense_params.quantization.ignore is False
        assert dense_params.quantization.oversampling is None
    assert [h.rank for h in result.hits] == [1, 2]
    assert result.hits[0].score_kind == ('rrf' if mode == 'hybrid' else 'cosine')
    assert result.hits[0].chunk.metadata.start_char < result.hits[1].chunk.metadata.start_char


def test_empty_vs_dependency_error(inputs):
    retriever, _, client = inputs()
    client.query_points = lambda **k: NS(points=[])
    assert retriever.retrieve('A question?').hits == []

    def fail(**kwargs):
        raise TimeoutError('service down')

    client.query_points = fail
    with pytest.raises(RagError):
        retriever.retrieve('A question?')
    for question, limit in [('', None), ('ok', 0), ('ok', 11), ('ok', True)]:
        with pytest.raises(RagError):
            retriever.retrieve(question, limit)


def test_health_checks_live_index_without_encoding(inputs):
    retriever, _, client = inputs()
    retriever.encoder.encode = lambda q: pytest.fail('Health must not embed a query')
    assert retriever.readiness() == {'index_ready': True, 'query_encoder_ready': True}
    del client.collections[retriever.index.collection]
    assert retriever.readiness() == {'index_ready': False, 'query_encoder_ready': True}
