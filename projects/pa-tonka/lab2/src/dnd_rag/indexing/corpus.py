"""Canonical books, validated nested map, and non-overlapping section ownership."""

import json
import re
from bisect import bisect_right
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import yaml
from markdown_it import MarkdownIt
from pydantic import ValidationError

from dnd_rag.config import UniqueKeyLoader
from dnd_rag.contracts import RagError, SectionAttribution

BOOK_FILES = ('xphb.md', 'xdmg.md', 'xmm.md')


@dataclass(frozen=True)
class Section:
    attribution: SectionAttribution
    level: int
    heading_end: int

    @property
    def start(self):
        return self.attribution.section_start_char

    @property
    def end(self):
        return self.attribution.section_end_char


@dataclass(frozen=True)
class Book:
    source_file: str
    body: str
    metadata: dict
    body_sha256: str
    line_starts: list[int]
    sections: list[Section]
    # Sorted disjoint intervals of each section's own content, not ancestors.
    ownership: list[tuple[int, int, Section]]
    ownership_starts: list[int]

    def coordinates(self, start: int, end: int) -> dict:
        if not (type(start) is int and type(end) is int and 0 <= start < end <= len(self.body)):
            raise ValueError(f'{self.source_file}: invalid body range [{start}, {end})')
        return {
            'start_char': start,
            'end_char': end,
            'line_start': bisect_right(self.line_starts, start),
            'line_end': bisect_right(self.line_starts, end - 1),
        }

    def attributions(self, start: int, end: int) -> list[SectionAttribution]:
        first = max(0, bisect_right(self.ownership_starts, start) - 1)
        result, seen = [], set()
        for left, right, section in self.ownership[first:]:
            if left >= end:
                break
            if right > start and section.start not in seen:
                seen.add(section.start)
                result.append(section.attribution)
        return result


@dataclass(frozen=True)
class CorpusSnapshot:
    books: dict[str, Book]
    source_map_sha256: str

    def passport(self) -> dict:
        return {
            'files': {name: {'body_sha256': book.body_sha256} for name, book in self.books.items()},
            'source_map_sha256': self.source_map_sha256,
        }


def _read_book(path: Path) -> Book:
    text = path.read_bytes().decode('utf-8')
    if '\r' in text or not text.startswith('---\n'):
        raise ValueError(f'{path.name}: expected UTF-8 LF Markdown with YAML front matter')
    closing = text.find('\n---\n', 3)
    if closing < 0 or text[closing + 5 : closing + 6] != '\n':
        raise ValueError(f'{path.name}: expected YAML closing delimiter and one blank separator')
    metadata = yaml.load(text[4:closing], Loader=UniqueKeyLoader)
    if not isinstance(metadata, dict) or any(
        not isinstance(metadata.get(key), str) or not metadata[key]
        for key in ('book_id', 'title', 'source', 'upstream_sha')
    ):
        raise ValueError(f'{path.name}: missing book metadata')
    body = text[closing + 6 :]
    if not body.strip():
        raise ValueError(f'{path.name}: empty body')
    return Book(
        path.name,
        body,
        metadata,
        sha256(body.encode()).hexdigest(),
        [0] + [match.end() for match in re.finditer('\n', body)],
        [],
        [],
        [],
    )


def _heading_ranges(book: Book) -> dict[int, tuple[int, int]]:
    headings = {}
    for token in MarkdownIt().parse(book.body):
        if token.type == 'heading_open' and token.map:
            first, last = token.map
            start = book.line_starts[first]
            end = book.line_starts[last] if last < len(book.line_starts) else len(book.body)
            # Source-map headings are ATX H1–H6. Setext titles are not exported.
            if re.match(r'#{1,6} ', book.body[start:end]):
                headings[start] = (int(token.tag[1]), end)
    return headings


def _load_sections(book: Book, records: list[dict]) -> None:
    headings = _heading_ranges(book)
    for record in records:
        if record.get('book_id') != book.metadata['book_id']:
            raise ValueError(f'{book.source_file}: source-map book_id mismatch')
        start, end = record['start_char'], record['end_char']
        actual = book.coordinates(start, end)
        if any(actual[key] != record[key] for key in actual):
            raise ValueError(f'{book.source_file}: source-map line/char disagreement')
        if start not in headings:
            raise ValueError(f'{book.source_file}:{start}: mapped heading is not a real H1–H6')
        path = record['heading_path']
        if not path or any(not isinstance(s, str) or not s.strip() for s in path):
            raise ValueError('Invalid heading_path')
        pages = record['printed_pages']
        if pages is not None and (
            len(pages) not in (1, 2) or any(type(p) is not int or p < 1 for p in pages)
        ):
            raise ValueError('Invalid printed_pages')
        attribution = SectionAttribution(
            heading_path=path,
            section_start_char=start,
            section_end_char=end,
            printed_pages=pages,
            page_attribution=record['page_attribution'],
        )
        level, heading_end = headings[start]
        book.sections.append(Section(attribution, level, heading_end))
    book.sections.sort(key=lambda s: (s.start, -s.end))
    if not book.sections:
        raise ValueError(f'{book.source_file}: missing source-map sections')
    stack, cursors, seen = [], {}, set()
    for section in book.sections:
        if section.start in seen:
            raise ValueError('Duplicate source-map start')
        seen.add(section.start)
        while stack and section.start >= stack[-1].end:
            parent = stack.pop()
            if cursors[parent.start] < parent.end:
                book.ownership.append((cursors[parent.start], parent.end, parent))
        if stack:
            parent = stack[-1]
            if section.end > parent.end:
                raise ValueError('Crossing source-map ranges')
            if cursors[parent.start] < section.start:
                book.ownership.append((cursors[parent.start], section.start, parent))
            cursors[parent.start] = section.end
        stack.append(section)
        cursors[section.start] = section.start
    for parent in stack:
        if cursors[parent.start] < parent.end:
            book.ownership.append((cursors[parent.start], parent.end, parent))
    book.ownership.sort(key=lambda span: span[0])
    book.ownership_starts.extend(left for left, _, _ in book.ownership)


def load_corpus(directory: Path) -> CorpusSnapshot:
    try:
        books = {name: _read_book(directory / name) for name in BOOK_FILES}
        raw = (directory / 'source_map.jsonl').read_bytes()
        records = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
        if any(not isinstance(r, dict) or r.get('file') not in books for r in records):
            raise ValueError('Unknown source-map file or malformed record')
        for name, book in books.items():
            _load_sections(book, [r for r in records if r['file'] == name])
        return CorpusSnapshot(books, sha256(raw).hexdigest())
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, ValidationError) as exc:
        raise RagError('invalid_corpus', f'{directory}: {exc}') from exc
