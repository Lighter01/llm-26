"""Read canonical Markdown bodies and resolve exact, body-relative quotations."""

import json
import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

BOOK_FILES = ('xphb.md', 'xdmg.md', 'xmm.md')


@dataclass
class Book:
    body: str
    line_starts: list[int]
    body_sha256: str

    def coordinates(self, start: int, end: int) -> dict:
        if not (type(start) is int and type(end) is int and 0 <= start < end <= len(self.body)):
            raise ValueError('Expected a nonempty character range inside the Markdown body')
        return {
            'line_start': bisect_right(self.line_starts, start),
            'line_end': bisect_right(self.line_starts, end - 1),
            'start_char': start,
            'end_char': end,
        }


@dataclass
class Corpus:
    files: dict[str, Book]
    sections: dict[tuple[str, tuple[str, ...]], list[dict]]
    source_map_sha256: str | None


def _read_book(path: Path) -> Book:
    text = path.read_bytes().decode('utf-8')
    if '\r' in text:
        raise ValueError('The Markdown corpus must use LF line endings')
    if not text.startswith('---\n'):
        raise ValueError('Missing YAML front matter opening delimiter')
    closing = text.find('\n---\n', 3)
    if closing < 0:
        raise ValueError('Missing YAML front matter closing delimiter')
    separator = closing + len('\n---\n')
    if text[separator : separator + 1] != '\n':
        raise ValueError('Expected one blank separator after YAML front matter')
    # Remove exactly one separator, preserving all subsequent body characters.
    body = text[separator + 1 :]
    if not body.strip():
        raise ValueError('The Markdown body is empty')
    return Book(
        body,
        [0] + [match.end() for match in re.finditer('\n', body)],
        sha256(body.encode('utf-8')).hexdigest(),
    )


def _section(record: object, files: dict[str, Book]) -> tuple[str, tuple[str, ...]]:
    if not isinstance(record, dict):
        raise ValueError('Expected a source-map object')
    filename, path = record.get('file'), record.get('heading_path')
    if not isinstance(filename, str) or filename not in BOOK_FILES:
        raise ValueError('Unknown source-map file; expected xphb.md, xdmg.md or xmm.md')
    if not (
        isinstance(path, list)
        and path
        and all(isinstance(title, str) and title.strip() for title in path)
    ):
        raise ValueError('heading_path must be a nonempty list of nonempty strings')
    for field in ('start_char', 'end_char', 'line_start', 'line_end'):
        if type(record.get(field)) is not int:
            raise ValueError(f'{field} must be an integer')
    if not (
        0 <= record['start_char'] < record['end_char']
        and 1 <= record['line_start'] <= record['line_end']
    ):
        raise ValueError('Invalid source-map character or line range')
    if filename in files:
        actual = files[filename].coordinates(record['start_char'], record['end_char'])
        if any(actual[field] != record[field] for field in actual):
            raise ValueError('Source-map line range disagrees with its character range')
    return filename, tuple(path)


def load_corpus(directory: Path, errors: list[dict]) -> Corpus:
    """Collect independent corpus errors instead of stopping at the first bad file."""
    files = {}
    for filename in BOOK_FILES:
        try:
            files[filename] = _read_book(directory / filename)
        except (OSError, UnicodeError, ValueError) as error:
            errors.append({'code': 'CORPUS_BOOK', 'message': str(error), 'file': filename})

    source_map_sha256 = None
    sections = defaultdict(list)
    try:
        raw = (directory / 'source_map.jsonl').read_bytes()
        source_map_sha256 = sha256(raw).hexdigest()
        text = raw.decode('utf-8')
    except (OSError, UnicodeError) as error:
        errors.append({'code': 'CORPUS_MAP', 'message': str(error), 'file': 'source_map.jsonl'})
    else:
        lines = text.split('\n')
        for number, line in enumerate(lines, 1):
            # A single final LF is normal JSONL; blank records elsewhere are invalid.
            if not line and number == len(lines):
                continue
            try:
                record = json.loads(line)
                key = _section(record, files)
                sections[key].append(record)
            except (ValueError, TypeError, RecursionError) as error:
                errors.append(
                    {
                        'code': 'CORPUS_MAP_RECORD',
                        'message': str(error),
                        'file': 'source_map.jsonl',
                        'source_map_line': number,
                    }
                )
        mapped = {filename for filename, _ in sections}
        for filename in files:
            if filename not in mapped:
                errors.append(
                    {
                        'code': 'CORPUS_MAP_MISSING',
                        'message': 'No valid source-map sections for this book',
                        'file': filename,
                    }
                )
    return Corpus(files, dict(sections), source_map_sha256)


def find_candidates(
    corpus: Corpus, filename: str, heading_path: list[str], quote: str
) -> list[dict]:
    """Find all distinct exact occurrences wholly contained in a mapped section."""
    if not quote or not quote.strip():
        raise ValueError('The quotation must not be empty or whitespace-only')
    book = corpus.files[filename]
    ranges = corpus.sections.get((filename, tuple(heading_path)), ())
    matches = {}
    for section in ranges:
        position = section['start_char']
        while (start := book.body.find(quote, position, section['end_char'])) >= 0:
            end = start + len(quote)
            coordinates = book.coordinates(start, end)
            if not (
                section['start_char'] <= start < end <= section['end_char']
                and section['line_start'] <= coordinates['line_start']
                and coordinates['line_end'] <= section['line_end']
                and book.body[start:end] == quote
            ):
                raise ValueError('Quotation coordinates disagree with its mapped section')
            matches[start, end] = coordinates
            position = start + 1  # Include overlapping occurrences.
    return [matches[key] for key in sorted(matches)]
