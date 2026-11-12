"""Deterministic compilation of the pinned local 5etools snapshot, never on tool call."""

import copy
import json
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

from dnd_rag.contracts import RagError
from dnd_rag.game.contracts import Monster, SourceRef

ALLOWED = {'XPHB', 'XDMG', 'XMM'}


def entity_id(kind, source, name):
    return f'{source}:{kind}:' + sha256(name.casefold().encode()).hexdigest()[:16]


def source_ref(kind, entry, revision, file):
    return SourceRef(
        source_id=f'5etools:{revision}:{entry["source"]}:{kind}:{entry["name"]}',
        book_id=entry['source'],
        source_file=file,
        provenance={k: entry[k] for k in ['page', 'baseItem', 'genericVariant'] if k in entry},
    )


def creature_types(value):
    if isinstance(value, str):
        return [value.casefold()]
    if isinstance(value, dict):
        if 'choose' in value:
            return sorted({v.casefold() for v in value['choose']})
        if 'type' in value:
            return creature_types(value['type'])
    raise RagError('invalid_game_source', 'Unsupported monster type')


def compile_catalog(raw, output_root, *, revision):
    if not re.fullmatch('[a-f0-9]{40}', revision):
        raise RagError('invalid_game_source', 'Expected pinned source SHA')
    monsters = {}
    items = {}
    groups = {
        (g['name'], g['source']): g for g in raw['legendary_groups'] if g['source'] in ALLOWED
    }
    for value in raw['monsters']:
        if value.get('source') != 'XMM':
            continue
        m = copy.deepcopy(value)
        cr = m.get('cr')
        cr_data = cr if isinstance(cr, dict) else {}
        cr = cr_data.get('cr', cr)
        try:
            rating = float(Fraction(cr))
            xp = cr_data.get('xp', raw['xp_by_cr'][str(cr)])
        except (ValueError, TypeError, KeyError) as exc:
            raise RagError('invalid_game_source', f'Unknown CR: {cr}') from exc
        if m.get('legendaryGroup'):
            key = (m['legendaryGroup']['name'], m['legendaryGroup']['source'])
            if key not in groups:
                raise RagError('missing_reference', f'Missing legendary group: {key}')
            m['legendary_group'] = groups[key]
        mid = entity_id('monster', m['source'], m['name'])
        monsters[mid] = Monster(
            monster_id=mid,
            name=m['name'],
            cr=rating,
            xp=xp,
            creature_types=creature_types(m['type']),
            habitats=[h.casefold() for h in m.get('environment', [])],
            stat_block=m,
            source=source_ref('monster', m, revision, 'data/bestiary/bestiary-xmm.json'),
        ).model_dump(mode='json')
    groups_items = {
        (g['name'].casefold(), g['source'].casefold()): g
        for g in raw.get('item_groups', [])
        if g['source'] in ALLOWED
    }
    for entry in raw['items']:
        if (
            entry.get('source') not in ALLOWED
            or (entry['name'].casefold(), entry['source'].casefold()) in groups_items
        ):
            continue
        # Generic templates are resolved into concrete approved base-item variants.
        if (
            entry.get('_category') == 'Generic Variant'
            or entry.get('type', '').split('|')[0] == 'GV'
        ):
            continue
        iid = entity_id('item', entry['source'], entry['name'])
        if iid in items:
            raise RagError('invalid_game_source', 'Duplicate concrete item ' + entry['name'])
        items[iid] = {
            **entry,
            'item_id': iid,
            'source_ref': source_ref(
                'item',
                entry,
                revision,
                'data/magicvariants.json'
                if entry.get('genericVariant')
                else 'data/items-base.json'
                if entry.get('_category') == 'Basic'
                else 'data/items.json',
            ).model_dump(mode='json'),
        }
    by_uid = {(i['name'].casefold(), i['source'].casefold()): key for key, i in items.items()}

    def resolve_choices(uid, seen=()):
        parts = uid.split('|')
        name = parts[0]
        source = parts[1] if len(parts) > 1 else 'XDMG'
        key = (name.casefold(), source.casefold())
        if key in seen:
            raise RagError('missing_reference', 'Cyclic item reference: ' + uid)
        if key in groups_items:
            members = groups_items[key].get('items', [])
            return [iid for member in members for iid in resolve_choices(member, (*seen, key))]
        if key in by_uid:
            return [by_uid[key]]
        matches = [
            iid
            for iid, item in items.items()
            if item.get('genericVariant', {}).get('name', item.get('_variantName', '')).casefold()
            == name.casefold()
            and item['source'].casefold() == source.casefold()
        ]
        if not matches:
            raise RagError('missing_reference', 'Missing item/variant: ' + uid)
        return matches

    magic = {}
    for original in raw['loot']['magicItems']:
        if original.get('source') != 'XDMG':
            continue
        t = copy.deepcopy(original)
        for row in t['table']:
            choose = row.get('choose', {})
            if t['type'].startswith('byLevel.'):
                if set(choose) != {'fromMatching'} or set(choose['fromMatching']) != {'rarity'}:
                    raise RagError('invalid_game_source', 'Unsupported rarity selector')
                row['rarity'] = choose['fromMatching']['rarity']
                continue
            pool = []
            if 'fromItems' in choose:
                pool = [iid for uid in choose['fromItems'] for iid in resolve_choices(uid)]
            elif 'fromGeneric' in choose:
                pool = [iid for uid in choose['fromGeneric'] for iid in resolve_choices(uid)]
            elif choose:
                raise RagError('invalid_game_source', 'Unsupported magic item row: ' + str(choose))
            elif 'item' in row:
                match = re.search(r'\{@item ([^}]+)\}', row['item'])
                if not match:
                    raise RagError('invalid_game_source', 'Missing concrete item tag')
                pool = resolve_choices(match.group(1))
            if not pool:
                raise RagError('missing_reference', 'Empty item pool: ' + t['name'])
            row['item_ids'] = sorted(set(pool))
        # Every percentile must resolve, never silently drop an unsupported row.
        covered = [n for row in t['table'] for n in range(row['min'], row['max'] + 1)]
        if sorted(covered) != list(range(1, 101)):
            raise RagError('invalid_game_source', 'Incomplete/overlapping d100 table: ' + t['name'])
        magic[t['type']] = t
    loot = {
        'individual': [t for t in raw['loot']['individual'] if t.get('source') == 'XDMG'],
        'hoard': [t for t in raw['loot']['hoard'] if t.get('source') == 'XDMG'],
        'magic_items': magic,
    }
    budget = raw['budgets']
    budgets = {
        str(row[0]): {
            k: int(str(v).replace(',', '')) for k, v in zip(['low', 'moderate', 'high'], row[1:])
        }
        for row in budget['rows']
    }
    rules = {
        'source': 'XDMG',
        'page': budget.get('page'),
        'budgets': budgets,
        'xp_by_cr': raw['xp_by_cr'],
        'multiplier': 1,
    }
    data = {'monsters': monsters, 'items': items, 'loot_tables': loot, 'encounter_rules': rules}
    target = output_root / revision
    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, doc in data.items():
        content = (json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()
        hashes[name + '.json'] = sha256(content).hexdigest()
        temp = target / (name + '.json.tmp')
        temp.write_bytes(content)
        temp.replace(target / (name + '.json'))
    manifest = {
        'schema_version': 1,
        'compiler_version': 1,
        'source_revision': revision,
        'files': hashes,
        'inputs': raw.get('inputs', []),
        'counts': {'monsters': len(monsters), 'items': len(items), 'magic_tables': len(magic)},
    }
    temp = target / 'manifest.json.tmp'
    temp.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    temp.replace(target / 'manifest.json')
    return target


def prepare_game_catalog(source_root: Path, output_root: Path):
    root = Path(__file__).resolve().parents[3]
    node = shutil.which('node') or str(root / 'tools/ingestion/node_modules/.bin/node')
    try:
        revision = subprocess.check_output(
            ['git', '-C', str(source_root), 'rev-parse', 'HEAD'], text=True
        ).strip()
        with tempfile.TemporaryDirectory(prefix='lab3-catalog-') as directory:
            output = Path(directory) / 'source.json'
            result = subprocess.run(
                [
                    node,
                    str(Path(__file__).with_name('prepare_5etools.mjs')),
                    str(source_root.resolve()),
                    str(output),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode:
                raise RagError('game_prepare_failed', result.stderr[-3000:])
            raw = json.loads(output.read_text())
            raw['inputs'] = {
                name: sha256((source_root / name).read_bytes()).hexdigest()
                for name in raw.get('inputs', [])
            }
        return compile_catalog(raw, output_root, revision=revision)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise RagError('game_prepare_failed', str(exc)) from exc
