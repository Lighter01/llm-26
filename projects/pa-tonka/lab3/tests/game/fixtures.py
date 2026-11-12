from dnd_rag.game.contracts import CatalogSnapshot, Monster, SourceRef


def catalog():
    monsters = {}
    for mid, name, cr, xp, typ, hab in [
        ('mage', 'Mage', 6.0, 2300, 'humanoid', 'forest'),
        ('warrior', 'Goblin Warrior', 0.25, 50, 'fey', 'forest'),
        ('boss', 'Goblin Boss', 1.0, 200, 'fey', 'forest'),
        ('sprite', 'Sprite', 0.25, 50, 'fey', 'forest'),
        ('zombie', 'Zombie', 0.25, 50, 'undead', 'urban'),
    ]:
        monsters[mid] = Monster(
            monster_id=mid,
            name=name,
            cr=cr,
            xp=xp,
            creature_types=[typ],
            habitats=[hab],
            stat_block={'hp': {'average': 10}},
            source=SourceRef(source_id=mid, book_id='XMM', source_file='fixture.json'),
        )
    items = {
        'common': {
            'item_id': 'common',
            'name': 'Potion of Healing',
            'rarity': 'common',
            'source': 'XPHB',
            'source_ref': {'book_id': 'XPHB'},
        },
        'rare': {
            'item_id': 'rare',
            'name': 'Sun Blade',
            'rarity': 'rare',
            'source': 'XDMG',
            'source_ref': {'book_id': 'XDMG'},
        },
    }
    bands = [
        (0, 4, {'gp': '3d6'}, {'gp': '2d4*100'}, '1d4-1'),
        (5, 10, {'gp': '2d8*10'}, {'gp': '8d10*100'}, '1d3'),
        (11, 16, {'pp': '2d10*10'}, {'gp': '8d8*1000'}, '1d4'),
        (17, 30, {'pp': '2d8*100'}, {'gp': '6d10*10000'}, '1d6'),
    ]
    individual = [
        {
            'source': 'XDMG',
            'name': str(lo),
            'crMin': lo,
            'crMax': hi,
            'table': [{'min': 1, 'max': 100, 'coins': coins}],
        }
        for lo, hi, coins, _, _ in bands
    ]
    hoard = [
        {
            'source': 'XDMG',
            'name': str(lo),
            'crMin': lo,
            'crMax': hi,
            'coins': coins,
            'table': [
                {'min': 1, 'max': 100, 'magicItems': [{'type': 'randomByLevel', 'amount': formula}]}
            ],
        }
        for lo, hi, _, coins, formula in bands
    ]
    magic = {
        'byLevel.1-4': {
            'source': 'XDMG',
            'type': 'byLevel.1-4',
            'table': [
                {'min': 1, 'max': 54, 'rarity': 'common'},
                {'min': 55, 'max': 100, 'rarity': 'rare'},
            ],
        },
        'armaments.common': {
            'source': 'XDMG',
            'type': 'armaments.common',
            'table': [{'min': 1, 'max': 100, 'item_ids': ['common']}],
        },
        'armaments.rare': {
            'source': 'XDMG',
            'type': 'armaments.rare',
            'table': [{'min': 1, 'max': 100, 'item_ids': ['rare']}],
        },
    }
    rules = {
        'budgets': {
            '1': {'low': 50, 'moderate': 75, 'high': 100},
            '3': {'low': 150, 'moderate': 225, 'high': 400},
            '6': {'low': 600, 'moderate': 1000, 'high': 1400},
        },
        'xp_by_cr': {str(i): 0 for i in range(31)} | {'1/8': 25, '1/4': 50, '1/2': 100},
    }
    return CatalogSnapshot(
        monsters, items, {'individual': individual, 'hoard': hoard, 'magic_items': magic}, rules, {}
    )


class MinRng:
    def randint(self, a, b):
        return a

    def choice(self, values):
        return values[0]


class MaxRng:
    def randint(self, a, b):
        return b

    def choice(self, values):
        return values[-1]
