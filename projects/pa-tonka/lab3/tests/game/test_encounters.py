import pytest

from dnd_rag.contracts import RagError
from tests.game.fixtures import catalog


def test_2024_arithmetic_and_boundaries():
    from dnd_rag.game.encounters import evaluate_encounter

    c = catalog()
    r = evaluate_encounter(
        c, party_size=4, party_level=6, monsters=[{'monster_id': 'mage', 'count': 2}]
    )
    assert r.total_xp == 4600 and r.budgets == {'low': 2400, 'moderate': 4000, 'high': 5600}
    assert r.difficulty == 'high' and not r.exceeds_high
    for mid, count, xp, label in [
        ('boss', 1, 200, 'low'),
        ('warrior', 6, 300, 'moderate'),
        ('boss', 2, 400, 'high'),
        ('mage', 1, 2300, 'above_high'),
    ]:
        r = evaluate_encounter(
            c, party_size=4, party_level=1, monsters=[{'monster_id': mid, 'count': count}]
        )
        assert r.total_xp == xp and r.difficulty == label


def test_build_preserves_required_counts_and_filters():
    from dnd_rag.game.encounters import build_encounter

    r = build_encounter(
        catalog(),
        party_size=4,
        party_level=3,
        difficulty='moderate',
        habitat='forest',
        creature_type='fey',
        total_count=4,
        required_monsters=[{'monster_id': 'warrior', 'count': 1}],
    )
    assert r.status == 'success' and r.difficulty == 'moderate' and 600 < r.total_xp <= 900
    assert sum(m['count'] for m in r.monsters) == 4
    assert next(m['count'] for m in r.monsters if m['monster_id'] == 'warrior') == 1
    assert all('fey' in m['creature_types'] and 'forest' in m['habitats'] for m in r.monsters)


@pytest.mark.parametrize(
    'changes',
    [
        {'creature_type': 'undead'},
        {'total_count': 0},
        {'required_monsters': [{'monster_id': 'mage', 'count': 1}]},
    ],
)
def test_build_never_silently_relaxes_conflicts(changes):
    from dnd_rag.game.encounters import build_encounter

    args = {
        'party_size': 4,
        'party_level': 1,
        'difficulty': 'low',
        'total_count': 1,
        'required_monsters': [{'monster_id': 'warrior', 'count': 1}],
        **changes,
    }
    try:
        r = build_encounter(catalog(), **args)
    except RagError:
        return
    assert r.status == 'conflict' and r.error


def test_search_exhaustion_is_distinct_and_invalid_party_is_rejected():
    from dnd_rag.game.encounters import build_encounter, evaluate_encounter

    r = build_encounter(
        catalog(), party_size=1, party_level=6, difficulty='high', habitat='underwater'
    )
    assert r.status == 'search_exhausted' and r.error['code'] == 'search_exhausted'
    with pytest.raises(RagError):
        evaluate_encounter(
            catalog(), party_size=0, party_level=6, monsters=[{'monster_id': 'mage', 'count': 2}]
        )
