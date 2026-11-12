"""Canonical build identity and deterministic point IDs, without model loading."""

import json
import uuid
from collections.abc import Sequence
from hashlib import sha256
from importlib.metadata import version

from dnd_rag.config import RagConfig
from dnd_rag.contracts import Chunk, ChunkDraft, ChunkMetadata, IndexIdentity
from dnd_rag.indexing.corpus import CorpusSnapshot

ALGORITHMS = {'coordinates': 1, 'chunking': 1, 'metadata': 1, 'embedding_input': 1}
# KB. Small corpus segments must actually build HNSW/quantized search structures.
INDEXING_THRESHOLD = 1
FULL_SCAN_THRESHOLD = 10


def canonical_json(value) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False
    )


def digest(value) -> str:
    return sha256(canonical_json(value).encode('utf-8')).hexdigest()


def library_versions(server_version: str) -> dict[str, str]:
    packages = (
        'langchain-core',
        'langchain-text-splitters',
        'transformers',
        'tokenizers',
        'sentence-transformers',
        'torch',
        'torchvision',
        'numpy',
        'qdrant-client',
        'markdown-it-py',
        'PyYAML',
    )
    return {**{name: version(name) for name in packages}, 'qdrant-server': server_version}


def make_identity(
    config: RagConfig, corpus: CorpusSnapshot, versions: dict[str, str]
) -> IndexIdentity:
    chunking = config.chunking.model_dump()
    if config.chunking.strategy != 'source_map_recursive':
        chunking.pop('max_heading_level')
    embedding = config.embedding.model_dump()
    embedding.pop('document_batch_size')
    embedding.pop('query_prompt_name')
    embedding.update(
        tokenizer_id=config.embedding.model_id,
        tokenizer_revision=config.embedding.revision,
        text_only=True,
        input_format='title: {title} | text: {content}',
        normalize_embeddings=True,
        max_input_tokens=8192,
    )
    spec = {
        'schema_version': 1,
        'algorithms': ALGORITHMS,
        'corpus': {
            'files': [
                {'source_file': name, 'body_sha256': book.body_sha256, 'metadata': book.metadata}
                for name, book in corpus.books.items()
            ],
            'source_map_sha256': corpus.source_map_sha256,
        },
        'chunking': {
            **chunking,
            'keep_separator': True,
            'strip_whitespace': False,
            'coordinate_policy': 'unicode-half-open-lf-body',
        },
        'embedding': embedding,
        'index': config.index.model_dump(),
        'qdrant': {
            'vector_name': 'dense',
            'distance': 'Cosine',
            'datatype': 'float32',
            'shard_number': 1,
            'indexing_threshold': INDEXING_THRESHOLD,
        },
        'mode': config.retrieval.mode,
        'versions': versions,
    }
    if config.retrieval.mode == 'hybrid':
        spec['bm25'] = config.bm25.model_dump(exclude={'k1', 'b'})
        spec['bm25'].update(
            scoring=True,
            min_token_len=1,
            max_token_len=40,
            ascii_folding=False,
            phrase_matching=False,
            memory='pinned',
            enable_hnsw=False,
        )
    index_id = digest(spec)
    return IndexIdentity(index_id=index_id, collection=f'rag_{index_id}', build_spec=spec)


def assign_ids(drafts: Sequence[ChunkDraft], identity: IndexIdentity) -> list[Chunk]:
    result, seen = [], {}
    for draft in drafts:
        m = draft.metadata
        name = 'dnd-rag-lab3:' + canonical_json(
            [identity.index_id, m.source_file, m.start_char, m.end_char]
        )
        chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, name))
        if chunk_id in seen:
            if seen[chunk_id] != draft.page_content:
                raise ValueError('Same chunk coordinates have different contents')
            continue
        seen[chunk_id] = draft.page_content
        result.append(
            Chunk(
                page_content=draft.page_content,
                metadata=ChunkMetadata(
                    **m.model_dump(), chunk_id=chunk_id, index_id=identity.index_id
                ),
            )
        )
    return result
