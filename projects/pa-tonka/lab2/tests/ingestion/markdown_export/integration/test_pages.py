"""Printed positions derived from the actual source book, not lookup targets."""

import re

import pytest

from dnd_rag.ingestion.markdown_export.rendering.engine import Engine
from helpers import payloads, walk, wrappers

pytestmark = pytest.mark.integration


def record(book, name, parent=None):
    return next(
        row
        for row in book.source_map
        if row['heading_path'][-1] == name
        and (parent is None or parent in row['heading_path'][:-1])
    )


def own_source_pages(node):
    return [
        child['page']
        for child in walk(node)
        if isinstance(child, dict)
        and type(child.get('page')) is int
        and not re.fullmatch(r'\{@\w+ [^{}]+\}', child.get('name', ''))
    ]


@pytest.mark.parametrize(
    ('book_id', 'name', 'expected'),
    [
        ('XPHB', 'Chapter 1: Playing the Game', [7, 31]),
        ('XPHB', 'Exploration', [19, 22]),
        ('XPHB', 'Conditions', [29, 31]),
        ('XDMG', 'Chapter 4: Creating Adventures', [105, 125]),
        ('XMM', 'Monster Lists', [374, 382]),
        ('XMM', 'Monster Conversions', [374]),
    ],
)
def test_book_ranges_follow_actual_own_source_nodes(
    book_id, name, expected, source_books, rendered
):
    node = next(
        n
        for n in walk(source_books[book_id]['chapters'])
        if isinstance(n, dict) and n.get('type') in ('section', 'entries') and n.get('name') == name
    )
    pages = own_source_pages(node)
    derived = [min(pages)] if min(pages) == max(pages) else [min(pages), max(pages)]
    assert derived == expected  # Documented examples of the pinned corpus.
    assert record(rendered[book_id], name)['printed_pages'] == derived


def test_reference_definitions_use_each_current_chapter_position(source_books, rendered):
    source, book = source_books['XPHB'], rendered['XPHB']
    chapter = next(c for c in source['chapters'] if c['title'] == 'Chapter 1: Playing the Game')
    definitions = [
        wrapper
        for wrapper in wrappers({'chapters': [chapter]})
        if wrapper['lookup']['prop'] in ('condition', 'hazard')
    ]
    assert definitions
    for wrapper in definitions:
        name = wrapper['data']['name']
        expected = wrapper['placement']['origin']['printed_page']
        row = record(book, name, chapter['title'])
        assert row['printed_pages'] == [expected]
        assert row['page_attribution'] == 'inherited_section_start'
        assert wrapper['entity_origin']['printed_page'] not in row['printed_pages']
        # The same definition can occur as its own entry in the glossary.
        other = [
            r
            for r in book.source_map
            if r['heading_path'][-1] == name and r['heading_path'][0] == 'Rules Glossary'
        ]
        if other:
            assert wrapper['entity_origin']['printed_page'] in other[0]['printed_pages']
    for name, maximum in [('Hazards', 22), ('Conditions', 31)]:
        for row in book.source_map:
            if name in row['heading_path'] and row['heading_path'][0] == chapter['title']:
                assert row['printed_pages'] and row['printed_pages'][-1] <= maximum


def test_class_overview_targets_are_not_placement_evidence(source_books):
    source = source_books['XPHB']
    engine = Engine(source)
    overview = [
        key
        for key, info in engine.domain.source.items()
        if isinstance(info['node'], dict) and info['node'].get('name', '').startswith('{@class ')
    ]
    assert overview
    chapter = next(c for c in source['chapters'] if c['title'] == 'Chapter 3: Character Classes')
    for key in overview:
        pages = engine.pages.sources[key]
        assert pages.page is None and pages.role == 'reference_target'
        assert pages.fallback == chapter['origin']['printed_page']


def test_full_classes_retain_local_native_pages_without_instrument_catalog_pages(
    source_books, rendered
):
    source, book = source_books['XPHB'], rendered['XPHB']
    classes = wrappers(source, 'class')
    following = next(
        c['origin']['printed_page']
        for c in source['chapters']
        if c['title'] == 'Chapter 4: Character Origins'
    )
    assert classes
    for index, wrapper in enumerate(classes):
        start = wrapper['entity_origin']['printed_page']
        limit = (
            classes[index + 1]['entity_origin']['printed_page']
            if index + 1 < len(classes)
            else following
        )
        row = record(book, wrapper['data']['name'], 'Chapter 3: Character Classes')
        assert row['printed_pages'][0] == start
        assert row['printed_pages'][-1] <= limit
        for child in book.source_map:
            if child['heading_path'][: len(row['heading_path'])] == row['heading_path']:
                assert (
                    child['printed_pages']
                    and start <= child['printed_pages'][0] <= child['printed_pages'][-1] <= limit
                )


@pytest.mark.parametrize(
    ('book_id', 'prop', 'name'),
    [
        ('XPHB', 'spell', 'Fireball'),
        ('XPHB', 'classFeature', 'Rage'),
        ('XMM', 'monster', 'Young Blue Dragon'),
    ],
)
def test_local_native_definition_pages_are_preserved(book_id, prop, name, source_books, rendered):
    data = next(p for p in payloads(source_books[book_id], prop) if p['name'] == name)
    title = 'Level 1: Rage' if prop == 'classFeature' else name
    row = record(rendered[book_id], title)
    assert data['page'] in row['printed_pages']
    assert row['page_attribution'] in ('explicit', 'partial')


def test_distant_treasure_origin_does_not_become_an_adventure_page(source_books, rendered):
    source, book = source_books['XDMG'], rendered['XDMG']
    chapter = next(c for c in source['chapters'] if c['title'] == 'Chapter 4: Creating Adventures')
    maximum = max(own_source_pages(chapter['content']))
    hoards = [
        e
        for e in source['domain']['entities']
        if e['prop'] == 'hoard'
        and e['representation'] == 'domain_component'
        and e['canonical_placement']['anchor']['chapter_index'] == chapter['chapter_index']
        and e['data_origin']['printed_page'] > maximum
    ]
    assert hoards
    for entity in hoards:
        anchor = entity['canonical_placement']['anchor']['origin']['json_pointer']
        node, owner = chapter['content'], None
        for token in anchor.removeprefix(chapter['origin']['json_pointer']).strip('/').split('/'):
            if isinstance(node, dict) and node.get('name'):
                owner = node['name']
            node = node[int(token)] if isinstance(node, list) else node[token]
        matches = [
            row
            for row in book.source_map
            if row['heading_path'][0] == chapter['title']
            and owner in row['heading_path'][:-1]
            and row['heading_path'][-1] == entity['data']['name']
        ]
        assert len(matches) == 1
        row = matches[0]
        assert row['printed_pages'] == [
            entity['canonical_placement']['anchor']['origin']['printed_page']
        ]
        assert row['page_attribution'] == 'inherited_section_start'


def test_original_inset_page_is_not_clamped_to_the_chapter_title(source_books, rendered):
    source, book = source_books['XMM'], rendered['XMM']
    chapter = source['chapters'][0]
    pages = own_source_pages(chapter['content'])
    assert min(pages) < chapter['origin']['printed_page']
    assert record(book, chapter['title'])['printed_pages'][0] == min(pages)
