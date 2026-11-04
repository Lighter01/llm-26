"""Render a resolved book or explicit build without filesystem publication."""

import json
from pathlib import Path

from .common.model import BOOK_IDS, ExportError, RenderedBook, RenderedCorpus, require
from .publication.inputs import read_build
from .rendering.engine import Engine


def render_book(book: dict) -> RenderedBook:
    engine = None
    book_id = None
    try:
        require(isinstance(book, dict), 'INVALID_PAYLOAD', 'Expected a resolved-book object')
        require(
            book.get('schema_version') == '1.0.0',
            'UNSUPPORTED_SCHEMA',
            str(book.get('schema_version')),
        )
        scope = book.get('scope')
        require(
            book.get('artifact_kind') == 'resolved_book'
            and isinstance(scope, dict)
            and all(
                scope.get(key) is True
                for key in (
                    'all_source_chapters',
                    'embedded_references_resolved',
                    'domain_enrichment',
                    'book_complete',
                )
            ),
            'INCOMPLETE_BOOK',
            'Expected a complete resolved book',
        )
        metadata = book.get('book')
        require(
            isinstance(metadata, dict) and metadata.get('id') in BOOK_IDS,
            'BOOK_ID',
            'Unknown core book',
        )
        book_id = metadata['id']
        chapters = book.get('chapters')
        require(
            isinstance(chapters, list)
            and bool(chapters)
            and all(isinstance(c, dict) for c in chapters),
            'CHAPTERS',
            'Expected nonempty chapter objects',
            book=book_id,
        )
        require(
            all(
                type(chapter.get('chapter_index')) is int and chapter['chapter_index'] == index
                for index, chapter in enumerate(chapters)
            ),
            'CHAPTER_ORDER',
            'Chapter indices differ from their order',
            book=book_id,
        )
        engine = Engine(book)
        return engine.render()
    except ExportError:
        raise
    except (KeyError, TypeError, IndexError, AttributeError, ValueError) as error:
        raise ExportError(
            'INVALID_PAYLOAD', str(error), **(engine.context() if engine else {'book': book_id})
        ) from error


def render_build(directory: str | Path) -> RenderedCorpus:
    books = tuple(render_book(book) for book in read_build(directory))
    files = {book.book_id.lower() + '.md': book.markdown.encode('utf-8') for book in books}
    files['source_map.jsonl'] = ''.join(
        json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n'
        for book in books
        for record in book.source_map
    ).encode('utf-8')
    return RenderedCorpus(files, books)
