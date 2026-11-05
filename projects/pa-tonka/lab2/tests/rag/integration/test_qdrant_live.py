"""Native server API probe with deterministic vectors and owned disposable indexes."""

import json
import subprocess
from pathlib import Path
from time import monotonic, sleep

import numpy as np
import pytest

from dnd_rag.config import load_experiment, load_settings
from dnd_rag.contracts import ChunkDraft, DraftMetadata
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.embedding import EmbeddedBatch
from dnd_rag.indexing.identity import assign_ids, make_identity
from dnd_rag.indexing.store import QdrantStore
from tests.rag.fixtures import baseline_data, make_corpus, write_yaml

pytestmark = pytest.mark.rag_qdrant
ROOT = Path(__file__).resolve().parents[3]


def test_native_bm25_rrf_quantization_and_persistence(tmp_path):
    from qdrant_client import models as m

    data = baseline_data()
    data.update(embedding={**data['embedding'], 'dimension': 128}, retrieval={'mode': 'hybrid'})
    config = load_experiment(write_yaml(tmp_path / 'c.yaml', data), project_root=tmp_path)
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    store = QdrantStore(load_settings(ROOT))
    assert store.server_version() == '1.20.0'
    report = {'server': store.server_version(), 'profiles': []}
    # Enough float32 vector KB to force the configured HNSW/quantized search path.
    for quant in ('none', 'scalar_int8', 'turboquant_4bit'):
        cfg = config.model_copy(
            update={'index': config.index.model_copy(update={'quantization': quant})}
        )
        identity = make_identity(
            cfg, corpus, {'qdrant-server': store.server_version(), 'probe': 'native-api-v1'}
        )
        drafts = []
        for i in range(1024):
            text = ('shield armor defence' if i == 0 else 'dragon fire breath') + f' {i}'
            book = corpus.books['xphb.md']
            drafts.append(
                ChunkDraft(
                    page_content=text,
                    metadata=DraftMetadata(
                        source_file='xphb.md',
                        body_sha256=book.body_sha256,
                        book_id='XPHB',
                        book_title='Probe',
                        source_system='fixture',
                        upstream_sha='a' * 40,
                        start_char=i * 100,
                        end_char=i * 100 + len(text),
                        line_start=i + 1,
                        line_end=i + 1,
                        token_count=5,
                        sections=[],
                    ),
                )
            )
        chunks = assign_ids(drafts, identity)
        vectors = np.random.default_rng(42).normal(size=(1024, 128)).astype('float32')
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        try:
            ready = store.build(
                identity,
                chunks,
                [EmbeddedBatch(chunks, vectors.tolist(), 0.0)],
                on_stage=lambda e: None,
            )
            assert store.inspect(identity).status == 'ready'
            info = store.client.get_collection(identity.collection)
            assert info.indexed_vectors_count > 0
            params = m.SearchParams(
                hnsw_ef=128, quantization=m.QuantizationSearchParams(ignore=False, rescore=False)
            )
            dense = store.client.query_points(
                identity.collection,
                query=vectors[0].tolist(),
                using='dense',
                search_params=params,
                limit=10,
            ).points
            lexical = store.client.query_points(
                identity.collection,
                query=m.TextQuery(
                    text=m.TextQueryInput(
                        query='shield', scoring=m.Bm25Scoring(bm25=m.Bm25Params(k=1.2, b=0.75))
                    )
                ),
                using='page_content',
                limit=10,
            ).points
            fusion = store.client.query_points(
                identity.collection,
                prefetch=[
                    m.Prefetch(query=vectors[0].tolist(), using='dense', params=params, limit=20),
                    m.Prefetch(query=m.TextQuery(text='shield'), using='page_content', limit=20),
                ],
                query=m.RrfQuery(rrf=m.Rrf(k=2, weights=[1.0, 1.0])),
                limit=10,
            ).points
            assert str(dense[0].id) == chunks[0].metadata.chunk_id
            assert str(lexical[0].id) == chunks[0].metadata.chunk_id
            assert str(fusion[0].id) == chunks[0].metadata.chunk_id
            shared = store.search(ready, vectors[0].tolist(), 'shield', cfg, 10)
            assert shared[0].chunk.metadata.chunk_id == chunks[0].metadata.chunk_id
            assert shared[0].score_kind == 'rrf'
            dense_config = cfg.model_copy(
                update={'retrieval': cfg.retrieval.model_copy(update={'mode': 'dense'})}
            )
            shared_dense = store.search(ready, vectors[0].tolist(), 'shield', dense_config, 10)
            assert shared_dense[0].chunk.metadata.chunk_id == chunks[0].metadata.chunk_id
            assert shared_dense[0].score_kind == 'cosine'
            report['profiles'].append(
                {
                    'quantization': quant,
                    'count': 1024,
                    'indexed_vectors_count': info.indexed_vectors_count,
                    'dense_score': dense[0].score,
                    'bm25_score': lexical[0].score,
                    'rrf_score': fusion[0].score,
                    'build_id': ready.build_id,
                }
            )
            if quant == 'none':
                subprocess.run(
                    ['docker', 'compose', '-f', str(ROOT / 'compose.yaml'), 'restart', 'qdrant'],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                )
                deadline = monotonic() + 60
                while True:
                    try:
                        store.server_version()
                        break
                    except Exception:
                        if monotonic() > deadline:
                            raise
                        sleep(0.25)
                store._wait_ready(identity, 1024, timeout=60)
                assert store.inspect(identity).status == 'ready'
                report['persistence_restart'] = True
            assert store.reset(identity.index_id) is True
            assert store.reset(identity.index_id) is False
        finally:
            store.reset(identity.index_id)
    (ROOT / '.agents/work/implementation/qdrant-probe.json').write_text(
        json.dumps(report, indent=2) + '\n'
    )
