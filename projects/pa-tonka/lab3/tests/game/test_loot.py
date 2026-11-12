import pytest

from dnd_rag.contracts import RagError
from tests.game.fixtures import MaxRng, MinRng, catalog


@pytest.mark.parametrize(
    'cr,coins',
    [
        (0, {'gp': 3}),
        (4, {'gp': 3}),
        (5, {'gp': 20}),
        (10, {'gp': 20}),
        (11, {'pp': 20}),
        (16, {'pp': 20}),
        (17, {'pp': 200}),
        (30, {'pp': 200}),
    ],
)
def test_individual_cr_bands_and_one_roll_times_count(cr, coins):
    from dnd_rag.game.loot import generate_loot

    r = generate_loot(catalog(), kind='individual', cr=cr, count=3, rng=MinRng())
    assert r.coins == {k: v * 3 for k, v in coins.items()}
    assert r.items == [] and r.count == 3 and r.rolls


def test_hoard_min_max_and_real_item_metadata():
    from dnd_rag.game.loot import generate_loot

    c = catalog()
    low = generate_loot(
        c, kind='hoard', cr=0, party_level=1, treasure_theme='Armaments', rng=MinRng()
    )
    assert low.coins == {'gp': 200} and low.items == []
    high = generate_loot(
        c, kind='hoard', cr=4, party_level=4, treasure_theme='Armaments', rng=MaxRng()
    )
    assert high.coins == {'gp': 800} and len(high.items) == 3
    assert all(
        i['name'] == 'Sun Blade' and i['rarity'] == 'rare' and i['source'] == 'XDMG'
        for i in high.items
    )
    assert high.total_gp == 800 and len(high.tables) >= 3


def test_missing_hoard_inputs_and_invalid_cr_are_explicit():
    from dnd_rag.game.loot import generate_loot

    for kwargs in [
        {'kind': 'hoard', 'cr': 1},
        {'kind': 'individual', 'cr': 4.5},
        {'kind': 'individual', 'cr': 31},
        {'kind': 'individual', 'cr': 1, 'count': 0},
    ]:
        with pytest.raises(RagError):
            generate_loot(catalog(), **kwargs)
