"""Inspect rendered artifacts with independent YAML and Markdown parsers."""

import re

import yaml
from markdown_it import MarkdownIt

MARKDOWN = MarkdownIt('commonmark', {'html': False}).enable('table').enable('strikethrough')
ABILITIES = ('str', 'dex', 'con', 'int', 'wis', 'cha')


def plain(token):
    return ''.join(plain(child) for child in token.children) if token.children else token.content


def visible(text):
    return '\n'.join(plain(t) for t in MARKDOWN.parse(text) if t.type == 'inline')


def tables(text_or_tokens):
    tokens = MARKDOWN.parse(text_or_tokens) if isinstance(text_or_tokens, str) else text_or_tokens
    result, current, row = [], None, None
    for token in tokens:
        if token.type == 'table_open':
            current = []
        elif token.type == 'tr_open':
            row = []
        elif current is not None and token.type == 'inline':
            row.append(plain(token))
        elif token.type == 'tr_close':
            current.append(row)
        elif token.type == 'table_close':
            result.append(current)
            current = None
    return result


def blocks(text):
    tokens = MARKDOWN.parse(text)
    start, depth = None, 0
    for i, token in enumerate(tokens):
        if token.type == 'blockquote_open':
            if depth == 0:
                start = i
            depth += 1
        elif token.type == 'blockquote_close':
            depth -= 1
            if depth == 0:
                yield tokens[start : i + 1]


def walk(node):
    yield node
    if isinstance(node, dict):
        if node.get('kind') == 'embedded_entity':
            return  # Payloads are not independent source occurrences.
        for child in node.values():
            yield from walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from walk(child)


def _entry_strings(node, shared=(), path=''):
    """Read prose fields, excluding metadata and explicitly shared blocks."""
    if path in shared:
        return
    if isinstance(node, str):
        if node.strip():
            yield node
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _entry_strings(child, shared, path + '/' + str(index))
    elif isinstance(node, dict):
        for key in ('entries', 'entry', 'items', 'wrapped'):
            if key in node:
                yield from _entry_strings(node[key], shared, path + '/' + key)


def literal_paragraphs(node, shared=(), path=''):
    """Read complete untagged paragraphs without a production formatter."""
    return (text for text in _entry_strings(node, shared, path) if '{@' not in text)


def literal_fragments(node):
    """Read literal spans outside tags; tag semantics have separate unit tests."""
    for text in _entry_strings(node):
        for fragment in re.findall(r'(?:^|})([^{}]+)(?=\{@|$)', text):
            if fragment.strip():
                yield fragment.strip()


def wrappers(book, prop=None):
    return [
        n
        for n in walk(book['chapters'])
        if isinstance(n, dict)
        and n.get('kind') == 'embedded_entity'
        and (prop is None or n['lookup']['prop'] == prop)
    ]


def payloads(book, prop):
    return [w['data'] for w in wrappers(book, prop)] + [
        e['data']
        for e in book['domain']['entities']
        if e['representation'] == 'domain_component' and e['prop'] == prop
    ]


def section(book, name, *, ancestor=None):
    matches = [
        r
        for r in book.source_map
        if r['heading_path'][-1] == name
        and (ancestor is None or ancestor in r['heading_path'][:-1])
    ]
    assert matches, (book.book_id, name, ancestor)
    record = max(matches, key=lambda r: r['end_char'] - r['start_char'])
    return book.body[record['start_char'] : record['end_char']]


def check_document(markdown, body, records, book_id, title, sha):
    """Assert the public contract against a YAML parser and a Markdown AST."""
    assert markdown.startswith('---\n') and '\r' not in markdown
    prefix, extracted = markdown[4:].split('\n---\n\n', 1)
    assert extracted == body and body.startswith('# ') and body.endswith('\n')
    assert '\n---\n' not in body  # Statblock separators are quoted.
    assert yaml.safe_load(prefix) == {
        'book_id': book_id,
        'title': title,
        'source': '5etools',
        'upstream_sha': sha,
    }
    tokens = MARKDOWN.parse(body)
    headings = [(i, t) for i, t in enumerate(tokens) if t.type == 'heading_open']
    assert len(headings) == len(records)
    lines, offsets = [line + '\n' for line in body.split('\n')[:-1]], [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    stack = []
    for (i, token), record in zip(headings, records, strict=True):
        depth = int(token.tag[1:])
        assert set(record) == {
            'book_id',
            'file',
            'heading_path',
            'line_start',
            'line_end',
            'start_char',
            'end_char',
            'printed_pages',
            'page_attribution',
        }
        assert record['book_id'] == book_id and record['file'] == book_id.lower() + '.md'
        assert depth == len(record['heading_path'])
        assert plain(tokens[i + 1]) == record['heading_path'][-1]
        assert record['line_start'] == token.map[0] + 1
        assert 1 <= record['line_start'] <= record['line_end'] <= len(lines)
        start, end = record['start_char'], record['end_char']
        assert 0 <= start < end <= len(body)
        assert start == offsets[record['line_start'] - 1] and end == offsets[record['line_end']]
        assert body[start:end] == ''.join(lines[record['line_start'] - 1 : record['line_end']])
        assert body[start:end].endswith('\n')
        while stack and len(stack[-1]['heading_path']) >= depth:
            previous = stack.pop()
            assert previous['end_char'] == start
        if stack:
            assert record['heading_path'][:-1] == stack[-1]['heading_path']
            assert end <= stack[-1]['end_char']
        else:
            assert depth == 1
        stack.append(record)
        pages, attribution = record['printed_pages'], record['page_attribution']
        assert attribution in {'explicit', 'partial', 'inherited_section_start', 'unknown'}
        if attribution == 'unknown':
            assert pages is None
        else:
            assert (
                isinstance(pages, list)
                and len(pages) in (1, 2)
                and all(type(p) is int for p in pages)
            )
            assert pages == sorted(set(pages))
            if attribution == 'inherited_section_start':
                assert len(pages) == 1
    assert all(record['end_char'] == len(body) for record in stack)
    nesting = []
    for token in tokens:
        if token.nesting == 1:
            nesting.append(token.type.removesuffix('_open'))
        elif token.nesting == -1:
            assert nesting.pop() == token.type.removesuffix('_close')
        assert token.type != 'image'
        assert not any(child.type == 'image' for child in token.children or [])
    assert not nesting
    assert not any(t.type in {'fence', 'code_block', 'html_block'} for t in tokens)
    return tokens
