"""Actual random XDMG2024 money and themed concrete magic items."""

import math
import random
import re
from fractions import Fraction

from dnd_rag.contracts import RagError
from dnd_rag.game.contracts import LootResult


def generate_loot(catalog, *, kind, cr, count=1, party_level=None, treasure_theme=None, rng=None):
    rng = rng or random.Random()
    try:
        rating = float(Fraction(str(cr)))
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise RagError('invalid_cr', 'CR must be a standard catalog CR') from exc
    allowed = {float(Fraction(v)) for v in catalog.encounter_rules['xp_by_cr']}
    if not math.isfinite(rating) or rating not in allowed:
        raise RagError('invalid_cr', 'CR must be a standard catalog CR0..30')
    if kind not in ('individual', 'hoard'):
        raise RagError('invalid_loot_kind', 'kind must be individual or hoard')
    if type(count) is not int or count < 1:
        raise RagError('invalid_count', 'count must be positive')
    if kind == 'hoard' and count != 1:
        raise RagError(
            'invalid_count',
            'A hoard uses one explicitly identified owner CR; count is individual-only',
        )
    if kind == 'hoard' and (
        type(party_level) is not int or not 1 <= party_level <= 20 or not treasure_theme
    ):
        raise RagError(
            'missing_parameter',
            'Hoard requires party_level1..20 and treasure_theme Arcana/Armaments/Implements/Relics',
        )
    theme = treasure_theme.casefold() if treasure_theme else None
    if theme and theme not in ('arcana', 'armaments', 'implements', 'relics'):
        raise RagError('invalid_theme', 'Unknown XDMG treasure theme')
    bands = catalog.loot_tables[kind]
    selected = next((t for t in bands if t['crMin'] <= rating <= t['crMax']), None)
    if selected is None:
        raise RagError('invalid_catalog', 'Missing treasure CR band')
    rolls = []
    tables = [{k: selected[k] for k in ['name', 'source', 'page'] if k in selected}]

    def roll(formula):
        match = re.fullmatch(r'(\d+)d(\d+)(?:\*(\d+))?(?:([+-])(\d+))?', formula.replace(' ', ''))
        if not match:
            raise RagError('invalid_catalog', 'Unsupported dice expression: ' + formula)
        n, sides, mul, sign, offset = match.groups()
        dice = [rng.randint(1, int(sides)) for _ in range(int(n))]
        value = sum(dice) * int(mul or 1) + (int(offset or 0) * (-1 if sign == '-' else 1))
        rolls.append({'formula': formula, 'dice': dice, 'value': value})
        return value

    def row_from(table):
        number = rng.randint(1, 100)
        rolls.append(
            {'formula': '1d100', 'value': number, 'table': table.get('type', table.get('name'))}
        )
        try:
            return next(r for r in table['table'] if r['min'] <= number <= r['max'])
        except StopIteration as exc:
            raise RagError('invalid_catalog', 'Incomplete d100 table') from exc

    row = row_from(selected)
    coin_formulas = row['coins'] if kind == 'individual' else selected['coins']
    coins = {
        denomination: roll(formula) * (count if kind == 'individual' else 1)
        for denomination, formula in coin_formulas.items()
    }
    items = []
    if kind == 'hoard':
        level_range = next(
            label
            for lo, hi, label in [
                (1, 4, '1-4'),
                (5, 10, '5-10'),
                (11, 16, '11-16'),
                (17, 20, '17-20'),
            ]
            if lo <= party_level <= hi
        )
        by_level = catalog.loot_tables['magic_items'].get('byLevel.' + level_range)
        if not by_level:
            raise RagError('invalid_catalog', 'Missing rarity-by-level table')
        for spec in row.get('magicItems', []):
            if spec['type'] != 'randomByLevel':
                raise RagError('invalid_catalog', 'Unsupported hoard selection')
            for _ in range(roll(spec['amount'])):
                rarity = row_from(by_level)['rarity']
                table = catalog.loot_tables['magic_items'].get(theme + '.' + rarity)
                if table is None:
                    raise RagError('invalid_catalog', 'Missing theme/rarity table')
                choice = row_from(table)
                iid = rng.choice(choice['item_ids'])
                item = catalog.items[iid]
                items.append(
                    {k: item[k] for k in ['item_id', 'name', 'rarity', 'source', 'source_ref']}
                )
                tables.extend(
                    [
                        {k: t[k] for k in ['type', 'name', 'source', 'page'] if k in t}
                        for t in [by_level, table]
                    ]
                )
    total_gp = sum(
        value * {'cp': 0.01, 'sp': 0.1, 'ep': 0.5, 'gp': 1, 'pp': 10}[denom]
        for denom, value in coins.items()
    )
    return LootResult(
        kind=kind,
        cr=rating,
        count=count,
        coins=coins,
        total_gp=float(total_gp),
        items=items,
        rolls=rolls,
        tables=tables,
    )
