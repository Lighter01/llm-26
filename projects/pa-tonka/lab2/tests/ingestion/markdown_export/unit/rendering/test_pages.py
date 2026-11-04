"""Placement, reference origins and exact versus inherited page evidence."""

import copy

import pytest

from dnd_rag.ingestion.markdown_export import render_book
from dnd_rag.ingestion.markdown_export.rendering.engine import Engine
from helpers import add_entity, empty_book, origin


def record(result, name, *, parent=None):
    return next(
        row
        for row in result.source_map
        if row['heading_path'][-1] == name
        and (parent is None or parent in row['heading_path'][:-1])
    )


def placed_card(*, page=15, source='XPHB', exact=None):
    book = empty_book()
    entity = add_entity(
        book,
        {
            'name': 'Definition',
            'source': source,
            '__prop': 'feat',
            'page': page,
            'entries': ['A complete rule.'],
        },
        'feat',
        insertion=True,
        page=page,
    )
    wrapper = book['chapters'][0]['content']['entries'][0]
    if exact is not None:
        wrapper['placement'] = {'origin': origin('XPHB', exact, '/source/0/entries/0')}
    book['chapters'][0]['content']['entries'].append(
        {'type': 'section', 'name': 'Next Section', 'page': 20, 'entries': ['Later rules.']}
    )
    return book, entity, wrapper


@pytest.mark.parametrize(
    ('source', 'page', 'exact', 'expected', 'attribution'),
    [
        ('XPHB', 15, None, 15, 'explicit'),
        ('XPHB', 300, None, 10, 'inherited_section_start'),
        ('XPHB', 300, 12, 12, 'explicit'),
        ('OTHER', 15, None, 10, 'inherited_section_start'),
        ('OTHER', 15, 12, 12, 'explicit'),
    ],
)
def test_card_page_requires_local_book_evidence(source, page, exact, expected, attribution):
    book, _, _ = placed_card(page=page, source=source, exact=exact)
    result = render_book(book)
    leaf = record(result, 'Definition')
    assert (leaf['printed_pages'], leaf['page_attribution']) == ([expected], attribution)
    assert record(result, 'First Part')['printed_pages'] == [10, 20]


def test_explicit_placement_does_not_allow_nested_catalog_pages_to_escape():
    book, _, wrapper = placed_card(page=300, exact=12)
    wrapper['data']['entries'] = [
        {'type': 'section', 'name': 'Inner Rules', 'page': 300, 'entries': ['Rules stay here.']}
    ]
    result = render_book(book)
    assert (
        record(result, 'Inner Rules')['printed_pages'],
        record(result, 'Inner Rules')['page_attribution'],
    ) == ([12], 'inherited_section_start')
    assert (
        record(result, 'Definition')['printed_pages'],
        record(result, 'Definition')['page_attribution'],
    ) == ([12], 'partial')
    assert record(result, 'First Part')['printed_pages'] == [10, 20]


@pytest.mark.parametrize('shape', ['unnamed', 'suppressed', 'compact', 'foreign_payload'])
def test_foreign_page_cannot_leak_through_container_or_compact_rendering(shape):
    node = {'type': 'entries', 'source': 'OTHER', 'page': 999, 'entries': ['Foreign rules.']}
    if shape == 'suppressed':
        node['name'] = 'First Part'
    elif shape == 'compact':
        node = {'type': 'list', 'items': [node]}
    elif shape == 'foreign_payload':
        book, _, wrapper = placed_card(source='OTHER')
        wrapper['data']['entries'] = [
            {'type': 'section', 'name': 'Inner Rules', 'page': 15, 'entries': ['Foreign child.']}
        ]
        result = render_book(book)
        assert record(result, 'Inner Rules')['printed_pages'] == [10]
        assert record(result, 'Inner Rules')['page_attribution'] == 'inherited_section_start'
        return
    result = render_book(empty_book(entries=[node]))
    assert record(result, 'First Part')['printed_pages'] == [10]
    assert record(result, 'First Part')['page_attribution'] == 'partial'


@pytest.mark.parametrize('padding', ['', '  '])
def test_reference_target_is_not_a_book_position_or_an_inherited_start(padding):
    target = {
        'type': 'entries',
        'name': padding + '{@class Scholar|XPHB}' + padding,
        'page': 700,
        'entries': [
            {'type': 'section', 'name': 'Overview Details', 'entries': ['Brief overview.']},
        ],
    }
    book = empty_book(
        entries=[target, {'type': 'section', 'name': 'Next', 'page': 20, 'entries': []}]
    )
    engine = Engine(book)
    pages = engine.pages.sources[(0, '/source/0/entries/0')]
    assert pages.page is None and pages.fallback == 10 and pages.role == 'reference_target'
    result = engine.render()
    assert record(result, 'Overview Details')['printed_pages'] == [10]
    assert record(result, 'Overview Details')['page_attribution'] == 'inherited_section_start'
    assert record(result, 'First Part')['printed_pages'] == [10, 20]


def test_each_original_occurrence_uses_its_actual_placement():
    book, entity, first = placed_card(page=70)
    first_site = {'type': 'section', 'name': 'First Site', 'page': 10, 'entries': [first]}
    second = copy.deepcopy(first)
    second['occurrence_id'] += ':second'
    second_site = {'type': 'section', 'name': 'Second Site', 'page': 60, 'entries': [second]}
    book['chapters'][0]['content']['entries'] = [
        first_site,
        second_site,
        {'type': 'section', 'name': 'End', 'page': 80, 'entries': []},
    ]
    entity['canonical_placement']['anchor']['origin']['json_pointer'] = (
        '/source/0/entries/0/entries/0'
    )
    result = render_book(book)
    one = record(result, 'Definition', parent='First Site')
    two = record(result, 'Definition', parent='Second Site')
    assert (one['printed_pages'], one['page_attribution']) == ([10], 'inherited_section_start')
    assert (two['printed_pages'], two['page_attribution']) == ([70], 'explicit')
    assert record(result, 'First Site')['printed_pages'] == [10]
    assert result.body.count('A complete rule.') == 2


def test_native_sibling_definitions_constrain_their_child_origins():
    book = empty_book()
    features = [
        {
            'name': 'Local Feature',
            'source': 'XPHB',
            '__prop': 'feat',
            'page': 25,
            'entries': ['Local rule.'],
        },
        {
            'name': 'Referenced Feature',
            'source': 'XPHB',
            '__prop': 'feat',
            'page': 75,
            'entries': ['Referenced rule.'],
        },
    ]
    parent = add_entity(
        book,
        {
            'name': 'First Facility',
            'source': 'XPHB',
            '__prop': 'facility',
            'page': 20,
            'entries': features,
        },
        'facility',
        insertion=True,
        page=20,
    )
    for data in features:
        add_entity(book, data, 'feat', parent=parent['entity_id'], page=data['page'])
    add_entity(
        book,
        {
            'name': 'Second Facility',
            'source': 'XPHB',
            '__prop': 'facility',
            'page': 40,
            'entries': [],
        },
        'facility',
        insertion=True,
        page=40,
    )
    book['chapters'][0]['content']['entries'].append(
        {'type': 'section', 'name': 'End', 'page': 100, 'entries': []}
    )
    result = render_book(book)
    assert record(result, 'Local Feature')['printed_pages'] == [25]
    assert record(result, 'Referenced Feature')['printed_pages'] == [20]
    assert record(result, 'Referenced Feature')['page_attribution'] == 'inherited_section_start'
    assert record(result, 'First Facility')['printed_pages'] == [20, 25]


def test_ambiguous_inline_origin_cannot_seed_its_own_inherited_fallback():
    book = empty_book()
    data = {
        'name': 'Inline Feature',
        'source': 'XPHB',
        '__prop': 'feat',
        'page': 15,
        'entries': ['Feature rules.'],
    }
    parent = add_entity(
        book,
        {'name': 'Facility', 'source': 'XPHB', '__prop': 'facility', 'page': 12, 'entries': [data]},
        'facility',
        insertion=True,
        page=12,
    )
    child = add_entity(book, data, 'feat', parent=parent['entity_id'], page=15)
    child['data_origin']['lookup_source'] = 'ambiguous_physical_candidates'
    book['chapters'][0]['content']['entries'].append(
        {'type': 'section', 'name': 'Next', 'page': 20, 'entries': []}
    )
    row = record(render_book(book), 'Inline Feature')
    assert (row['printed_pages'], row['page_attribution']) == ([12], 'inherited_section_start')


def test_compact_lists_quotes_and_table_cells_preserve_own_book_evidence():
    def block(name, page):
        return {'type': 'entries', 'name': name, 'page': page, 'entries': [name + ' body.']}

    book = empty_book(
        entries=[
            {'type': 'list', 'items': [block('List Block', 12)]},
            {'type': 'inset', 'name': 'Inset', 'page': 14, 'entries': [block('Inset Block', 15)]},
            {'type': 'table', 'colLabels': ['Rule'], 'rows': [[block('Cell Block', 16)]]},
            {'type': 'entries', 'source': 'OTHER', 'page': 999, 'entries': ['Foreign material.']},
        ]
    )
    result = render_book(book)
    assert len(result.source_map) == 1
    assert record(result, 'First Part')['printed_pages'] == [10, 16]
    assert record(result, 'First Part')['page_attribution'] == 'partial'
    assert all(
        name + ' body.' in result.body for name in ('List Block', 'Inset Block', 'Cell Block')
    )


def test_omitted_images_and_nonrendered_metadata_do_not_supply_page_evidence():
    book = empty_book(
        entries=[{'type': 'image', 'page': 900, 'href': {'type': 'internal', 'path': 'cover.webp'}}]
    )
    book['chapters'][0]['content']['data'] = {'type': 'entries', 'page': 999}
    engine = Engine(book)
    assert engine.pages.sources[(0, '/source/0/data')].page is None
    assert engine.render().source_map[0]['printed_pages'] == [10]


@pytest.mark.parametrize('reason', ['unknown_placement', 'ambiguous_origin'])
def test_catalog_page_without_sufficient_evidence_stays_inherited_or_unknown(reason):
    book, entity, _ = placed_card()
    if reason == 'unknown_placement':
        book['chapters'][0]['origin'] = origin(page=None, attribution='unknown')
        expected, attribution = None, 'unknown'
    else:
        entity['data_origin']['lookup_source'] = 'ambiguous_physical_candidates'
        expected, attribution = [10], 'inherited_section_start'
    result = render_book(book)
    row = record(result, 'Definition')
    assert (row['printed_pages'], row['page_attribution']) == (expected, attribution)


def test_zero_is_a_valid_explicit_book_page():
    book = empty_book(
        entries=[{'type': 'entries', 'name': 'Zero Page', 'page': 0, 'entries': ['Rules.']}]
    )
    book['chapters'][0]['origin'] = origin(page=0)
    result = render_book(book)
    for row in result.source_map:
        assert (row['printed_pages'], row['page_attribution']) == ([0], 'explicit')


def test_unprinted_navigation_group_does_not_add_its_page_to_the_previous_leaf():
    book = empty_book(
        entries=[
            {
                'type': 'section',
                'name': 'Appendix (A)',
                'page': 10,
                'entries': [
                    {'type': 'section', 'name': 'Alpha', 'page': 11, 'entries': ['Alpha text.']},
                    {'type': 'section', 'name': 'Axe', 'page': 12, 'entries': ['Axe text.']},
                ],
            },
            {
                'type': 'section',
                'name': 'Appendix (B)',
                'page': 20,
                'entries': [
                    {'type': 'section', 'name': 'Beta', 'page': 20, 'entries': ['Beta text.']},
                ],
            },
        ]
    )
    result = render_book(book)
    assert record(result, 'Axe')['printed_pages'] == [12]
    assert record(result, 'Beta')['printed_pages'] == [20]
    assert record(result, 'First Part')['printed_pages'] == [10, 20]
    assert 'Appendix (' not in result.body
