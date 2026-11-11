"""Validation of emitted artifacts and exact body-relative heading ranges."""

import copy
import json
from dataclasses import replace

import pytest

from dnd_rag.ingestion.markdown_export import ExportError, export_build, render_build
from dnd_rag.ingestion.markdown_export.publication.validation import validate_corpus
from helpers import change_book


@pytest.mark.parametrize('separator', ['\u2028', '\u2029', '\x85'])
def test_unicode_separators_are_characters_in_lf_coordinates(build, tmp_path, separator):
    def add_section(book):
        book['chapters'][0]['content']['entries'].append(
            {
                'type': 'section',
                'name': 'One' + separator + 'Two',
                'entries': ['Alpha' + separator + 'Beta.'],
            }
        )

    change_book(build, add_section)
    result = export_build(build, tmp_path / 'output')
    book = result.corpus.books[0]
    record = book.source_map[-1]
    assert separator in record['heading_path'][-1]
    assert record['line_start'] == book.body[: record['start_char']].count('\n') + 1
    assert record['line_end'] == book.body[: record['end_char']].count('\n')
    assert record['end_char'] == len(book.body)


@pytest.mark.parametrize('section_kind', ['only_root', 'last_child', 'before_sibling'])
def test_map_ranges_must_cover_entire_sections(build, section_kind):
    if section_kind != 'only_root':

        def add_sections(book):
            book['chapters'][0]['content']['entries'].extend(
                [
                    {
                        'type': 'section',
                        'name': 'First child',
                        'entries': ['Complete first child prose.'],
                    },
                    {
                        'type': 'section',
                        'name': 'Last child',
                        'entries': ['Complete last child prose.'],
                    },
                ]
            )

        change_book(build, add_sections)
    corpus = copy.deepcopy(render_build(build))
    book = corpus.books[0]
    record = (
        book.source_map[0]
        if section_kind == 'only_root'
        else book.source_map[1 if section_kind == 'before_sibling' else -1]
    )
    end = book.body.index('\n', record['start_char']) + 1
    record.update(end_char=end, line_end=record['line_start'])
    corpus.files['source_map.jsonl'] = ''.join(
        json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n'
        for rendered in corpus.books
        for r in rendered.source_map
    ).encode('utf-8')
    with pytest.raises(ExportError, match='INVALID_OUTPUT'):
        validate_corpus(corpus)


@pytest.mark.parametrize(
    'damage', ['files', 'utf8', 'frontmatter', 'invalid_yaml', 'tag', 'map', 'sibling', 'jsonl']
)
def test_publication_validation_rejects_bad_corpus(build, damage):
    if damage == 'sibling':

        def another_part(book):
            chapter = copy.deepcopy(book['chapters'][0])
            chapter.update(chapter_index=1, title='Second Part')
            book['chapters'].append(chapter)

        change_book(build, another_part)
    corpus = copy.deepcopy(render_build(build))
    first = corpus.books[0]
    if damage == 'files':
        corpus.files['unexpected.json'] = b'{}\n'
    elif damage == 'utf8':
        corpus.files['xphb.md'] = b'\xff\n'
    elif damage in ('frontmatter', 'invalid_yaml'):
        bad = (
            first.markdown.replace('source: "5etools"', 'export_version: "1"')
            if damage == 'frontmatter'
            else first.markdown.replace('title: ', 'title: [')
        )
        corpus = replace(corpus, books=(replace(first, markdown=bad), *corpus.books[1:]))
        corpus.files['xphb.md'] = bad.encode('utf-8')
    elif damage == 'tag':
        bad_body = first.body + '{@future lost}\n'
        bad = first.markdown[: -len(first.body)] + bad_body
        corpus = replace(
            corpus, books=(replace(first, markdown=bad, body=bad_body), *corpus.books[1:])
        )
        corpus.files['xphb.md'] = bad.encode('utf-8')
    elif damage == 'map':
        first.source_map[0]['start_char'] += 1
    elif damage == 'sibling':
        first.source_map[0]['end_char'] = first.source_map[1]['end_char']
        first.source_map[0]['line_end'] = first.source_map[1]['line_end']
    else:
        corpus.files['source_map.jsonl'] = b'{}\n'
    with pytest.raises(ExportError, match='INVALID_OUTPUT'):
        validate_corpus(corpus)
