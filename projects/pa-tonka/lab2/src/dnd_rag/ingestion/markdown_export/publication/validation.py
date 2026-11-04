"""Publication gate for the four UTF-8 artifacts; stdlib only.

The test suite additionally uses independent YAML and CommonMark parsers.
Here the intentionally narrow emitted format is checked without dependencies.
"""

import re

from ..common.json_io import strict_json
from ..common.model import ARTIFACTS, BOOK_IDS, ExportError, require
from ..rendering.inline import InlineRenderer

MAP_FIELDS = frozenset(
    (
        'book_id',
        'file',
        'heading_path',
        'line_start',
        'line_end',
        'start_char',
        'end_char',
        'printed_pages',
        'page_attribution',
    )
)


def _validate(corpus):
    require(
        set(corpus.files) == ARTIFACTS,
        'INVALID_OUTPUT',
        'Expected exactly three Markdown books and source_map.jsonl',
    )
    require(
        len(corpus.books) == 3 and {b.book_id for b in corpus.books} == set(BOOK_IDS),
        'INVALID_OUTPUT',
        'Expected each core book exactly once',
    )
    for name, raw in corpus.files.items():
        require(
            type(raw) is bytes
            and bool(raw)
            and raw.endswith(b'\n')
            and b'\r' not in raw
            and b'\0' not in raw,
            'INVALID_OUTPUT',
            'Expected nonempty UTF-8 with LF',
            file=name,
        )
        raw.decode('utf-8')
    snapshots, combined = set(), []
    inline = InlineRenderer()
    for book in corpus.books:
        context = {'book': book.book_id}
        require(
            corpus.files[book.book_id.lower() + '.md'].decode('utf-8') == book.markdown,
            'INVALID_OUTPUT',
            'Book object differs from emitted bytes',
            **context,
        )
        require(
            book.markdown.startswith('---\n'), 'INVALID_OUTPUT', 'Missing YAML prefix', **context
        )
        prefix, body = book.markdown[4:].split('\n---\n\n', 1)
        metadata = {}
        for line in prefix.split('\n'):
            key, separator, value = line.partition(': ')
            require(
                separator and key not in metadata,
                'INVALID_OUTPUT',
                'Invalid or duplicate metadata',
                **context,
            )
            require(
                key == 'book_id' or value.startswith('"'),
                'INVALID_OUTPUT',
                'Expected the emitted JSON-quoted YAML string format',
                **context,
            )
            metadata[key] = strict_json(value) if value.startswith('"') else value
        require(
            set(metadata) == {'book_id', 'title', 'source', 'upstream_sha'}
            and metadata['book_id'] == book.book_id
            and metadata['source'] == '5etools'
            and isinstance(metadata['title'], str)
            and bool(metadata['title'].strip())
            and isinstance(metadata['upstream_sha'], str)
            and re.fullmatch('[0-9a-f]{40}', metadata['upstream_sha']),
            'INVALID_OUTPUT',
            'Invalid book metadata',
            **context,
        )
        snapshots.add(metadata['upstream_sha'])
        require(
            body == book.body and body.startswith('# ') and '\n---\n' not in body,
            'INVALID_OUTPUT',
            'Body or front matter boundary differs',
            **context,
        )
        require(
            not any(
                t in body
                for t in (
                    '{@',
                    '{#',
                    '{{',
                    '![',
                    '__prop',
                    'json_pointer',
                    '[object Object]',
                    'undefined',
                    'summonSpellLevel',
                )
            )
            and not re.search(r'\b(?:entity|record):[A-Za-z%]', body),
            'INVALID_OUTPUT',
            'Active markup or technical artifacts remain',
            **context,
        )
        # The external coordinate contract counts LF, not every Unicode character
        # which str.splitlines() treats as a line separator.
        lines, offsets, headings = [line + '\n' for line in body.split('\n')[:-1]], [0], []
        for index, line in enumerate(lines):
            if re.match(r'^#{1,6} ', line):
                headings.append(index)
            offsets.append(offsets[-1] + len(line))
        require(
            len(headings) == len(book.source_map) and bool(headings),
            'INVALID_OUTPUT',
            'Heading/map count differs',
            **context,
        )
        stack = []
        for index, record in zip(headings, book.source_map, strict=True):
            require(
                set(record) == MAP_FIELDS
                and record['book_id'] == book.book_id
                and record['file'] == book.book_id.lower() + '.md',
                'INVALID_OUTPUT',
                'Invalid map record fields',
                **context,
            )
            path = record['heading_path']
            require(
                isinstance(path, list)
                and 1 <= len(path) <= 6
                and all(isinstance(p, str) and p.strip() for p in path),
                'INVALID_OUTPUT',
                'Invalid heading path',
                **context,
            )
            require(
                lines[index].rstrip('\n') == '#' * len(path) + ' ' + inline(path[-1]),
                'INVALID_OUTPUT',
                'Map does not identify the actual heading',
                **context,
            )
            start, end, first, last = (
                record[k] for k in ('start_char', 'end_char', 'line_start', 'line_end')
            )
            require(
                all(type(v) is int for v in (start, end, first, last))
                and first == index + 1
                and 1 <= first <= last <= len(lines)
                and start == offsets[index]
                and end == offsets[last]
                and start < end,
                'INVALID_OUTPUT',
                'Invalid body-relative line/character range',
                **context,
            )
            while stack and len(stack[-1]['heading_path']) >= len(path):
                require(
                    stack.pop()['end_char'] == start,
                    'INVALID_OUTPUT',
                    'Section does not end at its next sibling/ancestor heading',
                    **context,
                )
            require(
                (stack and path[:-1] == stack[-1]['heading_path'] and end <= stack[-1]['end_char'])
                or (not stack and len(path) == 1),
                'INVALID_OUTPUT',
                'Invalid section nesting',
                **context,
            )
            stack.append(record)
            pages, attribution = record['printed_pages'], record['page_attribution']
            require(
                attribution in {'explicit', 'partial', 'inherited_section_start', 'unknown'},
                'INVALID_OUTPUT',
                'Unknown page attribution',
                **context,
            )
            require(
                (pages is None and attribution == 'unknown')
                or (
                    isinstance(pages, list)
                    and len(pages) in (1, 2)
                    and all(type(p) is int and p >= 0 for p in pages)
                    and pages == sorted(set(pages))
                    and attribution != 'unknown'
                    and (attribution != 'inherited_section_start' or len(pages) == 1)
                ),
                'INVALID_OUTPUT',
                'Invalid printed-page evidence',
                **context,
            )
        require(
            all(record['end_char'] == len(body) for record in stack),
            'INVALID_OUTPUT',
            'Final section ranges omit the end of the body',
            **context,
        )
        require(
            sum(len(r['heading_path']) == 1 for r in book.source_map)
            == book.diagnostics.counts['chapters'],
            'INVALID_OUTPUT',
            'Missing top-level book parts',
            **context,
        )
        combined.extend(book.source_map)
    require(len(snapshots) == 1, 'INVALID_OUTPUT', 'Output mixes snapshots')
    actual = [
        strict_json(line)
        for line in corpus.files['source_map.jsonl'].decode('utf-8').split('\n')[:-1]
    ]
    require(actual == combined, 'INVALID_OUTPUT', 'JSONL differs from book maps or manifest order')
    return snapshots.pop()


def validate_corpus(corpus):
    """Validate without changing the corpus; return its common upstream SHA."""
    try:
        return _validate(corpus)
    except ExportError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
        raise ExportError('INVALID_OUTPUT', str(error)) from error
