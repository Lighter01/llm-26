import uuid

from dnd_rag.config import load_rag_config
from dnd_rag.indexing.chunking import split_corpus
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.identity import assign_ids, canonical_json, make_identity
from tests.rag.fixtures import baseline_data, make_corpus, write_yaml


def test_effective_build_fingerprint(tmp_path):
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    config = load_rag_config(
        write_yaml(tmp_path / 'c.yaml', baseline_data()), project_root=tmp_path
    )
    versions = {'qdrant-server': '1.20.0', 'splitter': '1.1.3'}
    first = make_identity(config, corpus, versions)
    query = config.model_copy(
        update={
            'retrieval': config.retrieval.model_copy(update={'ef_search': 256, 'rrf_constant': 60}),
            'embedding': config.embedding.model_copy(
                update={'query_prompt_name': 'SearchQuery', 'document_batch_size': 1}
            ),
            'bm25': config.bm25.model_copy(update={'k1': 1.5, 'b': 0.5, 'lowercase': False}),
        }
    )
    assert make_identity(query, corpus, versions).index_id == first.index_id
    for section, key, value in [
        ('chunking', 'chunk_size', 768),
        ('embedding', 'document_dtype', 'float32'),
        ('embedding', 'include_title', False),
        ('embedding', 'dimension', 128),
        ('index', 'quantization', 'scalar_int8'),
        ('retrieval', 'mode', 'hybrid'),
    ]:
        changed = config.model_copy(
            update={section: getattr(config, section).model_copy(update={key: value})}
        )
        assert make_identity(changed, corpus, versions).index_id != first.index_id
    depth = config.model_copy(
        update={'chunking': config.chunking.model_copy(update={'max_heading_level': 2})}
    )
    assert make_identity(depth, corpus, versions).index_id == first.index_id
    corpus.books['xphb.md'].metadata['title'] = 'Another title'
    assert make_identity(config, corpus, versions).index_id != first.index_id


def test_stable_point_ids(tmp_path):
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    config = load_rag_config(
        write_yaml(tmp_path / 'c.yaml', baseline_data()), project_root=tmp_path
    )
    identity = make_identity(config, corpus, {'qdrant-server': '1.20.0'})
    drafts = split_corpus(corpus, config.chunking, len)
    chunks = assign_ids(drafts, identity)
    assert [c.metadata.chunk_id for c in chunks] == [
        c.metadata.chunk_id for c in assign_ids(drafts, identity)
    ]
    first = chunks[0]
    expected = uuid.uuid5(
        uuid.NAMESPACE_URL,
        'dnd-rag-lab3:'
        + canonical_json(
            [identity.index_id, 'xphb.md', first.metadata.start_char, first.metadata.end_char]
        ),
    )
    assert first.metadata.chunk_id == str(expected)
    assert len({c.metadata.chunk_id for c in chunks}) == len(chunks)
    assert first.to_document().page_content == first.page_content


def test_r3_r9_same_spans_different_identity(tmp_path):
    import dnd_rag.config as module

    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    data = baseline_data()
    data['chunking'] = {'strategy': 'source_map_recursive'}
    r3 = module.load_rag_config(write_yaml(tmp_path / 'r3.yaml', data), project_root=tmp_path)
    data['embedding']['strip_markdown_headings'] = True
    r9 = module.load_rag_config(write_yaml(tmp_path / 'r9.yaml', data), project_root=tmp_path)
    assert make_identity(r3, corpus, {}).index_id != make_identity(r9, corpus, {}).index_id
    drafts3 = split_corpus(corpus, r3.chunking, len)
    drafts9 = split_corpus(corpus, r9.chunking, len)
    assert [(c.page_content, c.metadata.start_char, c.metadata.end_char) for c in drafts3] == [
        (c.page_content, c.metadata.start_char, c.metadata.end_char) for c in drafts9
    ]
