from types import SimpleNamespace as NS

import pytest

from dnd_rag.config import load_experiment, load_settings
from dnd_rag.contracts import RagError
from dnd_rag.indexing.chunking import split_corpus
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.embedding import EmbeddedBatch
from dnd_rag.indexing.identity import assign_ids, make_identity
from dnd_rag.indexing.store import QdrantStore
from tests.rag.fixtures import baseline_data, make_corpus, write_yaml


class FakeClient:
    def __init__(self):
        self.collections = {}
        self.fail_upload = False
        self.fail_network = False
        self.deleted = []
        self.force_grey = False

    def collection_exists(self, name):
        if self.fail_network:
            raise TimeoutError('network failure')
        return name in self.collections

    def create_collection(self, collection_name, **kwargs):
        self.collections[collection_name] = {'options': kwargs, 'points': {}, 'schema': {}}

    def get_collection(self, name):
        c = self.collections[name]
        o = c['options']
        return NS(
            config=NS(
                metadata=o['metadata'],
                params=NS(
                    vectors=o['vectors_config'], shard_number=o['shard_number'], sparse_vectors=None
                ),
                hnsw_config=o['hnsw_config'],
                optimizer_config=o['optimizers_config'],
                quantization_config=o['quantization_config'],
            ),
            payload_schema=c['schema'],
            status='grey' if self.force_grey else 'green',
            optimizer_status='ok',
            points_count=len(c['points']),
            indexed_vectors_count=len(c['points']),
        )

    def count(self, collection_name, **kwargs):
        return NS(count=len(self.collections[collection_name]['points']))

    def get_optimizations(self, collection_name, **kwargs):
        return NS(summary=NS(queued_optimizations=0), running=[])

    def upsert(self, collection_name, points, **kwargs):
        if self.fail_upload:
            raise RuntimeError('upload failed')
        self.collections[collection_name]['points'].update({str(p.id): p for p in points})

    def update_collection(self, collection_name, metadata=None, **kwargs):
        if metadata is not None:
            self.collections[collection_name]['options']['metadata'] = metadata
        if (
            'optimizers_config' in kwargs
            and kwargs['optimizers_config'].max_optimization_threads is not None
        ):
            self.force_grey = False

    def create_payload_index(self, collection_name, field_name, field_schema, **kwargs):
        self.collections[collection_name]['schema'][field_name] = NS(
            params=field_schema, data_type='text'
        )

    def scroll(self, collection_name, **kwargs):
        return list(self.collections[collection_name]['points'].values()), None

    def delete_collection(self, name):
        self.deleted.append(name)
        del self.collections[name]


@pytest.fixture
def store_inputs(tmp_path):
    config = load_experiment(
        write_yaml(tmp_path / 'c.yaml', baseline_data()), project_root=tmp_path
    )
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    client = FakeClient()
    store = QdrantStore(load_settings(tmp_path), client=client)

    def build_inputs(cfg=config):
        identity = make_identity(cfg, corpus, {'qdrant-server': '1.20.0'})
        chunks = assign_ids(split_corpus(corpus, cfg.chunking, len), identity)
        batches = [
            EmbeddedBatch(
                chunks, [[1.0] + [0.0] * (cfg.embedding.dimension - 1)] * len(chunks), 1.0
            )
        ]
        return identity, chunks, batches

    return store, client, config, build_inputs


def test_partial_upload_never_ready(store_inputs):
    store, client, _, inputs = store_inputs
    identity, chunks, batches = inputs()
    client.fail_upload = True
    with pytest.raises(RagError):
        store.build(identity, chunks, batches, on_stage=lambda e: None)
    assert client.collections[identity.collection]['options']['metadata']['status'] == 'building'
    assert store.inspect(identity).status == 'own_incomplete'


def test_retry_upsert_count_and_reset_old_id(store_inputs):
    store, client, _, inputs = store_inputs
    identity, chunks, batches = inputs()
    ready = store.build(identity, chunks, batches, on_stage=lambda e: None)
    points = list(client.collections[identity.collection]['points'].values())
    client.upsert(identity.collection, points)
    assert store.inspect(identity).index.expected_points == len(chunks)
    assert len(store.manifest(ready)) == len(chunks)
    client.collections['neighbour'] = {'untouched': True}
    assert store.reset(identity.index_id) is True
    assert store.reset(identity.index_id) is False
    assert client.collections['neighbour'] == {'untouched': True}


def test_network_not_missing_and_foreign_not_deleted(store_inputs):
    store, client, _, inputs = store_inputs
    identity, chunks, batches = inputs()
    client.fail_network = True
    with pytest.raises(RagError):
        store.inspect(identity)
    assert client.deleted == []
    client.fail_network = False
    store.build(identity, chunks, batches, on_stage=lambda e: None)
    client.collections[identity.collection]['options']['metadata']['owner'] = 'someone_else'
    with pytest.raises(RagError):
        store.reset(identity.index_id)
    assert client.deleted == []


def test_ready_waits_for_optimizer_queue(store_inputs):
    store, client, _, inputs = store_inputs
    identity, chunks, batches = inputs()
    store.build(identity, chunks, batches, on_stage=lambda e: None)
    calls = []

    def optimizations(*args, **kwargs):
        calls.append(True)
        return NS(summary=NS(queued_optimizations=1 if len(calls) == 1 else 0), running=[])

    client.get_optimizations = optimizations
    store._wait_ready(identity, len(chunks), timeout=5)
    assert len(calls) >= 2


def test_completed_index_after_restart_resumes_optimizer(store_inputs):
    store, client, _, inputs = store_inputs
    identity, chunks, batches = inputs()
    ready = store.build(identity, chunks, batches, on_stage=lambda e: None)
    client.force_grey = True
    wait = store._wait_ready
    store._wait_ready = lambda i, e: wait(i, e, timeout=0.5)
    inspected = store.inspect(identity)
    assert inspected.status == 'ready'
    assert inspected.index.build_id == ready.build_id
    assert client.deleted == []


@pytest.mark.parametrize(
    'mode,quant', [('dense', 'none'), ('hybrid', 'scalar_int8'), ('hybrid', 'turboquant_4bit')]
)
def test_index_modes(store_inputs, mode, quant):
    store, client, config, inputs = store_inputs
    cfg = config.model_copy(
        update={
            'retrieval': config.retrieval.model_copy(update={'mode': mode}),
            'index': config.index.model_copy(update={'quantization': quant}),
        }
    )
    identity, chunks, batches = inputs(cfg)
    store.build(identity, chunks, batches, on_stage=lambda e: None)
    collection = client.collections[identity.collection]
    assert collection['options']['hnsw_config'].full_scan_threshold >= 10
    assert ('page_content' in collection['schema']) == (mode == 'hybrid')
    if mode == 'hybrid':
        assert collection['schema']['page_content'].params.scoring is True
    assert collection['options']['vectors_config']['dense'].datatype.value == 'float32'
    assert (collection['options']['quantization_config'] is None) == (quant == 'none')


def test_runtime_readiness_matches_same_build_without_payload_scan(store_inputs, monkeypatch):
    store, client, _, inputs = store_inputs
    identity, chunks, batches = inputs()
    ready = store.build(identity, chunks, batches, on_stage=lambda e: None)
    monkeypatch.setattr(store, '_points', lambda *a: pytest.fail('Health must not scan payloads'))
    assert store.is_ready(ready) is True
    client.collections[identity.collection]['options']['metadata']['build_id'] = 'other-build'
    assert store.is_ready(ready) is False


def test_wrapped_qdrant_timeout_is_distinct(store_inputs):
    import httpx
    from qdrant_client.http.exceptions import ResponseHandlingException

    store, client, _, _ = store_inputs

    def timeout():
        raise ResponseHandlingException(httpx.ReadTimeout('read timed out'))

    client.info = timeout
    with pytest.raises(RagError) as error:
        store.server_version()
    assert error.value.code == 'qdrant_timeout'
