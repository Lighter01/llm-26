import numpy as np
import pytest

from dnd_rag.config import ChunkingConfig, EmbeddingConfig, load_settings
from dnd_rag.contracts import RagError
from dnd_rag.indexing import embedding
from dnd_rag.indexing.chunking import split_corpus
from dnd_rag.indexing.corpus import load_corpus
from tests.rag.fixtures import REVISION, make_corpus


class FakeTokenizer:
    def encode(self, text, *, add_special_tokens=True, truncation=False):
        assert not truncation
        return list(range(len(text) + int(add_special_tokens)))


class FakeModel:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.max_seq_length = 8192
        self.tokenizer = FakeTokenizer()
        self.prompts = {
            'QuestionAnswering': 'task: question answering | query: ',
            'SearchQuery': 'task: search result | query: ',
        }
        self.calls = []
        self.bad = False

    def encode(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        size = 1 if isinstance(texts, str) else len(texts)
        result = np.ones((size, kwargs['truncate_dim']), dtype=np.float32)
        if self.bad:
            result[0, 0] = np.nan
        return result[0] if isinstance(texts, str) else result


@pytest.fixture
def inputs(tmp_path):
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    chunks = split_corpus(corpus, ChunkingConfig(chunk_size=100, chunk_overlap=20), len)
    return corpus, chunks, load_settings(tmp_path)


def test_four_heading_modes(inputs):
    corpus, chunks, _ = inputs
    original = [c.page_content for c in chunks]
    whole = chunks[0].model_copy(
        update={
            'page_content': corpus.books['xphb.md'].body,
            'metadata': chunks[0].metadata.model_copy(
                update={
                    'start_char': 0,
                    'end_char': len(corpus.books['xphb.md'].body),
                    'sections': corpus.books['xphb.md'].attributions(
                        0, len(corpus.books['xphb.md'].body)
                    ),
                }
            ),
        }
    )
    for title in (True, False):
        for strip in (True, False):
            cfg = EmbeddingConfig(
                revision=REVISION, include_title=title, strip_markdown_headings=strip
            )
            text = embedding.prepare_embedding_text(whole, corpus, cfg)
            assert text.startswith('title: xphb title — Intro' if title else 'title: none | text: ')
            assert ('\n# Intro\n' in text) is not strip
            assert '\n# not a heading\n' in text
            assert text.count('Intro > Parent;') <= 1
    assert [c.page_content for c in chunks] == original
    # Partial heading: remove only the mapped intersection, not subsequent body.
    piece = whole.model_copy(
        update={
            'page_content': whole.page_content[5:17],
            'metadata': whole.metadata.model_copy(update={'start_char': 5, 'end_char': 17}),
        }
    )
    cfg = EmbeddingConfig(revision=REVISION, include_title=False, strip_markdown_headings=True)
    assert embedding.prepare_embedding_text(piece, corpus, cfg).endswith('\nWelcome')


def test_no_double_prompt_and_no_truncation(inputs, monkeypatch):
    corpus, drafts, settings = inputs
    model = FakeModel()
    monkeypatch.setattr(embedding, '_load_model', lambda *a, **k: model)
    cfg = EmbeddingConfig(revision=REVISION, document_batch_size=2)
    encoder = embedding.DocumentEncoder(cfg, settings)
    list(encoder.iter_batches(drafts[:3], corpus))
    assert len(model.calls) == 2
    assert all(k['prompt'] == '' and 'prompt_name' not in k for _, k in model.calls)
    assert model.calls[0][0][0].count('title: ') == 1
    query = embedding.QueryEncoder(cfg, settings)
    query.encode('What is AC?')
    assert model.calls[-1][1]['prompt_name'] == 'QuestionAnswering'
    assert model.calls[-1][0] == 'What is AC?'
    model.max_seq_length = 5
    before = len(model.calls)
    with pytest.raises(RagError, match='[Ii]nput'):
        query.encode('A long question')
    with pytest.raises(RagError, match='[Ii]nput'):
        list(encoder.iter_batches(drafts[:1], corpus))
    assert len(model.calls) == before


def test_dtype_devices_and_vector_validation(inputs, monkeypatch):
    import torch

    corpus, drafts, settings = inputs
    created = []

    def factory(model_id, **kwargs):
        model = FakeModel(**kwargs)
        created.append(model)
        return model

    monkeypatch.setattr(embedding, '_sentence_transformer_class', lambda: factory)
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: True)
    monkeypatch.setattr(torch.cuda, 'is_bf16_supported', lambda: True)
    cfg = EmbeddingConfig(revision=REVISION)
    document = embedding.DocumentEncoder(cfg, settings)
    query = embedding.QueryEncoder(cfg, settings)
    assert document.model.options['device'] == 'cuda'
    assert document.model.options['model_kwargs']['torch_dtype'] == torch.bfloat16
    assert query.model.options['device'] == 'cpu'
    assert query.model.options['model_kwargs']['torch_dtype'] == torch.float32
    assert query.model.options['config_kwargs'] == {'vision_config': None, 'audio_config': None}
    assert 'cache_folder' not in query.model.options
    query.model.bad = True
    with pytest.raises(RagError, match='[Vv]ector'):
        query.encode('AC?')
    monkeypatch.setattr(torch.cuda, 'is_bf16_supported', lambda: False)
    with pytest.raises(RagError, match='BF16'):
        embedding.DocumentEncoder(cfg, settings)
