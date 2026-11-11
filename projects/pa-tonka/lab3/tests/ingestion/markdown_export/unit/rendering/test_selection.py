"""Local field coverage, missing rules, alternate views and explicit ambiguity."""

import copy
import json

import pytest

from dnd_rag.ingestion.markdown_export import ExportError, render_book
from dnd_rag.ingestion.markdown_export.rendering.inline import InlineRenderer
from dnd_rag.ingestion.markdown_export.rendering.selection import container_projection
from helpers import add_entity, empty_book


def item_book():
    rule = 'As an action, the flask deals {@dice 1d6} Fire damage.'
    section = {
        'type': 'section',
        'name': 'Equipment',
        'entries': [
            {
                'type': 'table',
                'colLabels': ['Item', 'Cost', 'Weight'],
                'rows': [['{@item Signal Flask|XDMG}', '5 GP', '2 lb.']],
            },
            {'type': 'entries', 'name': 'Signal Flask', 'entries': [rule]},
        ],
    }
    book = empty_book('XDMG', entries=[section])
    component = add_entity(
        book,
        {
            'name': 'Signal Flask',
            'source': 'XDMG',
            '__prop': 'item',
            'type': 'G|XPHB',
            'rarity': 'none',
            'weight': 2,
            'value': 500,
            'entries': [rule.replace('@dice', '@damage')],
        },
        'item',
        relation='defining_table_reference',
        anchor='/source/0/entries/0/entries/0/rows/0/0',
    )
    return book, section, component


@pytest.mark.parametrize(
    ('cost', 'value', 'weight', 'amount'),
    [
        ('5 GP', 500, '2 lb.', 2),
        ('500 CP', 500, '½ lb.', 0.5),
        ('50 SP', 500, '1/2 lb.', 0.5),
        ('10 EP', 500, '1½ lb.', 1.5),
        ('0.5 PP', 500, '2 lb. (full)', 2),
        ('1,000 GP', 100000, '2.5 lb.', 2.5),
    ],
)
def test_item_requires_complete_prose_and_table_field_coverage_without_mutating_inputs(
    cost, value, weight, amount
):
    book, scope, component = item_book()
    scope['entries'][0]['rows'][0][1] = cost
    scope['entries'][1]['name'] += ' (' + cost + ')'
    component['data']['value'] = value
    scope['entries'][0]['rows'][0][2] = weight
    component['data']['weight'] = amount
    if '(full)' in weight:
        component['data']['weightNote'] = '(full)'
    before = json.dumps(book, sort_keys=True)
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert decision['decision'] == 'already_represented'
    assert {'entries', 'weight', 'value', 'type', 'rarity'} <= set(decision['coverage'])
    assert not decision['remaining_fields']
    assert result.body.count('the flask deals 1d6 Fire damage.') == 1
    assert '**Price:**' not in result.body and '**Weight:**' not in result.body
    assert json.dumps(book, sort_keys=True) == before


@pytest.mark.parametrize(
    ('extra', 'expected'),
    [
        ({'charges': 4}, '**Charges:** 4'),
        ({'containerCapacity': {'weight': [30]}}, '30 lb.'),
        ({'entries': ['A second, independent rule.']}, 'A second, independent rule.'),
        ({'rarity': 'rare'}, '*rare*'),
    ],
)
def test_item_keeps_unproved_fields_and_missing_paragraphs_without_repeating_known_rule(
    extra, expected
):
    book, _, component = item_book()
    if 'entries' in extra:
        component['data']['entries'].extend(extra['entries'])
    else:
        component['data'].update(extra)
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert decision['decision'] == 'rendered'
    assert result.body.count('the flask deals 1d6 Fire damage.') == 1
    assert expected in result.body
    assert set(extra) <= set(decision['remaining_fields'])


@pytest.mark.parametrize('field', ['weight', 'value'])
def test_conflicting_numeric_properties_are_reported_instead_of_hidden_or_printed_twice(field):
    book, _, component = item_book()
    component['data'][field] += 1
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert decision['decision'] == 'source_preferred'
    assert field not in decision['coverage']
    assert field in decision['conflict']['fields']
    assert [note['code'] for note in result.diagnostics.messages] == ['DOMAIN_SOURCE_CONFLICT']
    assert '**Price:**' not in result.body and '**Weight:**' not in result.body
    assert '| Signal Flask | 5 GP | 2 lb. |' in result.body


@pytest.mark.parametrize('partial', [False, True])
def test_item_suppression_preserves_independent_children_and_parent_provenance(partial):
    book, _, component = item_book()
    if partial:
        component['data']['charges'] = 4
    child = add_entity(
        book,
        {'name': 'Child Rule', '__prop': 'feat', 'entries': ['Independent child rules.']},
        'feat',
        parent=component['entity_id'],
    )
    result = render_book(book)
    assert result.body.count('Independent child rules.') == 1
    record = next(row for row in result.source_map if row['heading_path'][-1] == 'Child Rule')
    assert record['heading_path'] == ['First Part', 'Equipment', 'Child Rule']
    decision = result.diagnostics.components[child['entity_id']]
    assert decision['decision'] == 'rendered_in_parent'
    assert decision['parent'] == component['entity_id']


@pytest.mark.parametrize(
    'reason', ['other_owner', 'other_book', 'wrong_type', 'missing_description']
)
def test_item_link_or_equal_words_alone_cannot_suppress_missing_content(reason):
    book, scope, component = item_book()
    if reason == 'other_owner':
        scope['entries'][1]['name'] = 'Different Flask'
    elif reason == 'other_book':
        scope['entries'][0]['rows'][0][0] = '{@item Signal Flask|OTHER}'
    elif reason == 'wrong_type':
        scope['entries'][0]['rows'][0][0] = '{@creature Signal Flask|XDMG}'
    else:
        scope['entries'][1]['entries'] = ['A different, existing rule.']
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert decision['decision'] == 'rendered'
    assert 'coverage' not in decision
    assert '**Price:** 5 GP' in result.body


def test_item_new_paragraph_cannot_borrow_coverage_from_another_items_rule():
    book, scope, component = item_book()
    extra = 'Another item has this additional effect.'
    component['data']['entries'].append(extra)
    scope['entries'].append({'type': 'entries', 'name': 'Other Flask', 'entries': [extra]})
    result = render_book(book)
    assert result.body.count(extra) == 2
    assert result.body.count('the flask deals 1d6 Fire damage.') == 1
    assert result.diagnostics.components[component['entity_id']]['remaining_fields'] == [
        'entries',
        'rarity',
        'type',
    ]


@pytest.mark.parametrize('ambiguity', ['row', 'owner', 'order', 'multiplicity'])
def test_ambiguous_item_coverage_is_an_error(ambiguity):
    book, scope, component = item_book()
    if ambiguity == 'row':
        scope['entries'][0]['rows'].append(copy.deepcopy(scope['entries'][0]['rows'][0]))
    elif ambiguity == 'owner':
        scope['entries'].append(copy.deepcopy(scope['entries'][1]))
    elif ambiguity == 'order':
        scope['entries'][1]['entries'].append('Second rule.')
        component['data']['entries'] = ['Second rule.', *component['data']['entries']]
    else:
        component['data']['entries'] *= 2
    with pytest.raises(ExportError, match='AMBIGUOUS_DOMAIN_COVERAGE'):
        render_book(book)


def test_alternate_catalog_clause_is_reported_and_is_not_claimed_equivalent():
    book, scope, component = item_book()
    scope['entries'][1]['entries'].append('A separate matching rule.')
    component['data']['entries'] = [
        component['data']['entries'][0].replace('As an action', 'As a Bonus Action'),
        'A separate matching rule.',
    ]
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert decision['decision'] == 'source_preferred'
    assert decision['coverage']['entries']['matched'] == 1
    assert decision['conflict'] == {
        'catalog_clause': 'as a bonus action',
        'book_clause': 'as an action',
    }
    assert [note['code'] for note in result.diagnostics.messages] == ['DOMAIN_SOURCE_CONFLICT']
    assert 'As an action, the flask deals 1d6' in result.body
    assert 'As a Bonus Action' not in result.body


@pytest.mark.parametrize('change', [None, 'dc', 'radius', 'damage', 'variant', 'additional_rule'])
def test_container_projection_requires_the_entire_labelled_rule(change):
    source = {
        'type': 'entries',
        'name': 'Volatile Oil',
        'entries': [
            'A container explodes in a 10-foot radius. Each creature makes a {@dc 13} save, '
            'taking 8 ({@dice 2d6}) Fire damage (for a flask) or '
            '16 ({@dice 4d6}) Fire damage (for a barrel) on a failure or half on success.'
        ],
    }
    entries = [
        'A flask explodes in a 10-foot radius. Each creature makes a {@dc 13} save, '
        'taking 8 ({@damage 2d6}) Fire damage on a failure or half on success.'
    ]
    name = 'Volatile Oil (flask)'
    if change == 'dc':
        entries[0] = entries[0].replace('dc 13', 'dc 14')
    elif change == 'radius':
        entries[0] = entries[0].replace('10-foot', '20-foot')
    elif change == 'damage':
        entries[0] = entries[0].replace('2d6', '4d6')
    elif change == 'variant':
        name = 'Volatile Oil (jar)'
    elif change == 'additional_rule':
        entries[0] += ' It also causes Blindness.'
    assert container_projection(name, entries, [source], InlineRenderer()) == (change is None)


def reward_book():
    rule = (
        'You gain a magical Charm that lasts 3 days or until you use it. '
        'The Charm allows you to cast {@spell Fly|XPHB} once without expending a spell slot. '
        "You can't gain this Charm again while you still have it."
    )
    book = empty_book('XDMG')
    parent = add_entity(
        book,
        {
            'name': 'Quiet Room',
            'source': 'XDMG',
            '__prop': 'facility',
            'entries': [
                {'type': 'entries', 'name': 'Room Charm', 'entries': [rule]},
            ],
        },
        'facility',
        insertion=True,
    )
    component = add_entity(
        book,
        {
            'name': 'Room Charm',
            'source': 'XDMG',
            '__prop': 'reward',
            'type': 'Charm',
            'entries': [rule],
            'seeAlsoFacility': ['quiet room|xdmg'],
            'additionalSpells': [{'innate': {'_': {'limited': {'1': ['fly|xphb']}}}}],
        },
        'reward',
        parent=parent['entity_id'],
        relation='facility_reward',
    )
    return book, component


def test_named_source_intro_precedes_only_the_missing_item_table():
    intro = 'Choose an oddity from this table.'
    book = empty_book('XPHB', entries=[{'type': 'section', 'name': 'Oddities', 'entries': [intro]}])
    component = add_entity(
        book,
        {
            'name': 'Oddity',
            'source': 'XPHB',
            '__prop': 'item',
            'type': 'G|XPHB',
            'rarity': 'none',
            'entries': [
                intro,
                {
                    'type': 'table',
                    'colLabels': ['Roll', 'Result'],
                    'rows': [['1', 'A silver shell']],
                },
            ],
        },
        'item',
        relation='documented_label_alias',
        anchor='/source/0/entries/0',
    )
    result = render_book(book)
    assert result.body.count(intro) == 1
    assert result.body.index(intro) < result.body.index('| 1 | A silver shell |')
    assert result.diagnostics.components[component['entity_id']]['remaining_fields'] == ['entries']


@pytest.mark.parametrize('extra', [None, 'charges', 'weight'])
def test_single_kind_bundle_projection_keeps_unproved_member_fields(extra):
    book, _, bundle = item_book()
    bundle['data']['packContents'] = [{'item': 'signal flask unit|xdmg', 'quantity': 4}]
    member = copy.deepcopy(bundle['data'])
    member.pop('packContents')
    member['name'] = 'Signal Flask Unit'
    member['weight'] /= 4
    member['value'] /= 4
    if extra == 'charges':
        member['charges'] = 3
    elif extra == 'weight':
        member['weight'] += 1
    component = add_entity(
        book, member, 'item', parent=bundle['entity_id'], relation='pack_content'
    )
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert result.body.count('the flask deals 1d6 Fire damage.') == 1
    assert decision['decision'] == (
        'already_represented' if extra is None else 'rendered_in_parent'
    )
    if extra:
        assert decision['remaining_fields'] == [extra]
        assert ('**Charges:** 3' if extra == 'charges' else '**Weight:** 1.5 lb.') in result.body


@pytest.mark.parametrize('change', [None, 'value', 'style', 'unknown'])
def test_named_item_list_projection_preserves_extra_source_rows_and_linked_type_rules(change):
    shared = 'Proficiency with this tool applies to the check.'
    book_list = {
        'type': 'list',
        'style': 'list-hang-notitle',
        'items': [
            {'type': 'item', 'name': 'Ability:', 'entry': 'Intelligence'},
            {'type': 'item', 'name': 'Weight:', 'entry': '3 lb.'},
            {'type': 'item', 'name': 'Utilize:', 'entry': 'Create a disguise ({@dc 12})'},
        ],
    }
    source = {
        'type': 'section',
        'name': 'Tools',
        'entries': [
            shared,
            {'type': 'entries', 'name': 'Travel Kit (25 GP)', 'entries': [book_list]},
        ],
    }
    book = empty_book('XPHB', entries=[source])
    own = {
        'type': 'list',
        'style': 'list-hang-notitle',
        'items': [
            {'type': 'item', 'name': 'Ability:', 'entries': ['Intelligence']},
            {'type': 'item', 'name': 'Utilize:', 'entries': ['Create a disguise ({@dc 12})']},
        ],
    }
    type_entry = {'type': 'entries', 'name': 'Tool', 'entries': [shared]}
    wrapper = {
        'type': 'wrapper',
        'wrapped': copy.deepcopy(type_entry),
        'data': {'item__mergedEntryTag': 'type'},
    }
    if change == 'value':
        own['items'][1]['entries'] = ['Create a disguise ({@dc 13})']
    elif change == 'style':
        own['style'] = 'list-decimal'
    elif change == 'unknown':
        wrapper['wrapped']['futureRule'] = 'Do not discard this mechanic.'
    component = add_entity(
        book,
        {
            'name': 'Travel Kit',
            'source': 'XPHB',
            '__prop': 'item',
            'type': 'T|XPHB',
            'rarity': 'none',
            'weight': 3,
            'value': 2500,
            'entries': [own],
            '_fullEntries': [own, wrapper],
        },
        'item',
        relation='named_source_section_or_row',
        anchor='/source/0/entries/0/entries/1',
    )
    add_entity(
        book,
        {'name': 'Tool', 'source': 'XPHB', '__prop': 'itemType', 'entries': [type_entry]},
        'itemType',
        parent=component['entity_id'],
        relation='item_type',
    )
    if change == 'unknown':
        with pytest.raises(ExportError, match='UNKNOWN_ENTRY_FIELD'):
            render_book(book)
        return
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert result.body.count(shared) == 1
    assert decision['decision'] == ('already_represented' if change is None else 'rendered')
    if change is None:
        assert result.body.count('Create a disguise (DC 12)') == 1
    elif change == 'value':
        assert 'Create a disguise (DC 13)' in result.body
    else:
        assert '1. **Ability:**' in result.body


def test_empty_service_alias_keeps_book_price_and_reports_catalog_conflict():
    row = {'type': 'row', 'row': ['Animal lodging', '5 SP']}
    table = {'type': 'table', 'colLabels': ['Service', 'Cost'], 'rows': [row]}
    book = empty_book('XPHB', entries=[table])
    component = add_entity(
        book,
        {
            'name': 'Lodging (per day)',
            'source': 'XPHB',
            '__prop': 'item',
            'type': 'TAH|XPHB',
            'rarity': 'none',
            'value': 5,
            'entries': [],
        },
        'item',
        relation='documented_label_alias',
        anchor='/source/0/entries/0/rows/0/row/0',
    )
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert decision['decision'] == 'source_preferred'
    assert decision['conflict']['fields']['value'] == {'book': '5 SP', 'catalog': 5}
    assert not decision['remaining_fields'] and '**Price:**' not in result.body
    assert '| Animal lodging | 5 SP |' in result.body


def test_reward_type_parent_spell_identity_and_one_use_are_all_proven():
    book, component = reward_book()
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert decision['decision'] == 'already_represented'
    assert set(decision['coverage']) == {'entries', 'type', 'seeAlsoFacility', 'additionalSpells'}
    assert result.body.count('The Charm allows you to cast *Fly* once') == 1
    assert 'Additional Spells' not in result.body and 'Related Facilities' not in result.body


@pytest.mark.parametrize(
    'extra', ['count', 'spell_source', 'recharge', 'prerequisite', 'entries', 'type', 'parent']
)
def test_reward_additional_mechanics_cannot_hide_behind_equal_prose(extra):
    book, component = reward_book()
    data = component['data']
    field = 'additionalSpells'
    if extra == 'count':
        data['additionalSpells'][0]['innate']['_']['limited'] = {'2': ['fly|xphb']}
    elif extra == 'spell_source':
        data['additionalSpells'][0]['innate']['_']['limited']['1'] = ['fly|OTHER']
    elif extra == 'recharge':
        data['additionalSpells'][0]['innate']['_'] = {'daily': {'1': ['fly|xphb']}}
    elif extra == 'prerequisite':
        field = 'prerequisite'
        data[field] = [{'level': 3}]
    elif extra == 'entries':
        field = 'entries'
        data[field].append('Gain 5 Temporary Hit Points.')
    elif extra == 'type':
        field = 'type'
        data[field] = 'Blessing'
    else:
        field = 'seeAlsoFacility'
        data[field].append('other room|xdmg')
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert decision['decision'] == 'rendered_in_parent'
    assert decision['remaining_fields'] == [field]
    assert result.body.count('The Charm allows you to cast *Fly* once') == 1
    assert {
        'additionalSpells': '**Additional Spells:**',
        'prerequisite': '**Prerequisite:** Level 3',
        'entries': 'Gain 5 Temporary Hit Points.',
        'type': '**Type:** Blessing',
        'seeAlsoFacility': '**Related Facilities:**',
    }[field] in result.body


@pytest.mark.parametrize('family', ['item', 'reward'])
def test_unknown_fields_are_validated_before_suppressing_catalog_content(family):
    book, *_, component = item_book() if family == 'item' else reward_book()
    component['data']['futureRule'] = 'Do not discard this rule.'
    with pytest.raises(ExportError, match='UNKNOWN_PAYLOAD_FIELD.*futureRule'):
        render_book(book)


@pytest.mark.parametrize('kind', ['speaker_index', 'rules', 'language_link'])
def test_language_speaker_index_is_metadata_only_at_creature_placements(kind):
    book = empty_book('XMM', entries=['{@creature Birdfolk|OLD}'])
    data = {
        'name': 'Birdfolk',
        'source': 'XMM',
        '__prop': 'language',
        'typicalSpeakers': ['{@creature Sky Guard|XMM}'],
    }
    if kind == 'rules':
        data['entries'] = ['This language uses whistles.']
    elif kind == 'language_link':
        book['chapters'][0]['content']['entries'][0] = '{@language Birdfolk|XMM}'
    component = add_entity(book, data, 'language', anchor='/source/0/entries/0')
    result = render_book(book)
    decision = result.diagnostics.components[component['entity_id']]
    assert decision['decision'] == ('metadata_only' if kind == 'speaker_index' else 'rendered')
    assert ('**Typical Speakers:**' in result.body) == (kind != 'speaker_index')
    if kind == 'rules':
        assert 'This language uses whistles.' in result.body
