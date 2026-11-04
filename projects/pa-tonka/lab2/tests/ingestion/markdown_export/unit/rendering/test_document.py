import copy

import pytest

from dnd_rag.ingestion.markdown_export import ExportError
from dnd_rag.ingestion.markdown_export.rendering.document import Document
from dnd_rag.ingestion.markdown_export.rendering.inline import InlineRenderer
from helpers import check_document


def mapped_document():
    doc = Document('XMM', 'Test: "Book" — 🐉', 'abc123', InlineRenderer())
    doc.heading('Unknown 🐉', 1)
    doc.add('Café — e\u0301, 漢字.')
    doc.heading('Explicit [same]', 1, page=20)
    doc.add('Text.')
    doc.heading('Child', 2)
    doc.add('Inherited.')
    doc.heading('Explicit [same]', 1, page=30)
    doc.evidence(33, unknown=True)
    doc.add('Partial.')
    return doc.finish()


def test_yaml_unicode_and_exact_body_relative_map():
    markdown, body, records = mapped_document()
    check_document(markdown, body, records, 'XMM', 'Test: "Book" — 🐉', 'abc123')
    assert [(r['printed_pages'], r['page_attribution']) for r in records] == [
        (None, 'unknown'),
        ([20], 'partial'),
        ([20], 'inherited_section_start'),
        ([30, 33], 'partial'),
    ]
    # Two identical titles denote distinct coordinates, not a name lookup.
    assert records[1]['heading_path'] == records[3]['heading_path']
    assert records[1]['start_char'] != records[3]['start_char']
    assert records[1]['start_char'] != len(body[: records[1]['start_char']].encode('utf-8'))
    assert records[0]['start_char'] == 0 and records[0]['line_start'] == 1
    assert records[-1]['end_char'] == len(body)


def test_spell_links_in_headings_keep_plain_titles_and_body_relative_ranges():
    render = InlineRenderer()
    doc = Document('XPHB', 'Book', 'sha', render)
    doc.heading('Chapter', 1)
    doc.heading('{@b Spell {@spell Light|XPHB|{@i Lumen}}}', 2)
    doc.add(render('Cast {@spell Light|XPHB}.'))
    markdown, body, records = doc.finish()
    assert body == '# Chapter\n\n## Spell Lumen\n\nCast *Light*.\n'
    assert records[-1]['heading_path'] == ['Chapter', 'Spell Lumen']
    check_document(markdown, body, records, 'XPHB', 'Book', 'sha')


def test_explicit_page_range_propagates_to_parent():
    doc = Document('XPHB', 'Book', 'sha', InlineRenderer())
    doc.heading('Chapter', 1, page=2)
    doc.heading('Child', 2, page=4)
    doc.add('Text.')
    _, _, records = doc.finish()
    assert [(r['printed_pages'], r['page_attribution']) for r in records] == [
        ([2, 4], 'explicit'),
        ([4], 'explicit'),
    ]


def test_only_trusted_pages_aggregate_and_fallback_uses_the_stable_section_start():
    doc = Document('XPHB', 'Book', 'sha', InlineRenderer())
    doc.heading('Chapter', 1, page=5)
    doc.evidence(4)  # An actual source inset preceding the chapter title page.
    doc.heading('Inherited', 2)
    doc.add('Text.')
    doc.heading('Known Child', 2, page=9)
    doc.heading('Unlocated Child', 2, fallback=50)
    _, _, records = doc.finish()
    assert [(r['printed_pages'], r['page_attribution']) for r in records] == [
        ([4, 9], 'partial'),
        ([5], 'inherited_section_start'),
        ([9], 'explicit'),
        ([50], 'inherited_section_start'),
    ]


def test_unknown_parent_with_known_child_has_only_partial_evidence():
    doc = Document('XPHB', 'Book', 'sha', InlineRenderer())
    doc.heading('Unlocated Chapter', 1)
    doc.heading('Known Child', 2, page=15)
    _, _, records = doc.finish()
    assert (records[0]['printed_pages'], records[0]['page_attribution']) == ([15], 'partial')


@pytest.mark.parametrize(
    'damage', ['siblings', 'line', 'path', 'extra', 'byte_offset', 'gap', 'tail']
)
def test_independent_map_validator_rejects_corruption(damage):
    markdown, body, original = mapped_document()
    records = copy.deepcopy(original)
    if damage == 'siblings':
        records[0]['end_char'] = records[1]['end_char']
        records[0]['line_end'] = records[1]['line_end']
    elif damage == 'line':
        records[1]['line_start'] += 1
    elif damage == 'path':
        records[2]['heading_path'][0] = 'Wrong parent'
    elif damage == 'extra':
        records.append(records[-1])
    elif damage == 'byte_offset':
        records[1]['start_char'] = len(body[: records[1]['start_char']].encode('utf-8'))
    else:
        record = records[0] if damage == 'gap' else records[-1]
        record['line_end'] -= 1
        record['end_char'] = sum(
            len(line + '\n') for line in body.split('\n')[: record['line_end']]
        )
    with pytest.raises(AssertionError):
        check_document(markdown, body, records, 'XMM', 'Test: "Book" — 🐉', 'abc123')


def test_unicode_separators_are_content_not_lf_line_boundaries():
    doc = Document('XMM', 'Book', 'abc123', InlineRenderer())
    doc.heading('First', 1)
    doc.add('Line A\u2028Line B\u2029Line C\u0085Line D.')
    doc.heading('Second', 1)
    doc.add('Last paragraph.')
    markdown, body, records = doc.finish()
    check_document(markdown, body, records, 'XMM', 'Book', 'abc123')
    assert records[0]['line_start'] == 1 and records[0]['line_end'] == 4
    assert records[1]['line_start'] == 5


def test_skipping_heading_level_fails():
    doc = Document('XMM', 'Book', 'sha', InlineRenderer())
    doc.heading('Part', 1)
    with pytest.raises(ExportError, match='HEADING_DEPTH'):
        doc.heading('Missing parent', 3)


@pytest.mark.parametrize(
    'title', ['Title\u0085Part', 'Title\u0085🐉 Part', 'Title\u2028Part', 'Title\u2029Part']
)
def test_yaml_title_preserves_unicode_line_characters_and_emoji(title):
    doc = Document('XMM', title, 'abc123', InlineRenderer())
    doc.heading('Part', 1)
    doc.add('English book text.')
    markdown, body, records = doc.finish()
    check_document(markdown, body, records, 'XMM', title, 'abc123')
    if '\u0085' in title:
        assert '\\u0085' in markdown.split('\n---\n\n', 1)[0]
