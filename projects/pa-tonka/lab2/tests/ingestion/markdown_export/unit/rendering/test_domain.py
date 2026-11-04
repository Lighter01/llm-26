import copy
import json

import pytest

from dnd_rag.ingestion.markdown_export import ExportError, render_book
from helpers import add_entity, empty_book


def test_original_duplicate_insertions_survive_but_registry_does_not_repeat_them():
    book = empty_book()
    data = {
        'name': 'Repeated',
        'source': 'XPHB',
        '__prop': 'feat',
        'entries': ['Same original prose.'],
    }
    for _ in range(2):
        add_entity(book, copy.deepcopy(data), 'feat', insertion=True)
    child = add_entity(
        book,
        {'name': 'Supplement', '__prop': 'feat', 'entries': ['Extra rules.']},
        'feat',
        parent=book['domain']['entities'][0]['entity_id'],
    )
    before = json.dumps(book, sort_keys=True)
    result = render_book(book)
    assert result.body.count('Same original prose.') == 2
    assert result.body.count('Extra rules.') == 1
    assert result.diagnostics.counts['source_insertions'] == 2
    assert result.diagnostics.components[child['entity_id']]['decision'] == 'rendered_in_parent'
    assert json.dumps(book, sort_keys=True) == before


def test_shared_content_is_verified_locally_not_globally():
    book = empty_book('XMM')
    parent = add_entity(
        book,
        {'name': 'Species', '__prop': 'monsterFluff', 'entries': ['Common lore.']},
        'monsterFluff',
    )
    child = add_entity(
        book,
        {
            'name': 'Variant',
            '__prop': 'monsterFluff',
            'entries': ['Common lore.', 'Individual lore.', 'Common lore.'],
        },
        'monsterFluff',
        parent=parent['entity_id'],
        relation='companion_fluff',
    )
    child['shared_content'] = [
        {'path': '/entries/0', 'parent_entity_id': parent['entity_id'], 'parent_path': '/entries/0'}
    ]
    result = render_book(book)
    assert result.body.count('Common lore.') == 2  # Unmarked identical individual text survives.
    assert result.body.count('Individual lore.') == 1
    child['data']['entries'][0] = 'Different, not shared.'
    with pytest.raises(ExportError, match='SHARED_CONTENT_MISMATCH'):
        render_book(book)


def test_native_feature_identity_includes_class_source_and_level():
    book = empty_book()
    parent = add_entity(
        book,
        {'name': 'Package', '__prop': 'classFeature', 'entries': []},
        'classFeature',
        insertion=True,
    )
    body = book['chapters'][0]['content']['entries'][0]['data']['entries']
    children = []
    for i, (cls, source, level) in enumerate(
        (
            ('Scholar', 'XPHB', 1),
            ('Warrior', 'XPHB', 1),
            ('Scholar', 'OLD', 1),
            ('Scholar', 'XPHB', 2),
        )
    ):
        data = {
            'name': 'Resolve',
            '__prop': 'classFeature',
            'className': cls,
            'source': source,
            'classSource': source,
            'level': level,
            'entries': [f'Rules for identity {i}.'],
        }
        body.append(copy.deepcopy(data))
        children.append(add_entity(book, data, 'classFeature', parent=parent['entity_id']))
    result = render_book(book)
    assert all(result.body.count(f'Rules for identity {i}.') == 1 for i in range(len(children)))
    assert all(
        result.diagnostics.components[e['entity_id']]['decision'] == 'rendered_in_parent'
        for e in children
    )


def test_cross_book_entity_page_does_not_override_placement(fixture_data):
    book = empty_book('XPHB')
    data = fixture_data('monster')  # The card origin and book placement have different pages.
    entity = add_entity(book, data, 'monster', insertion=True)
    result = render_book(book)
    record = result.source_map[-1]
    assert record['printed_pages'] == [
        entity['canonical_placement']['anchor']['origin']['printed_page']
    ]
    assert record['printed_pages'] != [entity['data_origin']['printed_page']]
    assert record['page_attribution'] == 'inherited_section_start'


@pytest.mark.parametrize(
    ('mutation', 'code'),
    [
        ('anchor', 'MISSING_ANCHOR'),
        ('parent', 'MISSING_PARENT'),
        ('cycle', 'PLACEMENT_CYCLE'),
        ('relation', 'DANGLING_RELATION'),
        ('duplicate_entity', 'DUPLICATE_ENTITY'),
        ('duplicate_occurrence', 'DUPLICATE_OCCURRENCE'),
        ('book', 'CROSS_BOOK_ANCHOR'),
        ('insertion_id', 'MISSING_INSERTION'),
    ],
)
def test_invalid_placement_graph_fails(mutation, code):
    book = empty_book()
    entity = add_entity(
        book, {'name': 'Rule', '__prop': 'feat', 'entries': ['Rule text.']}, 'feat', insertion=True
    )
    placement = entity['canonical_placement']
    if mutation == 'anchor':
        placement['anchor']['origin']['json_pointer'] = '/absent'
    elif mutation == 'parent':
        placement['parent_entity_id'] = 'missing'
    elif mutation == 'cycle':
        placement['parent_entity_id'] = entity['entity_id']
    elif mutation == 'relation':
        book['domain']['relationships'].append(
            {
                'from_entity_id': entity['entity_id'],
                'to_entity_id': 'missing',
                'relation': 'companion_fluff',
            }
        )
    elif mutation == 'duplicate_entity':
        book['domain']['entities'].append(copy.deepcopy(entity))
    elif mutation == 'duplicate_occurrence':
        book['chapters'][0]['content']['entries'].append(
            copy.deepcopy(book['chapters'][0]['content']['entries'][0])
        )
    elif mutation == 'book':
        placement['anchor']['book_id'] = 'XMM'
    else:
        book['chapters'][0]['content']['entries'][0]['entity_id'] = 'wrong'
    with pytest.raises(ExportError) as error:
        render_book(book)
    assert error.value.code == code


def test_root_component_at_table_cell_is_placed_after_complete_table():
    book = empty_book(entries=[{'type': 'table', 'colLabels': ['Rule'], 'rows': [['Ref']]}])
    add_entity(
        book,
        {'name': 'Expanded Rule', '__prop': 'feat', 'entries': ['Expanded prose.']},
        'feat',
        anchor='/source/0/entries/0/rows/0/0',
    )
    result = render_book(book)
    assert result.body.index('| Ref |') < result.body.index('## Expanded Rule')


def test_declared_deck_projection_requires_matching_roll_card_pairs():
    book = empty_book('XDMG')
    parent_table = {
        'type': 'table',
        'caption': 'Deck',
        'colLabels': ['d13', 'd22', 'Card'],
        'rows': [['01–02', '01–03', 'Fortune']],
    }
    item = add_entity(
        book,
        {
            'name': 'Deck Item',
            '__prop': 'item',
            'entries': [
                parent_table,
                {'type': 'entries', 'name': 'Fortune', 'entries': ['Gain a boon.']},
            ],
        },
        'item',
        insertion=True,
    )
    projection = {
        'type': 'table',
        'caption': 'Deck',
        'colLabels': ['Roll', 'Card'],
        'rows': [['01–02', 'Fortune']],
    }
    card = {'name': 'Fortune', '__prop': 'card', 'entries': ['Gain a boon.']}
    deck = add_entity(
        book,
        {'name': 'Deck Rules', '__prop': 'deck', 'entries': [projection], 'cards': [card]},
        'deck',
        parent=item['entity_id'],
    )
    child = add_entity(book, copy.deepcopy(card), 'card', parent=deck['entity_id'])
    result = render_book(book)
    assert result.body.count('Gain a boon.') == 1
    assert result.diagnostics.components[deck['entity_id']]['decision'] == 'already_represented'
    assert result.diagnostics.components[child['entity_id']]['decision'] == 'already_represented'
    projection['rows'][0][0] = '99'
    result = render_book(book)
    assert '| 99 | Fortune |' in result.body
    assert result.diagnostics.components[deck['entity_id']]['decision'] == 'rendered_in_parent'


@pytest.mark.parametrize('valid', [True, False])
def test_generated_item_derivation_must_target_exact_component(valid):
    book = empty_book('XDMG')
    parent = add_entity(
        book,
        {'name': 'Generated Armor', '__prop': 'item', 'entries': ['Concrete expanded rules.']},
        'item',
        insertion=True,
    )
    component = add_entity(
        book,
        {'name': 'Base Armor', '__prop': 'item', 'entries': ['Base rules.']},
        'item',
        parent=parent['entity_id'],
        relation='generated_item_base_item',
    )
    book['chapters'][0]['content']['entries'][0]['derivation'] = {
        'base_item': {'target': {'entity_id': component['entity_id'] if valid else 'wrong'}}
    }
    if not valid:
        with pytest.raises(ExportError, match='DERIVATION_COMPONENT'):
            render_book(book)
        return
    result = render_book(book)
    assert result.diagnostics.components[component['entity_id']]['decision'] == 'native_derivation'
    assert 'Concrete expanded rules.' in result.body and '## Base Armor' not in result.body


def test_definition_suppression_is_limited_to_declared_parent():
    book = empty_book(entries=['Identical definition outside the parent.'])
    parent = add_entity(
        book,
        {'name': 'Weapon', '__prop': 'item', 'entries': ['Weapon description.']},
        'item',
        insertion=True,
    )
    component = add_entity(
        book,
        {
            'name': 'Property',
            '__prop': 'itemProperty',
            'entries': ['Identical definition outside the parent.'],
        },
        'itemProperty',
        parent=parent['entity_id'],
    )
    result = render_book(book)
    assert result.body.count('Identical definition outside the parent.') == 2
    assert result.diagnostics.components[component['entity_id']]['decision'] == 'rendered_in_parent'


def test_component_audit_rejects_missing_export_decision():
    from dnd_rag.ingestion.markdown_export.rendering.engine import Engine

    book = empty_book()
    add_entity(book, {'name': 'Rule', '__prop': 'feat', 'entries': ['Must not vanish.']}, 'feat')
    with pytest.raises(ExportError, match='UNPLACED_COMPONENTS'):
        Engine(book).domain.audit()
