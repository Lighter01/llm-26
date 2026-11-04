"""Mechanics present outside narrative text remain visible and exact."""

import pytest

from dnd_rag.ingestion.markdown_export import render_book
from dnd_rag.ingestion.markdown_export.rendering.engine import Engine
from helpers import add_entity, empty_book


@pytest.mark.parametrize(
    ('bonus', 'expected'), [('+8', '18'), ('-2', '8'), ('PB + 2', '10 + (PB + 2)'), (None, '12')]
)
def test_missing_passive_uses_perception_bonus_before_wisdom(fixture_data, bonus, expected):
    data = fixture_data('monster')
    data.pop('passive')
    if bonus is None:
        data['skill'].pop('perception')
    else:
        data['skill']['perception'] = bonus
    book = empty_book('XMM')
    add_entity(book, data, 'monster', insertion=True)
    assert 'Passive Perception ' + expected in render_book(book).body


@pytest.mark.parametrize(
    ('material', 'expected'),
    [
        (True, 'M'),
        ('a pearl', 'M (a pearl)'),
        ({'text': 'a pearl', 'cost': 10000, 'consume': True}, 'M (a pearl; 100 GP; consumed)'),
        (
            {
                'text': 'a pearl worth 1,000+ GP, which the spell consumes',
                'cost': 100000,
                'consume': True,
            },
            'M (a pearl worth 1,000+ GP, which the spell consumes)',
        ),
        ({'text': 'an herb', 'consume': 'optional'}, 'M (an herb; optionally consumed)'),
        ({'text': 'a weapon worth at least 1 CP', 'cost': 1}, 'M (a weapon worth at least 1 CP)'),
        ({'text': 'a pearl worth 10 SP', 'cost': 100}, 'M (a pearl worth 10 SP)'),
    ],
)
def test_material_component_variants_preserve_cost_and_consumption(material, expected):
    engine = Engine(empty_book())
    data = {
        'name': 'Test Spell',
        'level': 1,
        'school': 'V',
        'time': [{'number': 1, 'unit': 'action'}],
        'range': {'type': 'point', 'distance': {'type': 'touch'}},
        'components': {'m': material},
        'duration': [{'type': 'instant'}],
        'entries': ['Rules.'],
    }
    engine.payloads.spell(data, 2, structural=True)
    assert '**Components:** ' + expected + '\n' in ''.join(engine.doc.parts)


@pytest.mark.parametrize(
    'speed',
    [
        {'walk': 30, 'fly': 60, 'canHover': True},
        {'walk': 30, 'fly': {'number': 60, 'condition': '(hover)'}, 'canHover': True},
    ],
)
def test_hover_flag_is_visible_once(speed):
    engine = Engine(empty_book())
    assert engine.values.speed(speed) == '30 ft., Fly 60 ft. (hover)'


@pytest.mark.parametrize(('category', 'class_name'), [('FS:P', 'Paladin'), ('FS:R', 'Ranger')])
def test_fighting_style_category_and_structured_prerequisite_are_readable(category, class_name):
    book = empty_book()
    add_entity(
        book,
        {
            'name': 'Warrior Option',
            '__prop': 'feat',
            'category': category,
            'prerequisite': [
                {
                    'otherSummary': {
                        'entry': f'When Gaining the Level 2 {class_name} Feature',
                        'entrySummary': 'Special',
                    }
                }
            ],
            'entries': ['Rules.'],
        },
        'feat',
        insertion=True,
    )
    result = render_book(book)
    assert '**Category:** Fighting Style Replacement (' + class_name + ')' in result.body
    assert '**Prerequisite:** When Gaining the Level 2 ' + class_name + ' Feature' in result.body
    assert category not in result.body and 'Other Summary' not in result.body


@pytest.mark.parametrize(
    ('code', 'label'),
    [('PB', 'Pact Boon'), ('FS:P', 'Fighting Style; Paladin'), ('FS:R', 'Fighting Style; Ranger')],
)
def test_nested_feature_access_uses_native_feature_type_labels(code, label):
    engine = Engine(empty_book())
    assert engine.values.structure({'featureType': [code]}) == 'Feature Type: ' + label
