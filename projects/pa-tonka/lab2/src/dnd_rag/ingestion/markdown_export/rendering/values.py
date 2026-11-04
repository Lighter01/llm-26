"""Human representations of structured game values, not JSON serialization."""

import re

from ..common.model import require
from .inline import ABILITIES, split_pipes

SIZES = {'T': 'Tiny', 'S': 'Small', 'M': 'Medium', 'L': 'Large', 'H': 'Huge', 'G': 'Gargantuan'}
ALIGNMENTS = {
    'L': 'Lawful',
    'N': 'Neutral',
    'C': 'Chaotic',
    'G': 'Good',
    'E': 'Evil',
    'U': 'Unaligned',
    'A': 'Any Alignment',
    'NX': 'Neutral',
    'NY': 'Neutral',
}
DAMAGE = dict(
    zip(
        ('A', 'B', 'C', 'F', 'O', 'L', 'N', 'P', 'I', 'Y', 'R', 'S', 'T'),
        (
            'Acid',
            'Bludgeoning',
            'Cold',
            'Fire',
            'Force',
            'Lightning',
            'Necrotic',
            'Piercing',
            'Poison',
            'Psychic',
            'Radiant',
            'Slashing',
            'Thunder',
        ),
    )
)
SCHOOLS = {
    'A': 'Abjuration',
    'C': 'Conjuration',
    'D': 'Divination',
    'E': 'Enchantment',
    'V': 'Evocation',
    'I': 'Illusion',
    'N': 'Necromancy',
    'T': 'Transmutation',
}
CATEGORIES = {
    'O': 'Origin',
    'G': 'General',
    'FS': 'Fighting Style',
    'EB': 'Epic Boon',
    'FS:P': 'Fighting Style Replacement (Paladin)',
    'FS:R': 'Fighting Style Replacement (Ranger)',
}
FEATURE_TYPES = {
    'EI': 'Eldritch Invocation',
    'MM': 'Metamagic',
    'MV:B': 'Battle Master Maneuver',
    'FS:F': 'Fighting Style',
    'FS:B': 'Fighting Style',
    'ED': 'Elemental Discipline',
    'FS:P': 'Fighting Style; Paladin',
    'FS:R': 'Fighting Style; Ranger',
    'PB': 'Pact Boon',
}
ITEM_TYPES = {
    'M': 'Melee Weapon',
    'R': 'Ranged Weapon',
    'LA': 'Light Armor',
    'MA': 'Medium Armor',
    'HA': 'Heavy Armor',
    'S': 'Shield',
    'GV': 'Magic Item Variant',
    'A': 'Ammunition',
    'P': 'Potion',
    'RG': 'Ring',
    'RD': 'Rod',
    'SC': 'Scroll',
    'SCF': 'Spellcasting Focus',
    'WD': 'Wand',
    'G': 'Adventuring Gear',
    'T': 'Tools',
    'INS': 'Instrument',
}
ITEM_PROPERTIES = {
    'A': 'Ammunition',
    'AF': 'Ammunition (Firearm)',
    'BF': 'Burst Fire',
    'F': 'Finesse',
    'H': 'Heavy',
    'L': 'Light',
    'LD': 'Loading',
    'R': 'Reach',
    'RLD': 'Reload',
    'S': 'Special',
    'T': 'Thrown',
    '2H': 'Two-Handed',
    'V': 'Versatile',
}
LABELS = {
    'any': 'any',
    'anySkill': 'any skill',
    'anyTool': 'any tool',
    'anyLanguage': 'any language',
    'anyProficientSkill': 'any proficient skill',
    'proficiency': 'Proficiency Bonus',
    'spellcasting': 'Spellcasting',
    'innate': 'Innate Spells',
    'known': 'Spells Known',
    'prepared': 'Prepared Spells',
    'expanded': 'Expanded Spell List',
    'daily': 'per day',
    'rest': 'per rest',
    'restLong': 'per Long Rest',
    'ritual': 'Ritual',
    'will': 'At will',
    'limited': 'Total uses',
    's6': 'Spell level 6',
    's7': 'Spell level 7',
    's8': 'Spell level 8',
    's9': 'Spell level 9',
    'crMin': 'Minimum CR',
    'crMax': 'Maximum CR',
    'spellcastingFocus': 'Spellcasting Focus',
    'spellcasting2020': 'Spellcasting',
    'pactMagic': 'Pact Magic',
    'level': 'Level',
    'race': 'Species',
    'class': 'Class',
    'all': 'All matching spells',
    'choose': 'Choose',
    'amount': 'Amount',
    'exact': 'Exactly',
    'min': 'Minimum',
    'max': 'Maximum',
    'count': 'Number',
    'weightless': 'Contents add no weight',
    'item': 'Item',
    'uid': 'Reference',
    'fromClassList': 'Classes',
    'fromSubclass': 'Subclasses',
    'fromClassListVariant': 'Additional Classes',
    'type': 'Type',
    'note': 'Note',
}


class Values:
    def __init__(self, engine):
        self.engine = engine

    @property
    def inline(self):
        return self.engine.inline

    def label(self, key):
        if key in ABILITIES:
            return ABILITIES[key]
        if key in LABELS:
            return LABELS[key]
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', str(key)).replace('_', ' ')
        return text[:1].upper() + text[1:]

    def uid(self, value, *, source=False):
        if not isinstance(value, str):
            return self.structure(value)
        parts = split_pipes(value)
        name = parts[0].removesuffix('#c').removesuffix('#i')
        result = self.inline(name[:1].upper() + name[1:])
        if (
            source
            and len(parts) > 1
            and parts[1]
            and parts[1].casefold() != self.engine.domain.id.casefold()
        ):
            result += ' (' + self.inline(parts[1].upper()) + ')'
        return result

    def definition(self, uid, prop):
        parts = split_pipes(uid)
        source = parts[1].casefold() if len(parts) > 1 else None
        matches = []
        for entity in self.engine.domain.entities.values():
            if entity['prop'] != prop:
                continue
            data = self.engine.domain.payload(entity)
            code = data.get('abbreviation', data.get('name'))
            if (
                code
                and code.casefold() == parts[0].casefold()
                and (source is None or data['source'].casefold() == source)
            ):
                name = data.get('name') or next(
                    (
                        entry.get('name')
                        for entry in data.get('entries', [])
                        if isinstance(entry, dict) and entry.get('name')
                    ),
                    None,
                )
                if name:
                    matches.append(name)
        if len(set(matches)) == 1:
            return self.inline(matches[0])
        if prop == 'itemProperty' and parts[0] in ITEM_PROPERTIES:
            return ITEM_PROPERTIES[parts[0]]
        return self.uid(uid, source=True)

    def ability(self, value):
        return (
            ' or '.join(self.structure(option) for option in value)
            if isinstance(value, list)
            else self.structure(value)
        )

    def item_type(self, uid):
        parts = split_pipes(uid)
        code = parts[0]
        source = parts[1].casefold() if len(parts) > 1 else None
        for entity in self.engine.domain.entities.values():
            if entity['prop'] != 'itemType':
                continue
            data = self.engine.domain.payload(entity)
            if data.get('abbreviation') == code and (
                source is None or data.get('source', '').casefold() == source
            ):
                name = data.get('name') or next(
                    (
                        e.get('name')
                        for e in data.get('entries', [])
                        if isinstance(e, dict) and e.get('name')
                    ),
                    None,
                )
                if name:
                    return self.inline(name)
        return ITEM_TYPES.get(code, self.inline(code))

    def filters(self, query):
        fields = []
        for part in split_pipes(query):
            key, sep, value = part.partition('=')
            if sep:
                values = value.split(';')
                if key == 'level':
                    values = ['Cantrip' if v == '0' else 'Level ' + v for v in values]
                    fields.append(' or '.join(map(self.inline, values)))
                else:
                    fields.append(self.label(key) + ': ' + ' or '.join(map(self.inline, values)))
            elif part:
                fields.append(self.inline(part))
        return '; '.join(fields)

    def structure(self, value, *, key=None):
        """Only called for explicitly selected game fields by a typed adapter."""
        if value is None:
            return '—'
        if isinstance(value, bool):
            return 'Yes' if value else 'No'
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            if key in ('category', 'featureType'):
                labels = FEATURE_TYPES if key == 'featureType' else CATEGORIES
                return labels.get(value, self.inline(value))
            if key in ('choose', 'all') and '=' in value:
                return self.filters(value)
            if key == 'type' and '|' in value:
                return self.item_type(value)
            if key in ('property', 'mastery'):
                return self.definition(
                    value, 'itemProperty' if key == 'property' else 'itemMastery'
                )
            if key == 'type' and ('.' in value or re.search(r'[a-z][A-Z]', value)):
                return self.label(value.replace('.', ' — '))
            if key in ('item', 'uid', 'spell', 'baseItem', 'ammoType'):
                return self.uid(value, source=True)
            if key in ('str', 'dex', 'con', 'int', 'wis', 'cha'):
                return self.inline(value)
            if value in ABILITIES:
                return ABILITIES[value]
            if '|' in value and '{@' not in value:
                return self.uid(value, source=True)
            return self.inline(value)
        if isinstance(value, list):
            return '; '.join(filter(None, (self.structure(v, key=key) for v in value)))
        require(
            isinstance(value, dict), 'GAME_VALUE', type(value).__name__, **self.engine.context()
        )
        if value.get('type') == 'dice':
            return ' + '.join(
                f'{die.get("number", 1)}d{die["faces"]}'
                + (f' {die["modifier"]:+d}' if die.get('modifier') else '')
                for die in value.get('toRoll', [])
            )
        if 'entry' in value and ('choose' in value or 'entrySummary' in value):
            return self.inline(value['entry']) + (
                f' (choose {value["count"]})' if value.get('count') else ''
            )
        if 'special' in value:
            return self.inline(value['special'])
        if set(value) <= {'uid', 'note'} and 'uid' in value:
            text = (
                self.definition(value['uid'], 'itemMastery')
                if key == 'mastery'
                else self.uid(value['uid'], source=True)
            )
            return text + ('; ' + self.inline(value['note']) if value.get('note') else '')
        if 'choose' in value and set(value) <= {'choose', 'count', 'amount', 'hidden'}:
            choice = value['choose']
            if isinstance(choice, dict) and 'from' in choice:
                count = choice.get('count', 1)
                options = ', '.join(self.label(v) for v in choice['from'])
                amount = choice.get('amount')
                return f'Choose {count} from {options}' + (
                    f' ({amount:+d})' if amount is not None else ''
                )
            return f'Choose {value.get("count", 1)}: ' + self.structure(choice, key='choose')
        if 'weighted' in value:
            weighted = value['weighted']
            return (
                'Choose from '
                + ', '.join(self.label(v) for v in weighted['from'])
                + ': increases of '
                + ', '.join(f'{v:+d}' for v in weighted['weights'])
            )
        if 'item' in value:
            text = (
                self.inline(value['displayName'])
                if value.get('displayName')
                else self.uid(value['item'], source=True)
            )
            if value.get('quantity'):
                text = f'{value["quantity"]} × ' + text
            return text + (
                '; '
                + self.structure(
                    {k: v for k, v in value.items() if k not in ('item', 'quantity', 'displayName')}
                )
                if set(value) - {'item', 'quantity', 'displayName'}
                else ''
            )
        if set(value) == {'value'}:
            return f'{value["value"] / 100:g} GP'
        if 'name' in value and set(value) <= {
            'name',
            'source',
            'level',
            'className',
            'classSource',
            'shortName',
        }:
            result = self.inline(value['name'])
            if value.get('level') is not None:
                result += f' Level {value["level"]}'
            if (
                value.get('source')
                and value['source'].casefold() != self.engine.domain.id.casefold()
            ):
                result += ' (' + value['source'] + ')'
            return result
        pieces = []
        for name, child in value.items():
            if name in (
                'hidden',
                'visible',
                'visibleStats',
                'source',
                'entrySummary',
                'displayAs',
                'cond',
            ):
                continue
            if name == '_':
                pieces.append(self.structure(child))
            elif key in (
                'known',
                'innate',
                'prepared',
                'expanded',
                'progression',
                'itemMasteriesProgression',
            ) and (name.isdigit() or re.fullmatch(r's\d+', name)):
                label = 'Spell Level ' + name[1:] if name.startswith('s') else 'Level ' + name
                pieces.append(label + ': ' + self.structure(child))
            elif key in ('daily', 'rest', 'restLong', 'limited') and re.fullmatch(r'\d+e?', name):
                label = name.rstrip('e') + (
                    ' uses'
                    if key == 'limited'
                    else '/' + {'daily': 'day', 'rest': 'rest', 'restLong': 'Long Rest'}[key]
                )
                pieces.append(
                    label + (' each' if name.endswith('e') else '') + ': ' + self.structure(child)
                )
            elif isinstance(child, bool) and child:
                pieces.append(self.uid(name, source=True) if '|' in name else self.label(name))
            elif name == 'from':
                pieces.append('from ' + ', '.join(self.label(v) for v in child))
            else:
                pieces.append(self.label(name) + ': ' + self.structure(child, key=name))
        return '; '.join(filter(None, pieces))

    def capacity(self, value):
        parts = []
        for key, contents in value.items():
            if key in ('weight', 'volume'):
                unit = 'lb.' if key == 'weight' else 'cubic feet'
                parts.append(' or '.join(f'{v} {unit}' for v in contents))
            elif key == 'weightless' and contents:
                parts.append('contents add no weight')
            elif key == 'item':
                parts.append(
                    ' or '.join(
                        ', '.join(
                            f'{count} × {self.uid(uid, source=True)}'
                            for uid, count in group.items()
                        )
                        for group in contents
                    )
                )
            else:
                parts.append(self.label(key) + ': ' + self.structure(contents))
        return '; '.join(parts)

    def prerequisite(self, requirements):
        if isinstance(requirements, str):
            return self.inline(requirements)
        alternatives = []
        for requirement in requirements:
            clauses = []
            for field, value in requirement.items():
                if field == 'level':
                    if isinstance(value, dict):
                        cls = value.get('class', {}).get('name', '')
                        clauses.append((cls + ' ' if cls else '') + f'Level {value["level"]}')
                    else:
                        clauses.append(f'Level {value}')
                elif field == 'spell':
                    clauses.append('; '.join(self.structure(v, key='spell') for v in value))
                elif field == 'ability':
                    clauses.append(' or '.join(self.structure(v) for v in value))
                elif field in ('feat', 'feature', 'race', 'background'):
                    clauses.append(self.label(field) + ': ' + self.structure(value))
                elif field == 'spellcasting' and value:
                    clauses.append('Spellcasting')
                elif field == 'otherSummary':
                    require(
                        isinstance(value, dict)
                        and set(value) <= {'entry', 'entrySummary'}
                        and isinstance(value.get('entry'), str),
                        'PREREQUISITE_FORMAT',
                        'Unsupported prerequisite summary',
                        **self.engine.context(),
                    )
                    clauses.append(self.inline(value['entry']))
                else:
                    clauses.append(self.label(field) + ': ' + self.structure(value, key=field))
            alternatives.append(', '.join(clauses))
        return ' or '.join(alternatives)

    def speed(self, value):
        if isinstance(value, (str, int)):
            return self.inline(value) + (' ft.' if isinstance(value, int) else '')
        parts = []
        for mode, speed in value.items():
            if mode == 'canHover':
                continue
            if mode == 'alternate':
                for alternate_mode, alternatives in speed.items():
                    parts.extend(self.speed({alternate_mode: v}) for v in alternatives)
            elif mode == 'choose':
                parts.append(
                    ' or '.join(v.title() for v in speed['from'])
                    + f' {speed["amount"]} ft.'
                    + (' ' + self.inline(speed['note']) if speed.get('note') else '')
                )
            else:
                label = '' if mode == 'walk' else self.label(mode) + ' '
                if isinstance(speed, dict):
                    parts.append(
                        label
                        + str(speed['number'])
                        + ' ft.'
                        + (' ' + self.inline(speed['condition']) if speed.get('condition') else '')
                    )
                elif isinstance(speed, (int, float)):
                    parts.append(label + str(speed) + ' ft.')
                else:
                    parts.append(label + self.structure(speed))
                if mode == 'fly' and value.get('canHover') and 'hover' not in parts[-1].casefold():
                    parts[-1] += ' (hover)'
        return ', '.join(parts)

    def defenses(self, values, field):
        parts = []
        for value in values:
            if isinstance(value, str):
                parts.append(self.inline(value.title()))
            elif 'special' in value:
                parts.append(self.inline(value['special']))
            else:
                require(
                    field in value,
                    'DEFENSE_VALUE',
                    'Missing defense values',
                    field=field,
                    **self.engine.context(),
                )
                text = self.defenses(value[field], field)
                if value.get('preNote'):
                    text = self.inline(value['preNote']) + ' ' + text
                if value.get('note'):
                    text += ' ' + self.inline(value['note'])
                parts.append(text)
        return '; '.join(parts)

    def duration(self, values):
        result = []
        for value in values:
            kind = value['type']
            allowed = {
                'timed': {'type', 'duration', 'concentration'},
                'permanent': {'type', 'ends'},
                'instant': {'type'},
                'special': {'type', 'condition'},
            }
            require(
                kind in allowed and set(value) <= allowed[kind],
                'DURATION_FORMAT',
                'Unsupported duration type or fields',
                **self.engine.context(),
            )
            if kind == 'timed':
                duration = value['duration']
                require(
                    set(duration) <= {'amount', 'type', 'upTo'}
                    and duration['type']
                    in {'turn', 'round', 'minute', 'hour', 'day', 'week', 'month', 'year'},
                    'DURATION_FORMAT',
                    'Unsupported timed duration',
                    **self.engine.context(),
                )
                text = f'{duration["amount"]} {duration["type"]}' + (
                    's' if duration['amount'] != 1 else ''
                )
                if value.get('concentration'):
                    text = 'Concentration, up to ' + text
                elif duration.get('upTo'):
                    text = 'Up to ' + text
            elif kind == 'permanent':
                endings = {'dispel': 'dispelled', 'trigger': 'triggered', 'discharge': 'discharged'}
                require(
                    all(v in endings for v in value.get('ends', [])),
                    'DURATION_FORMAT',
                    'Unsupported ending condition',
                    **self.engine.context(),
                )
                text = 'Until ' + ' or '.join(endings[v] for v in value.get('ends', ['dispel']))
            else:
                text = {'instant': 'Instantaneous', 'special': 'Special'}.get(
                    kind, self.label(kind)
                )
                if value.get('condition'):
                    text += ' (' + self.inline(value['condition']) + ')'
            result.append(text)
        return ' or '.join(result)

    def time(self, values):
        parts = []
        for value in values:
            if isinstance(value, str):
                parts.append(self.inline(value))
                continue
            require(
                set(value) <= {'number', 'unit', 'condition', 'note'}
                and value['unit']
                in {'action', 'bonus', 'reaction', 'round', 'minute', 'hour', 'day'},
                'TIME_FORMAT',
                'Unsupported time unit or fields',
                **self.engine.context(),
            )
            unit = {'bonus': 'Bonus Action', 'reaction': 'Reaction'}.get(
                value['unit'], value['unit']
            )
            parts.append(
                f'{value.get("number", 1)} {unit}'
                + ('s' if value.get('number', 1) != 1 else '')
                + (', ' + self.inline(value['condition']) if value.get('condition') else '')
                + (' (' + self.inline(value['note']) + ')' if value.get('note') else '')
            )
        return ' or '.join(parts)

    def spell_range(self, value):
        kind = value['type']
        require(
            set(value) <= {'type', 'distance'}
            and kind
            in {
                'point',
                'line',
                'cone',
                'sphere',
                'hemisphere',
                'cylinder',
                'cube',
                'radius',
                'emanation',
                'special',
            },
            'RANGE_FORMAT',
            'Unsupported range type or fields',
            **self.engine.context(),
        )
        distance = value.get('distance', {})
        dtype, amount = distance.get('type'), distance.get('amount')
        require(
            set(distance) <= {'type', 'amount'}
            and (
                kind == 'special'
                or dtype in {'feet', 'miles', 'self', 'touch', 'sight', 'unlimited', 'special'}
            ),
            'RANGE_FORMAT',
            'Unsupported distance type or fields',
            **self.engine.context(),
        )
        require(
            dtype not in {'feet', 'miles'} or isinstance(amount, (int, float)),
            'RANGE_FORMAT',
            'Numeric distance has no amount',
            **self.engine.context(),
        )
        if dtype in ('feet', 'miles'):
            unit = {'feet': 'foot', 'miles': 'mile'}[dtype] if amount == 1 else dtype
            text = f'{amount} {unit}'
        else:
            text = {
                'self': 'Self',
                'touch': 'Touch',
                'sight': 'Sight',
                'unlimited': 'Unlimited',
                'special': 'Special',
            }.get(dtype, '')
        if kind == 'point':
            return text
        if kind == 'special':
            return 'Special'
        return f'Self ({text} {self.label(kind)})'
