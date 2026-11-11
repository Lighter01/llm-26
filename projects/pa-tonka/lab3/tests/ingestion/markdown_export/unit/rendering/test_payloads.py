import pytest

from dnd_rag.ingestion.markdown_export import ExportError, render_book
from helpers import add_entity, blocks, empty_book, tables, visible


def render_payload(data, prop):
    book = empty_book('XMM' if prop == 'monster' else 'XPHB')
    add_entity(book, data, prop, insertion=True)
    return render_book(book)


def test_complete_statblock_and_derived_missing_saves(fixture_data):
    data = fixture_data('monster')
    result = render_payload(data, 'monster')
    assert tables(result.body) == [
        [
            ['', 'STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'],
            ['Score', '19', '13', '16', '8', '15', '6'],
            ['Mod', '+4', '+1', '+3', '-1', '+2', '-2'],
            ['Save', '+7', '+1', '+3', '-1', '+5', '-2'],
        ]
    ]
    assert len(list(blocks(result.body))) == 1
    text = visible(result.body)
    for value in (
        'AC: 17 (natural armor)',
        'Initiative: +7 (17)',
        'HP: 85 (10d10 + 30)',
        'Speed: 30 ft., Fly 40 ft. (hover)',
        'Skills: Perception +8, Survival +5',
        'Passive Perception 18',
        'Vulnerabilities: Thunder',
        'Immunities: Poison',
        'Condition Immunities: Poisoned',
        'from nonmagical attacks',
        '2 × Spear',
        'CR: 5 (XP 1,800; PB +3)',
        'Legendary Action Uses: 2 (3 in Lair)',
        'Traits',
        'Actions',
        'Bonus Actions',
        'Reactions',
        'Legendary Actions',
        '2d6 + 5',
        'At will: Light',
        '1/day each: Shield, Fly',
        'Spell level 1 (2 slots): Magic Missile',
        'No Material components required.',
    ):
        assert value in text
    assert [r['heading_path'][-1] for r in result.source_map] == ['First Part', data['name']]


def test_initiative_and_all_save_fallbacks_do_not_require_explicit_fields(fixture_data):
    data = fixture_data('monster')
    for field in ('passive', 'initiative', 'save'):
        data.pop(field)
    result = render_payload(data, 'monster')
    assert '**Initiative:** +1 (11)' in result.body
    assert tables(result.body)[0][2][1:] == tables(result.body)[0][3][1:]


def test_symbolic_summon_values_survive_without_invented_level(fixture_data):
    data = fixture_data('monster')
    data.update(
        ac=[{'special': "11 + the spell's level"}],
        hp={'special': '40 + 10 for each spell level above 4'},
        cr='Unknown',
        pbNote='equals your Proficiency Bonus',
        action=[{'name': 'Strike', 'entries': ['{@damage 1d8 + summonSpellLevel} Force damage.']}],
    )
    result = render_payload(data, 'monster')
    for expected in (
        "11 + the spell's level",
        '40 + 10 for each spell level above 4',
        "1d8 + the spell's level",
        'equals your Proficiency Bonus',
    ):
        assert expected in result.body
    assert '**CR:** Unknown\n' in result.body


def test_spell_mechanics_higher_levels_and_scaling():
    data = {
        'name': 'Test Cantrip',
        'source': 'XPHB',
        '__prop': 'spell',
        'level': 0,
        'school': 'V',
        'time': [{'number': 1, 'unit': 'bonus'}],
        'range': {'type': 'point', 'distance': {'type': 'feet', 'amount': 60}},
        'components': {
            'v': True,
            's': True,
            'm': {'text': 'a pearl worth 100 GP', 'cost': 10000, 'consume': True},
        },
        'duration': [
            {'type': 'timed', 'duration': {'type': 'minute', 'amount': 1}, 'concentration': True}
        ],
        'entries': ['Deal {@damage 1d6} Thunder damage.'],
        'entriesHigherLevel': [
            {'type': 'entries', 'name': 'Cantrip Upgrade', 'entries': ['More damage.']}
        ],
        'classes': {'fromClassList': [{'name': 'Bard', 'source': 'XPHB'}]},
        'scalingLevelDice': {
            'label': 'Damage Scaling',
            'scaling': {'1': '1d6', '5': '2d6', '11': '3d6'},
        },
    }
    result = render_payload(data, 'spell')
    for value in (
        'Evocation Cantrip',
        '1 Bonus Action',
        '60 feet',
        'M (a pearl worth 100 GP; consumed)',
        'Concentration, up to 1 minute',
        'Bard',
        'Cantrip Upgrade',
        'More damage.',
    ):
        assert value in result.body
    assert tables(result.body) == [[['Level', 'Dice'], ['1', '1d6'], ['5', '2d6'], ['11', '3d6']]]


@pytest.mark.parametrize(
    ('name', 'expected', 'higher_level'),
    [
        (
            'Fireball',
            'Sorcerer, Wizard',
            'The damage increases by 1d6 for each spell slot level above 3.',
        ),
        (
            'Cure Wounds',
            'Bard, Cleric, Druid, Paladin, Ranger',
            'The healing increases by 2d8 for each spell slot level above 1.',
        ),
    ],
)
def test_real_spells_keep_compact_classes_without_reverse_access_indexes(
    fixture_data, name, expected, higher_level
):
    data = fixture_data('spells')[name]
    result = render_payload(data, 'spell')
    assert '**Classes:** ' + expected + '\n' in result.body
    assert not any(
        label in result.body
        for label in (' Access:', 'Subclass:', 'Base Source:', 'Sub Subclass:', 'Artificer')
    )
    assert 'Using a Higher-Level Spell Slot' in result.body
    assert higher_level in result.body


@pytest.mark.parametrize(
    ('definition_source', 'expected'),
    [('XPHB', 'Artificer, Sorcerer, Wizard'), ('Other Supplement', 'Artificer, Wizard')],
)
def test_spell_classes_use_book_class_identity_and_definition_source(
    fixture_data, definition_source, expected
):
    data = fixture_data('spells')['Fireball']
    data['classes']['fromClassList'] = [
        {'name': 'Wizard', 'source': 'PHB'},
        {'name': 'Wizard', 'source': 'XPHB'},
        {'name': 'Artificer', 'source': 'EFA'},
        {'name': 'Sorcerer', 'source': 'XPHB', 'definedInSource': definition_source},
    ]
    book = empty_book()
    # The book explicitly includes these class identities, including a foreign source.
    for name, source in [('Artificer', 'EFA'), ('Wizard', 'XPHB'), ('Sorcerer', 'XPHB')]:
        add_entity(
            book, {'name': name, 'source': source, '__prop': 'class'}, 'class', insertion=True
        )
    add_entity(book, data, 'spell', insertion=True)
    assert '**Classes:** ' + expected + '\n' in render_book(book).body


@pytest.mark.parametrize(
    'classes', [[], {'fromClassList': ['Wizard']}, {'fromClassList': [{'name': 'Wizard'}]}]
)
def test_malformed_primary_spell_classes_are_diagnosed(fixture_data, classes):
    data = fixture_data('spells')['Fireball']
    data['classes'] = classes
    with pytest.raises(ExportError) as error:
        render_payload(data, 'spell')
    assert error.value.code == 'SPELL_CLASSES'
    assert error.value.context['heading_path'][-1] == 'Fireball'


@pytest.mark.parametrize(
    'classes', [None, {'fromSubclass': [{'class': {'name': 'Cleric', 'source': 'XPHB'}}]}]
)
def test_missing_main_spell_list_does_not_promote_subclass_access(fixture_data, classes):
    data = fixture_data('spells')['Fireball']
    if classes is None:
        data.pop('classes')
    else:
        data['classes'] = classes
    result = render_payload(data, 'spell')
    assert '**Classes:**' not in result.body
    assert 'A bright streak flashes' in result.body


def test_item_uses_processed_full_entries_and_keeps_game_fields():
    data = {
        'name': 'Test Wand',
        '__prop': 'item',
        'source': 'XPHB',
        'type': 'WD',
        'rarity': 'rare',
        'reqAttune': 'by a Wizard',
        'charges': 7,
        'recharge': 'dawn',
        'rechargeAmount': '{@dice 1d6 + 1}',
        'entries': ['Base text.'],
        '_fullEntries': [
            'Base text.',
            {
                'type': 'wrapper',
                'data': {'item__mergedEntryTag': 'Armor'},
                'wrapped': {'type': 'entries', 'name': 'Armor', 'entries': ['Enhanced rule.']},
            },
        ],
        'containerCapacity': {'weight': [500], 'volume': [64], 'weightless': True},
        'weight': 1,
        '_isEnhanced': True,
        '_baseName': 'Debug metadata',
        'hasToken': True,
    }
    result = render_payload(data, 'item')
    assert result.body.count('Base text.') == result.body.count('Enhanced rule.') == 1
    assert '**Armor**' in result.body and 'Armor' not in [
        r['heading_path'][-1] for r in result.source_map
    ]
    for value in (
        'Required by a Wizard',
        'Charges:** 7',
        'Charges Regained:** 1d6 + 1',
        '500 lb.',
        '64 cubic feet',
        'contents add no weight',
    ):
        assert value in result.body
    assert 'Debug metadata' not in result.body


def test_prerequisites_alternatives_and_weighted_ability_choices():
    data = {
        'name': 'Choice',
        '__prop': 'feat',
        'source': 'XPHB',
        'prerequisite': [
            {
                'level': {'level': 2, 'class': {'name': 'Wizard'}},
                'ability': [{'int': 13}, {'wis': 13}],
            },
            {'spellcasting': True, 'feat': ['Alert|XPHB']},
        ],
        'ability': [{'choose': {'weighted': {'from': ['str', 'dex', 'con'], 'weights': [2, 1]}}}],
        'entries': ['Choose deliberately.'],
    }
    result = render_payload(data, 'feat')
    for value in (
        'Wizard Level 2',
        'Intelligence: 13 or Wisdom: 13',
        'Spellcasting',
        'Alert',
        'Strength',
        'Dexterity',
        'Constitution',
        'increases of +2, +1',
    ):
        assert value in result.body


def test_casting_time_alternatives_keep_their_notes():
    from dnd_rag.ingestion.markdown_export.rendering.engine import Engine

    engine = Engine(empty_book())
    assert (
        engine.values.time(
            [
                {'number': 1, 'unit': 'action', 'note': 'Overgrowth'},
                {'number': 8, 'unit': 'hour', 'note': 'Enrichment'},
            ]
        )
        == '1 action (Overgrowth) or 8 hours (Enrichment)'
    )
    assert (
        engine.values.duration([{'type': 'special', 'condition': 'Until the stone stops rolling'}])
        == 'Special (Until the stone stops rolling)'
    )


@pytest.mark.parametrize(
    ('method', 'value', 'code'),
    [
        ('duration', [{'type': 'future', 'rounds': 5}], 'DURATION_FORMAT'),
        (
            'duration',
            [{'type': 'timed', 'duration': {'amount': 1, 'type': 'minute'}, 'newRule': True}],
            'DURATION_FORMAT',
        ),
        ('time', [{'number': 1, 'unit': 'future'}], 'TIME_FORMAT'),
        ('time', [{'number': 1, 'unit': 'action', 'newRule': 'important'}], 'TIME_FORMAT'),
        (
            'spell_range',
            {'type': 'point', 'distance': {'type': 'future', 'amount': 30}},
            'RANGE_FORMAT',
        ),
        (
            'spell_range',
            {'type': 'future', 'distance': {'type': 'feet', 'amount': 30}},
            'RANGE_FORMAT',
        ),
    ],
)
def test_unknown_nested_spell_grammar_fails(method, value, code):
    from dnd_rag.ingestion.markdown_export.rendering.engine import Engine

    engine = Engine(empty_book())
    with pytest.raises(ExportError) as error:
        getattr(engine.values, method)(value)
    assert error.value.code == code


@pytest.mark.parametrize(
    ('prop', 'field', 'value', 'code'),
    [
        ('monster', 'newMechanic', 'Important', 'UNKNOWN_PAYLOAD_FIELD'),
        ('monster', 'hp', {'average': 10, 'newFormula': '2d8'}, 'HP_FORMAT'),
        ('monster', 'initiative', {'newFormula': '2d8'}, 'INITIATIVE_FORMAT'),
        (
            'monster',
            'spellcasting',
            [{'name': 'Magic', 'displayAs': 'unknown'}],
            'SPELLCASTING_POSITION',
        ),
        ('unknownProp', 'entries', ['Important'], 'UNKNOWN_PAYLOAD_TYPE'),
    ],
)
def test_unknown_payload_grammar_fails(fixture_data, prop, field, value, code):
    data = fixture_data('monster') if prop == 'monster' else {'name': 'Unknown', '__prop': prop}
    data[field] = value
    with pytest.raises(ExportError) as error:
        render_payload(data, prop)
    assert error.value.code == code
    assert error.value.context['heading_path'][-1] == data['name']
