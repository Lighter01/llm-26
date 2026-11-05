"""Owned Qdrant collections, validated passports, batched upload and targeted reset."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic, perf_counter, sleep

from qdrant_client import QdrantClient
from qdrant_client import models as m

from dnd_rag.contracts import (
    Chunk,
    ChunkRef,
    RagError,
    ReadyIndex,
    RetrievalHit,
    StageEvent,
)
from dnd_rag.indexing.identity import FULL_SCAN_THRESHOLD, INDEXING_THRESHOLD, digest

OWNER = 'dnd_rag_lab2'


def utc_now():
    return datetime.now(UTC).isoformat()


def quantization_config(kind):
    if kind == 'scalar_int8':
        return m.ScalarQuantization(
            scalar=m.ScalarQuantizationConfig(type=m.ScalarType.INT8, memory=m.Memory.PINNED)
        )
    if kind == 'turboquant_4bit':
        return m.TurboQuantization(
            turbo=m.TurboQuantQuantizationConfig(
                bits=m.TurboQuantBitSize.BITS4, memory=m.Memory.PINNED
            )
        )
    return None


def text_index_params(spec):
    return m.TextIndexParams(**spec, type=m.TextIndexType.TEXT)


@dataclass(frozen=True)
class IndexInspection:
    status: str
    reason: str
    index: ReadyIndex | None = None


class QdrantStore:
    def __init__(self, settings, *, client=None):
        self.client = client or QdrantClient(url=settings.qdrant_url, timeout=60)

    def _call(self, method, *args, **kwargs):
        try:
            return getattr(self.client, method)(*args, **kwargs)
        except RagError:
            raise
        except Exception as exc:
            raise RagError('qdrant_unavailable', f'Qdrant {method}: {exc}') from exc

    def server_version(self):
        return self._call('info').version

    def _owned_metadata(self, info, index_id):
        meta = info.config.metadata or {}
        spec = meta.get('build_spec')
        if (
            meta.get('owner') != OWNER
            or meta.get('index_id') != index_id
            or not isinstance(spec, dict)
            or digest(spec) != index_id
        ):
            raise RagError(
                'index_ownership',
                'Collection ownership/passport cannot be verified',
                {'index_id': index_id},
            )
        return meta

    def _schema_matches(self, info, spec):
        vectors = info.config.params.vectors
        expected = spec['index']
        if not isinstance(vectors, dict) or set(vectors) != {'dense'}:
            return False
        v = vectors['dense']
        if (
            v.size != spec['embedding']['dimension']
            or v.distance != m.Distance.COSINE
            or v.datatype != m.Datatype.FLOAT32
            or info.config.params.shard_number != 1
            or info.config.params.sparse_vectors
        ):
            return False
        hnsw = info.config.hnsw_config
        if (
            hnsw.m != expected['hnsw']['m']
            or hnsw.ef_construct != expected['hnsw']['ef_construction']
            or hnsw.full_scan_threshold != FULL_SCAN_THRESHOLD
            or info.config.optimizer_config.indexing_threshold != INDEXING_THRESHOLD
        ):
            return False
        actual_quant = info.config.quantization_config
        wanted_quant = quantization_config(expected['quantization'])
        if actual_quant != wanted_quant:
            return False
        field = info.payload_schema.get('page_content')
        if spec['mode'] == 'dense':
            return field is None
        if not field or not field.params:
            return False
        actual = field.params.model_dump(mode='json', exclude_none=True)
        wanted = text_index_params(spec['bm25']).model_dump(mode='json', exclude_none=True)
        if actual.get('scoring') == {'type': 'bm25'}:
            actual['scoring'] = True
        return all(actual.get(key) == value for key, value in wanted.items())

    def _points(self, collection):
        offset = None
        while True:
            points, offset = self._call(
                'scroll',
                collection_name=collection,
                offset=offset,
                limit=256,
                with_payload=True,
                with_vectors=False,
            )
            yield from points
            if offset is None:
                break

    def _validate_points(self, identity, expected):
        count = 0
        hashes = {
            b['source_file']: b['body_sha256'] for b in identity.build_spec['corpus']['files']
        }
        for point in self._points(identity.collection):
            try:
                chunk = Chunk.model_validate(point.payload)
                meta = chunk.metadata
                valid = (
                    meta.index_id == identity.index_id
                    and meta.chunk_id == str(point.id)
                    and hashes.get(meta.source_file) == meta.body_sha256
                    and 0 <= meta.start_char < meta.end_char
                    and len(chunk.page_content) == meta.end_char - meta.start_char
                    and 1 <= meta.line_start <= meta.line_end
                    and meta.token_count >= 0
                )
            except (ValueError, TypeError):
                return False
            if not valid:
                return False
            count += 1
        return count == expected

    def inspect(self, identity):
        if not self._call('collection_exists', identity.collection):
            return IndexInspection('missing', 'Collection does not exist')
        info = self._call('get_collection', identity.collection)
        meta = self._owned_metadata(info, identity.index_id)
        if (
            meta.get('status') != 'ready'
            or meta.get('build_spec') != identity.build_spec
            or not self._schema_matches(info, identity.build_spec)
        ):
            return IndexInspection(
                'own_incomplete', 'Owned collection is incomplete or schema differs'
            )
        expected = meta.get('expected_points')
        count = self._call('count', collection_name=identity.collection, exact=True).count
        if (
            type(expected) is not int
            or expected <= 0
            or count != expected
            or not self._validate_points(identity, expected)
        ):
            return IndexInspection(
                'own_incomplete', 'Count, payload or readiness validation failed'
            )
        if info.status in ('grey', 'yellow'):
            info = self._wait_ready(identity, expected)
            meta = self._owned_metadata(info, identity.index_id)
        if info.status != 'green' or info.optimizer_status != 'ok':
            return IndexInspection('own_incomplete', 'Qdrant index is not ready')
        ready = ReadyIndex(
            **identity.model_dump(),
            build_id=meta['build_id'],
            expected_points=expected,
            build_provenance=meta,
        )
        return IndexInspection('ready', 'Compatible complete index', ready)

    def _wait_ready(self, identity, expected, timeout=600):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            info = self._call('get_collection', identity.collection)
            if info.status == 'red' or info.optimizer_status != 'ok':
                raise RagError('index_failed', f'Qdrant optimizer: {info.optimizer_status}')
            if info.status == 'grey':
                meta = self._owned_metadata(info, identity.index_id)
                # v1.20 ignores empty/no-change optimizer diffs after restart.
                # Change only execution concurrency to wake paused optimization.
                threads = info.config.optimizer_config.max_optimization_threads
                resumed_threads = 2 if threads == 1 else 1
                self._call(
                    'update_collection',
                    collection_name=identity.collection,
                    optimizers_config=m.OptimizersConfigDiff(
                        max_optimization_threads=resumed_threads
                    ),
                    metadata={
                        **meta,
                        'last_optimizer_resume': {
                            'at': utc_now(),
                            'max_optimization_threads': resumed_threads,
                        },
                    },
                )
            if (
                info.status == 'green'
                and info.points_count == expected
                and (
                    expected * identity.build_spec['embedding']['dimension'] * 4 <= 1024
                    or info.indexed_vectors_count > 0
                )
                and self._schema_matches(info, identity.build_spec)
            ):
                # indexed_vectors_count need not equal points_count: small segments may remain plain.
                jobs = self._call('get_optimizations', collection_name=identity.collection)
                if not jobs.running and jobs.summary.queued_optimizations == 0:
                    return info
            sleep(0.25)
        raise RagError(
            'index_timeout', f'Qdrant indexes did not become ready within {timeout} seconds'
        )

    def build(self, identity, chunks, batches, on_stage):
        if not chunks:
            raise RagError('empty_index', 'Cannot build an empty index')
        inspection = self.inspect(identity)
        if inspection.status != 'missing':
            self.reset(identity.index_id)
        spec = identity.build_spec
        passport = {
            'schema_version': 1,
            'owner': OWNER,
            'index_id': identity.index_id,
            'build_spec': spec,
            'build_id': str(uuid.uuid4()),
            'status': 'building',
            'expected_points': len(chunks),
            'created_at': utc_now(),
            'ready_at': None,
            'versions': spec['versions'],
            'stages': [],
        }
        self._call(
            'create_collection',
            collection_name=identity.collection,
            vectors_config={
                'dense': m.VectorParams(
                    size=spec['embedding']['dimension'],
                    distance=m.Distance.COSINE,
                    datatype=m.Datatype.FLOAT32,
                )
            },
            shard_number=1,
            hnsw_config=m.HnswConfigDiff(
                m=spec['index']['hnsw']['m'],
                ef_construct=spec['index']['hnsw']['ef_construction'],
                full_scan_threshold=FULL_SCAN_THRESHOLD,
            ),
            optimizers_config=m.OptimizersConfigDiff(indexing_threshold=INDEXING_THRESHOLD),
            quantization_config=quantization_config(spec['index']['quantization']),
            metadata=passport,
        )
        embedding_ms, upload_ms = 0.0, 0.0
        for batch in batches:
            if len(batch.chunks) != len(batch.vectors):
                raise RagError('invalid_batch', 'Chunk and vector counts differ')
            embedding_ms += batch.embedding_elapsed_ms
            before = perf_counter()
            points = [
                m.PointStruct(
                    id=chunk.metadata.chunk_id, vector={'dense': vector}, payload=chunk.model_dump()
                )
                for chunk, vector in zip(batch.chunks, batch.vectors)
            ]
            self._call('upsert', collection_name=identity.collection, points=points, wait=True)
            upload_ms += (perf_counter() - before) * 1000

        def record(name, elapsed):
            event = StageEvent(name=name, status='executed', elapsed_ms=elapsed)
            passport['stages'].append(event.model_dump())
            on_stage(event)

        record('embedding', embedding_ms)
        record('upload', upload_ms)
        if spec['mode'] == 'hybrid':
            before = perf_counter()
            self._call(
                'create_payload_index',
                collection_name=identity.collection,
                field_name='page_content',
                field_schema=text_index_params(spec['bm25']),
                wait=True,
            )
            record('bm25_index', (perf_counter() - before) * 1000)
        before = perf_counter()
        info = self._wait_ready(identity, len(chunks))
        if not self._validate_points(identity, len(chunks)):
            raise RagError('index_incomplete', 'Uploaded payloads do not match the index passport')
        record('index_wait', (perf_counter() - before) * 1000)
        passport.update(
            status='ready',
            ready_at=utc_now(),
            indexed_vectors_count=info.indexed_vectors_count,
            storage_vectors_bytes=len(chunks) * spec['embedding']['dimension'] * 4,
        )
        self._call('update_collection', collection_name=identity.collection, metadata=passport)
        return ReadyIndex(
            **identity.model_dump(),
            build_id=passport['build_id'],
            expected_points=len(chunks),
            build_provenance=passport,
        )

    def reset(self, index_id):
        if not isinstance(index_id, str) or not re.fullmatch('[a-f0-9]{64}', index_id):
            raise RagError('invalid_index_id', 'Expected a full lowercase SHA256 index_id')
        collection = f'rag_{index_id}'
        if not self._call('collection_exists', collection):
            return False
        self._owned_metadata(self._call('get_collection', collection), index_id)
        self._call('delete_collection', collection)
        return True

    def manifest(self, index):
        fields = set(ChunkRef.model_fields)
        return [
            ChunkRef.model_validate(
                {k: v for k, v in point.payload['metadata'].items() if k in fields}
            )
            for point in self._points(index.collection)
        ]

    def search(self, index, vector, question, config, limit):
        params = m.SearchParams(hnsw_ef=config.retrieval.ef_search)
        if config.index.quantization != 'none':
            params.quantization = m.QuantizationSearchParams(ignore=False, rescore=False)
        request = {
            'collection_name': index.collection,
            'limit': limit,
            'with_payload': True,
            'with_vectors': False,
        }
        if config.retrieval.mode == 'dense':
            request.update(query=vector, using='dense', search_params=params)
        else:
            text_query = m.TextQuery(
                text=m.TextQueryInput(
                    query=question,
                    scoring=m.Bm25Scoring(bm25=m.Bm25Params(k=config.bm25.k1, b=config.bm25.b)),
                )
            )
            request.update(
                prefetch=[
                    m.Prefetch(
                        query=vector,
                        using='dense',
                        params=params,
                        limit=config.retrieval.hybrid_candidates_per_branch,
                    ),
                    m.Prefetch(
                        query=text_query,
                        using='page_content',
                        limit=config.retrieval.hybrid_candidates_per_branch,
                    ),
                ],
                query=m.RrfQuery(rrf=m.Rrf(k=config.retrieval.rrf_constant, weights=[1.0, 1.0])),
            )
        points = self._call('query_points', **request).points
        hits, seen = [], set()
        for point in points:
            point_id = str(point.id)
            if point_id in seen:
                continue
            seen.add(point_id)
            chunk = Chunk.model_validate(point.payload)
            if chunk.metadata.chunk_id != point_id or chunk.metadata.index_id != index.index_id:
                raise RagError('index_incomplete', 'Search payload disagrees with the ready index')
            hits.append(
                RetrievalHit(
                    rank=len(hits) + 1,
                    score=float(point.score),
                    score_kind='cosine' if config.retrieval.mode == 'dense' else 'rrf',
                    chunk=chunk,
                )
            )
        return hits
