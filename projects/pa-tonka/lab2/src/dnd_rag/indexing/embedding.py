"""Text-only EG2 adapters; model imports and GPU allocation are explicit."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from time import perf_counter

import numpy as np

from dnd_rag.config import EmbeddingConfig, RuntimeSettings
from dnd_rag.contracts import ChunkDraft, RagError
from dnd_rag.indexing.corpus import CorpusSnapshot


def load_token_counter(config: EmbeddingConfig, cache_dir=None):
    from transformers import AutoTokenizer

    kwargs = {'revision': config.revision}
    if cache_dir is not None:
        kwargs['cache_dir'] = str(cache_dir)
    tokenizer = AutoTokenizer.from_pretrained(config.model_id, **kwargs)
    return lambda text: len(tokenizer.encode(text, add_special_tokens=False, truncation=False))


def prepare_embedding_text(chunk, corpus: CorpusSnapshot, config: EmbeddingConfig) -> str:
    meta = chunk.metadata
    content = chunk.page_content
    if config.strip_markdown_headings:
        book = corpus.books[meta.source_file]
        removed = sorted(
            (max(meta.start_char, s.start), min(meta.end_char, s.heading_end))
            for s in book.sections
            if s.start < meta.end_char and s.heading_end > meta.start_char
        )
        parts, cursor = [], meta.start_char
        for left, right in removed:
            parts.append(content[cursor - meta.start_char : left - meta.start_char])
            cursor = right
        parts.append(content[cursor - meta.start_char :])
        content = ''.join(parts)
    title = 'none'
    if config.include_title:
        paths = list(dict.fromkeys(' > '.join(s.heading_path) for s in meta.sections))
        title = meta.book_title + (' — ' + '; '.join(paths) if paths else '')
    return f'title: {title} | text: {content}'


def _sentence_transformer_class():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer


def _load_model(config: EmbeddingConfig, settings: RuntimeSettings, *, document: bool):
    import torch

    if document and not torch.cuda.is_available():
        raise RagError('gpu_unavailable', 'Document encoding requires a CUDA GPU')
    if document and config.document_dtype == 'bfloat16' and not torch.cuda.is_bf16_supported():
        raise RagError('unsupported_dtype', 'Selected BF16 is not supported by this GPU')
    dtype = torch.bfloat16 if document and config.document_dtype == 'bfloat16' else torch.float32
    options = {
        'revision': config.revision,
        'device': 'cuda' if document else 'cpu',
        'config_kwargs': {'vision_config': None, 'audio_config': None},
        'model_kwargs': {'torch_dtype': dtype},
    }
    if settings.embedding_cache_dir is not None:
        options['cache_folder'] = str(settings.embedding_cache_dir)
    return _sentence_transformer_class()(config.model_id, **options)


def _check_input(model, text: str, source: str):
    tokens = len(model.tokenizer.encode(text, add_special_tokens=True, truncation=False))
    limit = min(8192, model.max_seq_length)
    if tokens > limit:
        raise RagError(
            'embedding_input_too_long', f'Input {source} has {tokens} tokens; limit is {limit}'
        )


def _vectors(values, count: int, dimension: int) -> list[list[float]]:
    vectors = np.asarray(values, dtype=np.float32)
    if vectors.shape != (count, dimension) or not np.isfinite(vectors).all():
        raise RagError(
            'invalid_vector',
            'Vector shape or finite-value validation failed',
            {'shape': list(vectors.shape), 'expected': [count, dimension]},
        )
    return vectors.tolist()


@dataclass(frozen=True)
class EmbeddedBatch:
    chunks: Sequence[ChunkDraft]
    vectors: list[list[float]]
    embedding_elapsed_ms: float


class DocumentEncoder:
    def __init__(self, config: EmbeddingConfig, settings: RuntimeSettings):
        self.config = config
        self.model = _load_model(config, settings, document=True)

    def iter_batches(self, chunks: Sequence, corpus: CorpusSnapshot) -> Iterator[EmbeddedBatch]:
        for start in range(0, len(chunks), self.config.document_batch_size):
            selected = chunks[start : start + self.config.document_batch_size]
            texts = [prepare_embedding_text(chunk, corpus, self.config) for chunk in selected]
            for chunk, text in zip(selected, texts):
                _check_input(
                    self.model, text, f'{chunk.metadata.source_file}:{chunk.metadata.start_char}'
                )
            before = perf_counter()
            values = self.model.encode(
                texts,
                prompt='',
                batch_size=len(selected),
                truncate_dim=self.config.dimension,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            vectors = _vectors(values, len(selected), self.config.dimension)
            yield EmbeddedBatch(selected, vectors, (perf_counter() - before) * 1000)


class QueryEncoder:
    def __init__(self, config: EmbeddingConfig, settings: RuntimeSettings):
        self.config = config
        self.model = _load_model(config, settings, document=False)
        if config.query_prompt_name not in self.model.prompts:
            raise RagError('unsupported_prompt', f'Missing query prompt {config.query_prompt_name}')

    def encode(self, question: str) -> list[float]:
        if not isinstance(question, str) or not question.strip():
            raise RagError('invalid_question', 'Question must be nonempty text')
        _check_input(
            self.model, self.model.prompts[self.config.query_prompt_name] + question, 'question'
        )
        values = self.model.encode(
            question,
            prompt_name=self.config.query_prompt_name,
            truncate_dim=self.config.dimension,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return _vectors(np.asarray(values)[None, :], 1, self.config.dimension)[0]
