"""Adapters around LangChain's token-measured splitters, preserving exact slices."""

from collections.abc import Callable

from langchain_text_splitters import MarkdownTextSplitter, RecursiveCharacterTextSplitter

from dnd_rag.config import ChunkingConfig
from dnd_rag.contracts import ChunkDraft, DraftMetadata, RagError
from dnd_rag.indexing.corpus import Book, CorpusSnapshot

TokenCounter = Callable[[str], int]


def primary_spans(book: Book, max_level: int) -> list[tuple[int, int]]:
    boundaries = sorted(
        {0, len(book.body), *(s.start for s in book.sections if s.level <= max_level)}
    )
    return list(zip(boundaries, boundaries[1:]))


def _exact_ranges(
    text: str, pieces: list[str], overlap: int, count_tokens: TokenCounter
) -> list[tuple[int, int]]:
    """Constrain matches by ordering, coverage and token overlap, never token→char arithmetic."""
    ranges = []
    previous_start, covered_end = -1, 0
    for piece in pieces:
        if not piece:
            continue
        candidates = []
        position = previous_start + 1
        while (start := text.find(piece, position, covered_end + len(piece))) >= 0:
            end = start + len(piece)
            if start > covered_end:
                break
            if end > covered_end and count_tokens(text[start:covered_end]) <= overlap:
                candidates.append((start, end))
            position = start + 1
        if len(candidates) != 1:
            raise RagError(
                'chunk_mapping',
                'Cannot map splitter output to one exact source slice',
                {
                    'covered_end': covered_end,
                    'candidate_count': len(candidates),
                    'preview': piece[:100],
                },
            )
        start, end = candidates[0]
        ranges.append((start, end))
        previous_start, covered_end = start, end
    if covered_end != len(text):
        raise RagError(
            'chunk_mapping',
            'Splitter did not preserve the entire input',
            {'covered_end': covered_end, 'input_length': len(text)},
        )
    return ranges


def _split_book(book: Book, config: ChunkingConfig, count_tokens: TokenCounter):
    cls = MarkdownTextSplitter if config.strategy == 'markdown' else RecursiveCharacterTextSplitter
    options = {
        'chunk_size': config.chunk_size,
        'chunk_overlap': config.chunk_overlap,
        'length_function': count_tokens,
        'keep_separator': True,
        'strip_whitespace': False,
    }
    if config.strategy == 'markdown':
        options['is_separator_regex'] = True
    splitter = cls(**options)
    spans = (
        primary_spans(book, config.max_heading_level)
        if config.strategy == 'source_map_recursive'
        else [(0, len(book.body))]
    )
    for left, right in spans:
        source = book.body[left:right]
        pieces = splitter.split_text(source)
        for start, end in _exact_ranges(source, pieces, config.chunk_overlap, count_tokens):
            yield left + start, left + end


def split_corpus(
    corpus: CorpusSnapshot, config: ChunkingConfig, count_tokens: TokenCounter
) -> list[ChunkDraft]:
    chunks = []
    for name, book in corpus.books.items():
        seen = set()
        for start, end in _split_book(book, config, count_tokens):
            if (start, end) in seen:
                continue
            seen.add((start, end))
            content = book.body[start:end]
            token_count = count_tokens(content)
            if token_count > config.chunk_size:
                raise RagError('chunk_too_long', f'{name}:{start}: {token_count} raw tokens')
            metadata = DraftMetadata(
                source_file=name,
                body_sha256=book.body_sha256,
                book_id=book.metadata['book_id'],
                book_title=book.metadata['title'],
                source_system=book.metadata['source'],
                upstream_sha=book.metadata['upstream_sha'],
                **book.coordinates(start, end),
                token_count=token_count,
                sections=book.attributions(start, end),
            )
            chunks.append(ChunkDraft(page_content=content, metadata=metadata))
    return chunks
