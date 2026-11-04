"""Local structural equivalence and typed deck projection."""

import pytest

from dnd_rag.ingestion.markdown_export import ExportError, render_book
from dnd_rag.ingestion.markdown_export.rendering.engine import Engine
from dnd_rag.ingestion.markdown_export.rendering.representation import deck_roll_projection
from helpers import add_entity, empty_book, tables


@pytest.mark.parametrize(
    ('expected', 'available'),
    [
        (
            {
                'type': 'entries',
                'entries': [
                    {'type': 'table', 'colLabels': ['Name', 'Value'], 'rows': [['Skill', 5]]}
                ],
            },
            {
                'type': 'entries',
                'entries': [
                    {'type': 'table', 'colLabels': ['Name', 'Value'], 'rows': [['Skill', 7]]}
                ],
            },
        ),
        (
            {'type': 'list', 'style': 'list-decimal', 'items': ['First step', 'Second step']},
            {'type': 'list', 'style': 'list-decimal', 'items': ['Second step', 'First step']},
        ),
        ({'type': 'list', 'items': ['Repeat', 'Repeat']}, {'type': 'list', 'items': ['Repeat']}),
        (
            {'type': 'list', 'style': 'list-decimal', 'items': ['First', 'Second']},
            {'type': 'list', 'items': ['First', 'Second']},
        ),
        (
            {'type': 'entries', 'entries': ['Rules'], 'futureRule': 5},
            {'type': 'entries', 'entries': ['Rules']},
        ),
    ],
)
def test_equal_words_do_not_prove_different_structures_represented(expected, available):
    engine = Engine(empty_book())
    assert not engine.entry_represented(expected, {'entries': [available]})
    assert engine.entry_represented(expected, {'entries': [expected]})


def test_definition_numeric_table_cells_are_not_silently_discarded():
    book = empty_book()
    source_table = {'type': 'table', 'colLabels': ['Name', 'Value'], 'rows': [['Skill', 7]]}
    extra_table = {'type': 'table', 'colLabels': ['Name', 'Value'], 'rows': [['Skill', 5]]}
    parent = add_entity(
        book,
        {'name': 'Object', '__prop': 'item', 'entries': [source_table]},
        'item',
        insertion=True,
    )
    component = add_entity(
        book,
        {'name': 'Property', '__prop': 'itemProperty', 'entries': [extra_table]},
        'itemProperty',
        parent=parent['entity_id'],
    )
    result = render_book(book)
    assert [table[-1][-1] for table in tables(result.body)] == ['7', '5']
    assert result.diagnostics.components[component['entity_id']]['decision'] == 'rendered_in_parent'


def test_numeric_only_definition_has_content():
    book = empty_book()
    parent = add_entity(
        book,
        {'name': 'Object', '__prop': 'item', 'entries': ['Description.']},
        'item',
        insertion=True,
    )
    component = add_entity(
        book,
        {'name': 'Property', '__prop': 'itemProperty', 'entries': [0]},
        'itemProperty',
        parent=parent['entity_id'],
    )
    result = render_book(book)
    assert '\n0\n' in result.body
    assert result.diagnostics.components[component['entity_id']]['decision'] == 'rendered_in_parent'


def test_deck_projection_cannot_mix_rows_from_different_roll_columns():
    engine = Engine(empty_book())
    projected = {
        'type': 'table',
        'caption': 'Draws',
        'colLabels': ['Roll', 'Card'],
        'rows': [['01–02', 'Alpha'], ['03–04', 'Beta']],
    }
    source = {
        'type': 'table',
        'caption': 'Draws',
        'colLabels': ['Small Deck', 'Large Deck', 'Card'],
        'rows': [['01–02', '11–12', 'Alpha'], ['13–14', '03–04', 'Beta']],
    }
    assert not deck_roll_projection(projected, source, engine.inline)
    source['rows'][1][0] = '03–04'
    assert deck_roll_projection(projected, source, engine.inline)
    assert not engine.entry_represented(projected, source)


@pytest.mark.parametrize('change', ['order', 'roll', 'value_category'])
def test_loot_suppression_requires_exact_numbered_results_and_category(change):
    table = {
        'type': 'table',
        'caption': '50 GP Gems',
        'colLabels': ['1d2', 'Gem'],
        'rows': [['1', 'Ruby'], ['2', 'Sapphire']],
    }
    book = empty_book('XDMG', entries=[table])
    component = add_entity(
        book,
        {'name': '50 GP Gems', '__prop': 'gems', 'type': 50, 'table': ['Ruby', 'Sapphire']},
        'gems',
        anchor='/source/0/entries/0',
    )
    result = render_book(book)
    assert (
        result.diagnostics.components[component['entity_id']]['decision'] == 'already_represented'
    )
    if change == 'order':
        table['rows'][0][1], table['rows'][1][1] = table['rows'][1][1], table['rows'][0][1]
    elif change == 'roll':
        table['rows'][1][0] = '3'
    else:
        table['caption'] = '500 GP Gems'
    result = render_book(book)
    assert result.diagnostics.components[component['entity_id']]['decision'] == 'rendered'
    assert len(tables(result.body)) == 2


@pytest.mark.parametrize('deck', [False, True])
def test_card_rules_cannot_be_borrowed_from_a_different_named_card(deck):
    book = empty_book('XDMG')
    parent = add_entity(
        book,
        {
            'name': 'Deck Item',
            '__prop': 'item',
            'entries': [
                {'type': 'entries', 'name': 'Alpha', 'entries': ['Actual Alpha rule.']},
                {'type': 'entries', 'name': 'Beta', 'entries': ['Required Alpha rule.']},
            ],
        },
        'item',
        insertion=True,
    )
    card = {'name': 'Alpha', '__prop': 'card', 'entries': ['Required Alpha rule.']}
    if deck:
        component = add_entity(
            book,
            {'name': 'Deck Rules', '__prop': 'deck', 'entries': [], 'cards': [card]},
            'deck',
            parent=parent['entity_id'],
        )
    else:
        component = add_entity(book, card, 'card', parent=parent['entity_id'])
    result = render_book(book)
    assert result.diagnostics.components[component['entity_id']]['decision'] == 'rendered_in_parent'
    assert result.body.count('Required Alpha rule.') == 2
    # A matching named section is affirmative evidence even when other cards
    # also use the same text; the rule and its owner remain associated.
    book['chapters'][0]['content']['entries'][0]['data']['entries'][0]['entries'] = [
        'Required Alpha rule.'
    ]
    result = render_book(book)
    assert (
        result.diagnostics.components[component['entity_id']]['decision'] == 'already_represented'
    )
    assert result.body.count('Required Alpha rule.') == 2


def test_empty_card_rules_can_be_represented_by_its_visible_name():
    book = empty_book('XDMG')
    parent = add_entity(
        book,
        {
            'name': 'Deck Item',
            '__prop': 'item',
            'entries': [
                {'type': 'table', 'colLabels': ['Roll', 'Card'], 'rows': [['1', 'Alpha']]},
            ],
        },
        'item',
        insertion=True,
    )
    component = add_entity(
        book, {'name': 'Alpha', '__prop': 'card', 'entries': []}, 'card', parent=parent['entity_id']
    )
    result = render_book(book)
    assert (
        result.diagnostics.components[component['entity_id']]['decision'] == 'already_represented'
    )
    assert result.body.count('Alpha') == 1


@pytest.mark.parametrize('source_child', [False, True])
def test_fluff_unknown_fields_are_validated_before_render_or_shared_suppression(source_child):
    book = empty_book('XMM')
    parent = add_entity(
        book,
        {
            'name': 'Species',
            '__prop': 'monsterFluff',
            'entries': ['Common lore.'],
            'futureRules': ['Rules must not disappear.'],
        },
        'monsterFluff',
    )
    if source_child:
        child = add_entity(
            book,
            {'name': 'Variant', '__prop': 'monsterFluff', 'entries': ['Common lore.']},
            'monsterFluff',
            insertion=True,
        )
        child['shared_content'] = [
            {
                'path': '/entries/0',
                'parent_entity_id': parent['entity_id'],
                'parent_path': '/entries/0',
            }
        ]
    with pytest.raises(ExportError, match='UNKNOWN_PAYLOAD_FIELD.*futureRules'):
        render_book(book)


def inline_component_book(inline, canonical):
    book = empty_book()
    base = {
        'name': 'Resolve',
        '__prop': 'classFeature',
        'source': 'XPHB',
        'className': 'Scholar',
        'classSource': 'XPHB',
        'level': 1,
    }
    parent = add_entity(
        book,
        {'name': 'Package', '__prop': 'classFeature', 'entries': [{**base, **inline}]},
        'classFeature',
        insertion=True,
    )
    component = add_entity(book, {**base, **canonical}, 'classFeature', parent=parent['entity_id'])
    return book, component


def test_inline_component_preserves_inline_costs_and_missing_canonical_fields():
    book, component = inline_component_book(
        {
            'entries': [
                '{@i Cost: 1 Sorcery Point}',
                'First rule.',
                'Additional source context.',
                'Second rule.',
            ]
        },
        {
            'entries': ['First rule.', 'Second rule.'],
            'prerequisite': [{'level': 2}],
            'featureType': ['MM'],
        },
    )
    result = render_book(book)
    for text in (
        'Cost: 1 Sorcery Point',
        'Additional source context.',
        '**Prerequisite:** Level 2',
        '**Feature Type:** Metamagic',
    ):
        assert text in result.body
    assert result.body.count('First rule.') == result.body.count('Second rule.') == 1
    assert result.diagnostics.components[component['entity_id']]['decision'] == 'rendered_in_parent'


@pytest.mark.parametrize(
    ('inline', 'canonical', 'code'),
    [
        (
            {'entries': ['Known rule.']},
            {'entries': ['Known rule.'], 'futureRules': ['Do not lose this.']},
            'UNKNOWN_PAYLOAD_FIELD',
        ),
        (
            {'entries': ['Known rule.']},
            {'entries': ['Known rule.', 'Do not lose this.']},
            'INLINE_COMPONENT_MISMATCH',
        ),
        (
            {'entries': ['Second rule.', 'First rule.']},
            {'entries': ['First rule.', 'Second rule.']},
            'INLINE_COMPONENT_MISMATCH',
        ),
        (
            {'entries': ['Rule.'], 'prerequisite': [{'level': 1}]},
            {'entries': ['Rule.'], 'prerequisite': [{'level': 2}]},
            'INLINE_COMPONENT_MISMATCH',
        ),
    ],
)
def test_inline_component_cannot_hide_unknown_missing_or_conflicting_rules(inline, canonical, code):
    book, _ = inline_component_book(inline, canonical)
    with pytest.raises(ExportError, match=code):
        render_book(book)


@pytest.mark.parametrize('prop', ['itemEntry', 'baseitem', 'magicvariant'])
def test_materialized_item_components_validate_unknown_fields_before_suppression(prop):
    book = empty_book('XDMG')
    parent = add_entity(
        book,
        {'name': 'Item', '__prop': 'item', 'entries': ['Expanded text.']},
        'item',
        insertion=True,
    )
    relation = (
        'structural_string_reference'
        if prop == 'itemEntry'
        else 'generated_item_base_item'
        if prop == 'baseitem'
        else 'generated_item_template'
    )
    payload = {'name': 'Recipe', '__prop': prop, 'futureRules': ['Unknown mechanic.']}
    payload['entriesTemplate' if prop == 'itemEntry' else 'entries'] = ['Expanded text.']
    component = add_entity(book, payload, prop, parent=parent['entity_id'], relation=relation)
    if prop != 'itemEntry':
        book['chapters'][0]['content']['entries'][0]['derivation'] = {
            'base_item' if prop == 'baseitem' else 'template': {
                'target': {'entity_id': component['entity_id']}
            }
        }
    with pytest.raises(ExportError, match='UNKNOWN_PAYLOAD_FIELD.*futureRules'):
        render_book(book)
