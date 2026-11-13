"""2024 XP sums and bounded constrained search; no 2014 multipliers."""

from collections import Counter
from itertools import zip_longest

from pydantic import ValidationError

from dnd_rag.contracts import RagError
from dnd_rag.game.catalog import matches_habitat
from dnd_rag.game.contracts import EncounterResult, MonsterCount


def party_budgets(catalog, party_size, party_level):
    if (
        type(party_size) is not int
        or party_size < 1
        or type(party_level) is not int
        or not 1 <= party_level <= 20
    ):
        raise RagError('invalid_party', 'party_size must be positive and common party_level1..20')
    try:
        return {
            k: v * party_size
            for k, v in catalog.encounter_rules['budgets'][str(party_level)].items()
        }
    except KeyError as exc:
        raise RagError('invalid_catalog', 'Missing XP budgets for party level') from exc


def normalize_counts(catalog, monsters):
    counts = Counter()
    try:
        for entry in monsters:
            item = entry if isinstance(entry, MonsterCount) else MonsterCount.model_validate(entry)
            monster = catalog.resolve_monster(item.monster_id)
            counts[monster.monster_id] += item.count
    except (ValidationError, TypeError) as exc:
        raise RagError('invalid_encounter', str(exc)) from exc
    return counts


def evaluate_encounter(catalog, *, party_size, party_level, monsters):
    budgets = party_budgets(catalog, party_size, party_level)
    counts = normalize_counts(catalog, monsters)
    if not counts:
        raise RagError('invalid_encounter', 'At least one monster is required')
    lines = []
    for mid, count in sorted(counts.items()):
        m = catalog.monsters[mid]
        lines.append(
            {
                'monster_id': mid,
                'name': m.name,
                'count': count,
                'cr': m.cr,
                'xp_each': m.xp,
                'xp': m.xp * count,
                'creature_types': m.creature_types,
                'habitats': m.habitats,
                'source': m.source.model_dump(mode='json'),
            }
        )
    xp = sum(line['xp'] for line in lines)
    difficulty = next(
        (level for level in ['low', 'moderate', 'high'] if xp <= budgets[level]), 'above_high'
    )
    return EncounterResult(
        party_size=party_size,
        party_level=party_level,
        monsters=lines,
        total_xp=xp,
        budgets=budgets,
        difficulty=difficulty,
        exceeds_high=xp > budgets['high'],
    )


def build_encounter(
    catalog,
    *,
    party_size,
    party_level,
    difficulty,
    habitat=None,
    creature_type=None,
    total_count=None,
    required_monsters=(),
    rng=None,
    max_attempts=256,
    max_creature_types=3,
    auto_count_limit=12,
):
    budgets = party_budgets(catalog, party_size, party_level)
    if difficulty not in budgets:
        raise RagError('invalid_difficulty', 'difficulty must be low, moderate or high')
    if total_count is not None and (type(total_count) is not int or total_count < 1):
        raise RagError('invalid_count', 'total_count must be positive')
    required = normalize_counts(catalog, required_monsters)
    constraints = {
        'habitat': habitat,
        'creature_type': creature_type,
        'total_count': total_count,
        'required_monsters': dict(required),
        'max_attempts': max_attempts,
        'max_creature_types': max_creature_types,
        'auto_count_limit': min(auto_count_limit, 2 * party_size),
    }

    def matches(m):
        return matches_habitat(m.habitats, habitat) and (
            not creature_type or creature_type.casefold() in m.creature_types
        )

    def failure(status, message):
        return EncounterResult(
            status=status,
            party_size=party_size,
            party_level=party_level,
            budgets=budgets,
            target_budget=budgets[difficulty],
            constraints=constraints,
            error={'code': status, 'message': message},
        )

    if any(not matches(catalog.monsters[mid]) for mid in required):
        return failure('conflict', 'A required monster conflicts with habitat/type filters')
    required_count = sum(required.values())
    required_xp = sum(catalog.monsters[mid].xp * n for mid, n in required.items())
    if total_count is not None and required_count > total_count:
        return failure('conflict', 'Required counts exceed total_count')
    if required_xp > budgets[difficulty]:
        return failure('conflict', 'Required monsters exceed the selected XP budget')
    counts = (
        [total_count]
        if total_count
        else list(range(max(1, required_count), min(auto_count_limit, 2 * party_size) + 1))
    )
    if not counts:
        return failure(
            'conflict', 'Required count exceeds automatic count range; specify total_count'
        )
    pool = [
        m
        for m in catalog.monsters.values()
        if m.monster_id not in required
        and matches(m)
        and 0 < m.xp <= budgets[difficulty] - required_xp
    ]

    def forms(n):
        remaining = n - required_count
        if remaining == 0:
            yield dict(required)
            return
        if remaining < 0:
            return
        ordered = sorted(
            pool,
            key=lambda m: (abs(m.xp - (budgets[difficulty] - required_xp) / remaining), m.name),
        )
        # Interleave counts so a large catalog cannot consume the whole budget at n=1.
        for m in ordered[:12]:
            yield {**required, m.monster_id: remaining}
        if remaining >= 2 and len(required) <= max_creature_types - 2:
            for a in ordered[:4]:
                for na in range(1, remaining):
                    target = (budgets[difficulty] - required_xp - a.xp * na) / (remaining - na)
                    others = sorted(
                        (m for m in pool if m.monster_id != a.monster_id),
                        key=lambda m: (abs(m.xp - target), m.name),
                    )[:3]
                    for b in others:
                        yield {**required, a.monster_id: na, b.monster_id: remaining - na}
        if remaining >= 3 and len(required) <= max_creature_types - 3:
            for a in ordered[:3]:
                for b in ordered[:4]:
                    if a.monster_id == b.monster_id:
                        continue
                    target = (budgets[difficulty] - required_xp - a.xp - b.xp) / (remaining - 2)
                    rest = sorted(
                        (m for m in pool if m.monster_id not in (a.monster_id, b.monster_id)),
                        key=lambda m: (abs(m.xp - target), m.name),
                    )[:2]
                    for c in rest:
                        yield {
                            **required,
                            a.monster_id: 1,
                            b.monster_id: 1,
                            c.monster_id: remaining - 2,
                        }

    best = None
    attempts = 0
    seen = set()
    for round_forms in zip_longest(*(forms(n) for n in counts)):
        for composition in round_forms:
            if composition is None or len(composition) > max_creature_types:
                continue
            key = tuple(sorted(composition.items()))
            if key in seen:
                continue
            seen.add(key)
            attempts += 1
            result = evaluate_encounter(
                catalog,
                party_size=party_size,
                party_level=party_level,
                monsters=[{'monster_id': mid, 'count': n} for mid, n in composition.items()],
            )
            if result.difficulty == difficulty and (
                best is None or result.total_xp > best.total_xp
            ):
                best = result
            if attempts >= max_attempts or (best and best.total_xp == budgets[difficulty]):
                break
        if attempts >= max_attempts or (best and best.total_xp == budgets[difficulty]):
            break
    constraints['attempts'] = attempts
    if best:
        return best.model_copy(
            update={'target_budget': budgets[difficulty], 'constraints': constraints}
        )
    return failure(
        'search_exhausted',
        'No matching composition was found within the bounded search; this is not a proof of impossibility',
    )
