"""Read only complete compatible snapshots; search one shared entity catalog."""

import json
from hashlib import sha256
from pathlib import Path

from dnd_rag.contracts import RagError
from dnd_rag.game.contracts import CatalogSnapshot, Monster


def load_catalog(snapshot_dir: Path):
    try:
        manifest = json.loads((snapshot_dir / 'manifest.json').read_text())
        if manifest['schema_version'] != 1 or len(manifest['source_revision']) != 40:
            raise ValueError('Incompatible manifest')
        data = {}
        for name in ['monsters', 'items', 'loot_tables', 'encounter_rules']:
            raw = (snapshot_dir / f'{name}.json').read_bytes()
            if sha256(raw).hexdigest() != manifest['files'][f'{name}.json']:
                raise ValueError('Catalog file hash disagrees with manifest: ' + name)
            data[name] = json.loads(raw)
        monsters = {key: Monster.model_validate(value) for key, value in data['monsters'].items()}
        if not monsters or not data['items']:
            raise ValueError('Empty catalog')
        return CatalogSnapshot(
            monsters, data['items'], data['loot_tables'], data['encounter_rules'], manifest
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RagError('invalid_catalog', f'{snapshot_dir}: {exc}') from exc


def matches_habitat(habitats, requested):
    if not requested or requested.casefold() == 'any':
        return True
    normalized = {h.casefold() for h in habitats}
    return 'any' in normalized or requested.casefold() in normalized


def lookup_monsters(catalog, query=None, *, habitat=None, creature_type=None, limit=5):
    if type(limit) is not int or not 1 <= limit <= 10:
        raise RagError('invalid_limit', 'Monster limit must be1..10')
    values = list(catalog.monsters.values())
    if query:
        exact = [
            m for m in values if m.monster_id == query or m.name.casefold() == query.casefold()
        ]
        values = exact or [m for m in values if query.casefold() in m.name.casefold()]
    if habitat:
        values = [m for m in values if matches_habitat(m.habitats, habitat)]
    if creature_type:
        values = [m for m in values if creature_type.casefold() in m.creature_types]
    return sorted(values, key=lambda m: m.name)[:limit]


def resolve_monster(catalog, selector):
    if selector in catalog.monsters:
        return catalog.monsters[selector]
    found = catalog.lookup_monsters(selector, limit=10)
    if not found:
        raise RagError('unknown_monster', f'Unknown monster: {selector}')
    if len(found) > 1:
        raise RagError(
            'ambiguous_monster',
            f'Ambiguous monster: {selector}',
            {'candidates': [{'monster_id': m.monster_id, 'name': m.name} for m in found]},
        )
    return found[0]
