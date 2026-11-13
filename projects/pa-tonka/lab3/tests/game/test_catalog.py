import pytest

from dnd_rag.contracts import RagError


def fixture_raw():
    return {
        'monsters': [
            {
                'name': 'Chosen Creature',
                'source': 'XMM',
                'type': {'type': {'choose': ['humanoid', 'undead']}},
                'cr': {'cr': '1/2'},
                'environment': ['forest'],
                'hp': {'average': 10},
                'legendaryGroup': {'name': 'Lair', 'source': 'XMM'},
            }
        ],
        'legendary_groups': [
            {'name': 'Lair', 'source': 'XMM', 'lairActions': ['A real lair action.']}
        ],
        'items': [
            {'name': 'Longsword', 'source': 'XPHB', 'type': 'M', 'rarity': 'none'},
            {
                'name': '+1 Longsword',
                'source': 'XDMG',
                'rarity': 'uncommon',
                'baseItem': 'Longsword|XPHB',
                'genericVariant': {'name': '+1 Weapon', 'source': 'XDMG'},
            },
        ],
        'loot': {
            'individual': [
                {
                    'source': 'DMG',
                    'crMin': 0,
                    'crMax': 4,
                    'table': [{'min': 1, 'max': 100, 'coins': {'gp': '9d6'}}],
                },
                {
                    'source': 'XDMG',
                    'crMin': 0,
                    'crMax': 4,
                    'table': [{'min': 1, 'max': 100, 'coins': {'gp': '3d6'}}],
                },
            ],
            'hoard': [
                {
                    'source': 'XDMG',
                    'crMin': 0,
                    'crMax': 4,
                    'coins': {'gp': '2d4*100'},
                    'table': [
                        {
                            'min': 1,
                            'max': 100,
                            'magicItems': [{'type': 'randomByLevel', 'amount': '1d4-1'}],
                        }
                    ],
                }
            ],
            'magicItems': [
                {
                    'source': 'XDMG',
                    'name': 'Armaments - Uncommon',
                    'type': 'armaments.uncommon',
                    'table': [
                        {'min': 1, 'max': 100, 'choose': {'fromGeneric': ['+1 Weapon|XDMG']}}
                    ],
                },
                {
                    'source': 'XDMG',
                    'name': 'By Level',
                    'type': 'byLevel.1-4',
                    'table': [
                        {'min': 1, 'max': 100, 'choose': {'fromMatching': {'rarity': 'uncommon'}}}
                    ],
                },
            ],
        },
        'xp_by_cr': {'0': 10, '1/2': 100},
        'budgets': {'source': 'XDMG', 'page': 114, 'rows': [['1', '50', '75', '100']]},
    }


def test_compile_preserves_types_cr_links_variants_and_only_2024_tables(tmp_path):
    from dnd_rag.game.catalog import load_catalog
    from dnd_rag.game.prepare import compile_catalog

    path = compile_catalog(fixture_raw(), tmp_path, revision='a' * 40)
    catalog = load_catalog(path)
    monster = catalog.lookup_monsters('Chosen Creature')[0]
    assert (
        monster.creature_types == ['humanoid', 'undead'] and monster.cr == 0.5 and monster.xp == 100
    )
    assert monster.stat_block['legendary_group']['lairActions'] == ['A real lair action.']
    assert catalog.loot_tables['individual'][0]['table'][0]['coins'] == {'gp': '3d6'}
    choices = catalog.loot_tables['magic_items']['armaments.uncommon']['table'][0]['item_ids']
    assert len(choices) == 1 and catalog.items[choices[0]]['name'] == '+1 Longsword'
    first = (path / 'manifest.json').read_bytes()
    compile_catalog(fixture_raw(), tmp_path, revision='a' * 40)
    assert (path / 'manifest.json').read_bytes() == first


def test_unknown_required_reference_and_corrupt_manifest_are_errors(tmp_path):
    from dnd_rag.game.catalog import load_catalog
    from dnd_rag.game.prepare import compile_catalog

    raw = fixture_raw()
    raw['legendary_groups'] = []
    with pytest.raises(RagError, match='legendary'):
        compile_catalog(raw, tmp_path, revision='a' * 40)
    raw = fixture_raw()
    raw['items'] = []
    with pytest.raises(RagError, match='item|variant'):
        compile_catalog(raw, tmp_path, revision='a' * 40)
    path = compile_catalog(fixture_raw(), tmp_path, revision='a' * 40)
    (path / 'items.json').write_text('{}')
    with pytest.raises(RagError, match='hash|manifest'):
        load_catalog(path)


@pytest.mark.parametrize(
    'value,types',
    [
        ('beast', ['beast']),
        ({'type': 'fey', 'tags': ['goblin']}, ['fey']),
        ({'type': {'choose': ['fey', 'humanoid']}}, ['fey', 'humanoid']),
    ],
)
def test_monster_type_shapes_are_searchable(value, types, tmp_path):
    from dnd_rag.game.catalog import load_catalog
    from dnd_rag.game.prepare import compile_catalog

    raw = fixture_raw()
    raw['monsters'][0]['type'] = value
    catalog = load_catalog(compile_catalog(raw, tmp_path, revision='a' * 40))
    for creature_type in types:
        assert len(catalog.lookup_monsters(None, creature_type=creature_type)) == 1
    assert catalog.lookup_monsters('Unknown') == []


def test_item_group_can_reference_generic_variants_without_emitting_placeholder(tmp_path):
    from dnd_rag.game.catalog import load_catalog
    from dnd_rag.game.prepare import compile_catalog

    raw = fixture_raw()
    raw['item_groups'] = [{'name': 'Weapon Group', 'source': 'XDMG', 'items': ['+1 Weapon|XDMG']}]
    raw['loot']['magicItems'][0]['table'][0]['choose']['fromGeneric'] = ['Weapon Group|XDMG']
    catalog = load_catalog(compile_catalog(raw, tmp_path, revision='a' * 40))
    choices = catalog.loot_tables['magic_items']['armaments.uncommon']['table'][0]['item_ids']
    assert [catalog.items[i]['name'] for i in choices] == ['+1 Longsword']


def test_any_habitat_entities_match_concrete_habitats_without_relaxing_other_entities():
    from tests.game.fixtures import catalog

    c = catalog()
    c.monsters['mage'] = c.monsters['mage'].model_copy(update={'habitats': ['any']})
    assert [m.name for m in c.lookup_monsters('Mage', habitat='urban')] == ['Mage']
    assert c.lookup_monsters('Goblin Warrior', habitat='urban') == []
    assert [m.name for m in c.lookup_monsters('Goblin Warrior', habitat='any')] == [
        'Goblin Warrior'
    ]
