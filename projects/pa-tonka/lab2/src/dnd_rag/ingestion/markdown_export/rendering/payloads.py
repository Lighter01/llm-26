"""Typed game payloads. Metadata and source recipes are never prose."""

import math
import re
from fractions import Fraction

from ..common.model import require
from .entries import INLINE_ENTRY_DEPTH, quote
from .inline import ABILITIES, split_pipes
from .representation import narrative_strings, normalized, ordered_entries_represented
from .values import ALIGNMENTS, DAMAGE, SCHOOLS, SIZES

XP = dict(
    zip(
        ('0', '1/8', '1/4', '1/2', *map(str, range(1, 31))),
        (
            10,
            25,
            50,
            100,
            200,
            450,
            700,
            1100,
            1800,
            2300,
            2900,
            3900,
            5000,
            5900,
            7200,
            8400,
            10000,
            11500,
            13000,
            15000,
            18000,
            20000,
            22000,
            25000,
            33000,
            41000,
            50000,
            62000,
            75000,
            90000,
            105000,
            120000,
            135000,
            155000,
        ),
    )
)
COMMON_METADATA = frozenset(
    (
        'name',
        'source',
        'page',
        '__prop',
        'type',
        'srd',
        'srd52',
        'basicRules',
        'basicRules2024',
        'edition',
        'otherSources',
        'referenceSources',
        'hasFluff',
        'hasFluffImages',
        'hasToken',
        'soundClip',
        'alias',
        'isReprinted',
        'reprintedAs',
        'foundryTokenScale',
        'tokenCredit',
        'tokenCustom',
        'altArt',
        'hasRefs',
        'className',
        'classSource',
        'subclassShortName',
        'subclassSource',
        'header',
        'shortName',
        'repeatableHidden',
        'previousVersions',
        'gainSubclassFeature',
    )
)
CACHE_FIELDS = frozenset(
    (
        '_versions',
        '_isCopy',
        '_isEnhanced',
        '_isBaseItem',
        '_isItemGroup',
        '_isInherited',
        '_isMutEntity',
        '_tmpSourcesInit',
        '_tmpClasses',
        '_tmpRaces',
        '_tmpBackgrounds',
        '_tmpFeats',
        '_tmpOptionalfeatures',
        '_tmpGroups',
        '_fonts',
        '_category',
        '_textTypes',
        '_entryType',
        '_entrySubType',
        '_attunement',
        '_attunementCategory',
        '_valueFromRarity',
        '_baseFreeRules2024',
        '_baseName',
        '_baseSource',
        '_baseSrd52',
        '_baseValue',
        '_variantName',
        '_isReplacement',
    )
)

RULE_FIELDS = {
    'prerequisite': 'Prerequisite',
    'ability': 'Ability Score Increases',
    'category': 'Category',
    'repeatable': 'Repeatable',
    'featureType': 'Feature Type',
    'additionalSpells': 'Additional Spells',
    'consumes': 'Consumes',
    'cost': 'Cost',
    'featProgression': 'Feats',
    'armorProficiencies': 'Armor Training',
    'weaponProficiencies': 'Weapon Proficiencies',
    'savingThrowProficiencies': 'Saving Throw Proficiencies',
    'skillProficiencies': 'Skill Proficiencies',
    'toolProficiencies': 'Tool Proficiencies',
    'skillToolLanguageProficiencies': 'Skill, Tool, or Language Proficiencies',
    'expertise': 'Expertise',
    'senses': 'Senses',
    'resist': 'Resistances',
    'creatureTypes': 'Creature Type',
    'size': 'Size',
    'speed': 'Speed',
    'darkvision': 'Darkvision',
    'feats': 'Feats',
    'level': 'Level',
    'rating': 'Rating',
    'trigger': 'Trigger',
    'duration': 'Duration',
    'facilityType': 'Facility Type',
    'space': 'Space',
    'hirelings': 'Hirelings',
    'orders': 'Orders',
    'ac': 'AC',
    'hp': 'HP',
    'objectType': 'Object Type',
    'vehicleType': 'Vehicle Type',
    'terrain': 'Terrain',
    'capCrew': 'Crew Capacity',
    'capPassenger': 'Passenger Capacity',
    'immune': 'Immunities',
    'dialects': 'Dialects',
    'origin': 'Origin',
    'script': 'Script',
    'typicalSpeakers': 'Typical Speakers',
    'pantheon': 'Pantheon',
    'plane': 'Plane',
    'symbol': 'Symbol',
    'title': 'Title',
    'worshipers': 'Worshipers',
    'seeAlsoAction': 'Related Actions',
    'seeAlsoFacility': 'Related Facilities',
    'ruleType': 'Rule Type',
}
RULE_PROPS = frozenset(
    (
        'background',
        'race',
        'feat',
        'optionalfeature',
        'classFeature',
        'subclassFeature',
        'hazard',
        'trap',
        'disease',
        'condition',
        'action',
        'sense',
        'status',
        'variantrule',
        'facility',
        'object',
        'reward',
        'vehicle',
        'language',
        'deity',
        'skill',
        'card',
        'itemType',
        'itemProperty',
        'itemMastery',
    )
)
RULE_RENDER_FIELDS = frozenset(RULE_FIELDS) | {
    'entries',
    'actionEntries',
    'startingEquipment',
    'sizeEntry',
    'time',
}
RULE_DATA_FIELDS = RULE_RENDER_FIELDS | {'abbreviation', 'template', 'set', 'face', 'trapHazType'}
ITEM_FIELDS = {
    'weight': 'Weight',
    'weightNote': 'Weight Note',
    'value': 'Price',
    'valueRarity': 'Price by Rarity',
    'ac': 'Base AC',
    'bonusAc': 'AC Bonus',
    'bonusWeapon': 'Weapon Bonus',
    'bonusWeaponDamage': 'Weapon Damage Bonus',
    'bonusSavingThrow': 'Saving Throw Bonus',
    'bonusAbilityCheck': 'Ability Check Bonus',
    'bonusSpellAttack': 'Spell Attack Bonus',
    'bonusSpellSaveDc': 'Spell Save DC Bonus',
    'bonusProficiencyBonus': 'Proficiency Bonus Increase',
    'reqAttune': 'Attunement',
    'charges': 'Charges',
    'recharge': 'Recharge',
    'rechargeAmount': 'Charges Regained',
    'resist': 'Resistances',
    'immune': 'Immunities',
    'vulnerable': 'Vulnerabilities',
    'property': 'Properties',
    'mastery': 'Mastery',
    'range': 'Range',
    'reload': 'Reload',
    'strength': 'Strength Requirement',
    'stealth': 'Stealth',
    'ability': 'Ability Scores',
    'containerCapacity': 'Capacity',
    'carryingCapacity': 'Carrying Capacity',
    'packContents': 'Contents',
    'light': 'Light',
    'modifySpeed': 'Speed Changes',
    'speed': 'Speed',
    'focus': 'Spellcasting Focus',
    'scfType': 'Focus Type',
    'poison': 'Poison',
    'poisonTypes': 'Poison Types',
    'curse': 'Cursed',
    'sentient': 'Sentient',
    'grantsLanguage': 'Grants Language',
    'grantsProficiency': 'Grants Proficiency',
    'spellScrollLevel': 'Spell Scroll Level',
    'critThreshold': 'Critical Hit Threshold',
    'attachedSpells': 'Spells',
    'weaponCategory': 'Weapon Category',
    'capCargo': 'Cargo Capacity',
    'capPassenger': 'Passenger Capacity',
    'crew': 'Crew',
    'vehAc': 'Vehicle AC',
    'vehHp': 'Vehicle HP',
    'vehDmgThresh': 'Damage Threshold',
    'vehSpeed': 'Vehicle Speed',
    'barDimensions': 'Bar Dimensions',
    'age': 'Age',
    'ammoType': 'Ammunition',
    'requires': 'Applies To',
    'excludes': 'Excluded Forms',
    'classFeatures': 'Related Class Features',
    'optionalfeatures': 'Related Options',
    'items': 'Items',
    'baseItem': 'Base Item',
}
ITEM_TAXONOMY = frozenset(
    (
        'armor',
        'arrow',
        'axe',
        'bolt',
        'bow',
        'bulletFirearm',
        'bulletSling',
        'cellEnergy',
        'club',
        'crossbow',
        'dagger',
        'firearm',
        'group',
        'hammer',
        'lance',
        'mace',
        'needleBlowgun',
        'polearm',
        'rapier',
        'spear',
        'staff',
        'sword',
        'weapon',
        'wondrous',
        'ammo',
        'genericVariant',
        'lootTables',
        'detail1',
        'detail2',
        'seeAlsoDeck',
        'seeAlsoVehicle',
        'itemsHidden',
    )
)


def ability_mod(score):
    return (score - 10) // 2 if isinstance(score, int) else None


def pb(cr):
    if isinstance(cr, dict):
        cr = cr.get('cr')
    if cr in (None, 'Unknown', '—'):
        return None
    try:
        return max(2, math.ceil(Fraction(cr) / 4) + 1)
    except (ValueError, ZeroDivisionError):
        return None


class Payloads:
    def __init__(self, engine):
        self.engine = engine

    @property
    def doc(self):
        return self.engine.doc

    @property
    def entries(self):
        return self.engine.entries

    @property
    def values(self):
        return self.engine.values

    @property
    def inline(self):
        return self.engine.inline

    def fields(self, data, handled, *, metadata=()):
        ignored = COMMON_METADATA | CACHE_FIELDS | set(metadata)
        unknown = {
            key
            for key in data
            if key not in handled and key not in ignored and not key.endswith('Tags')
        }
        require(
            not unknown,
            'UNKNOWN_PAYLOAD_FIELD',
            ', '.join(sorted(unknown)),
            prop=data.get('__prop'),
            **self.engine.context(),
        )

    def line(self, label, value):
        if value is not None and value != '':
            self.doc.add('**' + label + ':** ' + value)

    def complete_inline_rule(self, data, canonical):
        self.fields(data, RULE_DATA_FIELDS)
        self.fields(canonical, RULE_DATA_FIELDS)
        complete = dict(data)
        for field in sorted(RULE_RENDER_FIELDS):
            if field not in canonical:
                continue
            if field not in data:
                complete[field] = canonical[field]
            else:
                agrees = (
                    ordered_entries_represented(canonical[field], data[field], self.inline)
                    if field == 'entries'
                    else normalized(canonical[field], self.inline)
                    == normalized(data[field], self.inline)
                )
                require(
                    agrees,
                    'INLINE_COMPONENT_MISMATCH',
                    'Inline rule differs from its canonical component',
                    field=field,
                    name=data.get('name'),
                    **self.engine.context(),
                )
        return complete

    def render(self, data, prop, level, *, structural=True, partial=False):
        if prop == 'monster':
            return self.monster(data)
        if prop in ('class', 'subclass'):
            return self.character_class(data, prop, level, structural=structural)
        if prop == 'spell':
            return self.spell(data, level, structural=structural)
        if prop in ('item', 'baseitem', 'itemGroup', 'magicvariant'):
            return self.item(
                data, level, structural=structural, show_type=not partial or 'type' in data
            )
        if prop.endswith('Fluff'):
            self.fields(data, {'entries', 'images'})
            for entry in data.get('entries', []):
                self.entries.render(entry, level, structural=structural, skip_name=data.get('name'))
            return
        if prop == 'legendaryGroup':
            self.fields(data, {'lairActions', 'regionalEffects', 'mythicEncounter'})
            for field, title in (
                ('lairActions', 'Lair Actions'),
                ('regionalEffects', 'Regional Effects'),
                ('mythicEncounter', 'Mythic Encounter'),
            ):
                if data.get(field):
                    child_level = self.entries.label(
                        title,
                        level,
                        structural=structural,
                        fallback=self.engine.page_context.fallback,
                        partial=True,
                    )
                    self.entries.render(
                        data[field],
                        child_level,
                        structural=structural,
                        entry_depth=INLINE_ENTRY_DEPTH,
                    )
            return
        if prop in ('gems', 'artObjects', 'magicItems', 'individual', 'hoard'):
            return self.loot(data)
        if prop == 'deck':
            self.fields(data, {'entries', 'cards', 'back', 'hasCardArt'})
            for entry in data.get('entries', []):
                if not self.engine.ancestor_represents(entry):
                    self.entries.render(
                        entry, level, structural=structural, entry_depth=INLINE_ENTRY_DEPTH
                    )
            for card in data.get('cards', []):
                require(
                    isinstance(card, dict), 'UNRESOLVED_CARD', str(card), **self.engine.context()
                )
                self.engine.native(card, level, prop='card', structural=structural)
            return
        require(prop in RULE_PROPS, 'UNKNOWN_PAYLOAD_TYPE', prop, **self.engine.context())
        self.fields(data, RULE_DATA_FIELDS)
        for field, label in RULE_FIELDS.items():
            if (
                field not in data
                or field == 'level'
                and prop in ('classFeature', 'subclassFeature')
            ):
                continue
            value = data[field]
            if field == 'prerequisite':
                text = self.values.prerequisite(value)
            elif field == 'ability':
                text = self.values.ability(value)
                if prop == 'skill':
                    label = 'Ability'
            elif field == 'size':
                text = ' or '.join(SIZES[v] for v in value)
            elif field == 'speed':
                text = self.values.speed(value)
            elif field == 'duration':
                text = self.values.duration(value)
            elif field == 'space':
                text = ' or '.join(v.title() for v in value)
            elif field in ('category', 'featureType'):
                text = ', '.join(
                    self.values.structure(v, key=field)
                    for v in ([value] if isinstance(value, str) else value)
                )
            elif field == 'ruleType':
                continue  # Display taxonomy, not an additional rule.
            else:
                text = self.values.structure(value, key=field)
            self.line(label, text)
        if 'type' in data and prop in ('disease', 'reward', 'language'):
            self.line('Type', self.values.structure(data['type']))
        if data.get('time'):
            self.line('Time', self.values.time(data['time']))
        if data.get('sizeEntry'):
            self.entries.render(data['sizeEntry'], structural=False)
        if data.get('startingEquipment'):
            self.starting_equipment(data['startingEquipment'])
        for entry in data.get('entries', []):
            self.entries.render(
                entry,
                level,
                structural=structural,
                skip_name=data.get('name'),
                entry_depth=INLINE_ENTRY_DEPTH,
            )
        if data.get('actionEntries'):
            self.doc.add('**Actions**')
            self.entries.render(data['actionEntries'], level, structural=False)

    def starting_equipment(self, value):
        self.doc.add('**Starting Equipment**')
        if isinstance(value, dict) and 'entries' in value:
            self.entries.render(value['entries'], structural=False)
            if value.get('additionalFromBackground'):
                self.doc.add('Also gain the starting equipment from your background.')
            return
        options = value.get('defaultData', []) if isinstance(value, dict) else value
        for option in options:
            self.doc.add(
                '\n'.join(
                    '- **' + str(key) + ':** ' + self.values.structure(items)
                    for key, items in option.items()
                )
            )

    def character_class(self, data, prop, level, *, structural):
        fields = {
            'primaryAbility',
            'hd',
            'proficiency',
            'startingProficiencies',
            'startingEquipment',
            'multiclassing',
            'classFeatures',
            'subclassFeatures',
            'classTableGroups',
            'subclassTableGroups',
            'subclassTitle',
            'itemMasteries',
            'itemMasteriesProgression',
            'featProgression',
            'additionalSpells',
            'optionalfeatureProgression',
            'spellcastingAbility',
            'casterProgression',
            'preparedSpellsChange',
            'cantripProgression',
            'preparedSpellsProgression',
            'spellsKnownProgressionFixed',
            'spellsKnownProgressionFixedByLevel',
            'spellsKnownProgressionFixedAllowLowerLevel',
        }
        self.fields(data, fields)
        for field, label in (
            ('primaryAbility', 'Primary Ability'),
            ('proficiency', 'Saving Throw Proficiencies'),
            ('spellcastingAbility', 'Spellcasting Ability'),
            ('casterProgression', 'Spellcasting Progression'),
        ):
            if field in data:
                self.line(label, self.values.structure(data[field], key=field))
        if 'hd' in data:
            self.line(
                'Hit Point Die',
                f'{data["hd"]["number"]}d{data["hd"]["faces"]} per {self.inline(data["name"])} level',
            )
        for field, label in (
            ('startingProficiencies', 'Starting Proficiencies'),
            ('multiclassing', 'Multiclassing'),
        ):
            if data.get(field):
                proficiencies = data[field]
                if field == 'startingProficiencies':
                    for key, title in (
                        ('skills', 'Skill Proficiencies'),
                        ('weapons', 'Weapon Proficiencies'),
                        ('armor', 'Armor Training'),
                    ):
                        if key in proficiencies:
                            self.line(title, self.values.structure(proficiencies[key]))
                    represented_armor = set(proficiencies.get('armor', []))
                    structured_armor = proficiencies.get('armorProficiencies', [])
                    armor_keys = {
                        key
                        for group in structured_armor
                        for key, value in group.items()
                        if value is True
                    }
                    equivalent_armor = (
                        all(value is True for group in structured_armor for value in group.values())
                        and armor_keys == represented_armor
                    )
                    consumed = {'skills', 'weapons', 'armor'} | (
                        {'armorProficiencies'} if equivalent_armor else set()
                    )
                    remaining = {k: v for k, v in proficiencies.items() if k not in consumed}
                    if remaining:
                        self.line(label, self.values.structure(remaining))
                else:
                    self.line(label, self.values.structure(proficiencies))
        if data.get('startingEquipment'):
            self.starting_equipment(data['startingEquipment'])
        features = data.get('classFeatures', data.get('subclassFeatures', []))
        groups = data.get('classTableGroups', data.get('subclassTableGroups', []))
        for index, group in enumerate(groups):
            rows = group.get('rows', group.get('rowsSpellProgression'))
            require(
                isinstance(rows, list),
                'CLASS_TABLE_ROWS',
                'Missing progression rows',
                **self.engine.context(),
            )
            if index == 0 and prop == 'class':
                require(
                    len(rows) == len(features),
                    'CLASS_TABLE_LENGTH',
                    data['name'],
                    **self.engine.context(),
                )
                body = [
                    [
                        i,
                        f'{2 + (i - 1) // 4:+d}',
                        ', '.join(f['name'] for f in fs if f.get('name')) or '—',
                        *row,
                    ]
                    for i, (row, fs) in enumerate(zip(rows, features), 1)
                ]
                labels = ['Level', 'Proficiency Bonus', 'Class Features', *group['colLabels']]
            else:
                body = [[i, *row] for i, row in enumerate(rows, 1)]
                labels = ['Level', *group['colLabels']]
            table = {
                'type': 'table',
                'caption': group.get('title', data['name'] + ' Features'),
                'colLabels': labels,
                'rows': body,
            }
            self.entries.table(table)
        for field, label in (
            ('cantripProgression', 'Cantrips Known'),
            ('preparedSpellsProgression', 'Spells Prepared'),
            ('spellsKnownProgressionFixed', 'Spells Learned'),
        ):
            if data.get(field):
                self.entries.table(
                    {
                        'type': 'table',
                        'caption': label,
                        'colLabels': ['Level', label],
                        'rows': [[i, value] for i, value in enumerate(data[field], 1)],
                    }
                )
        for field, label in (
            ('additionalSpells', 'Additional Spells'),
            ('featProgression', 'Feats'),
            ('optionalfeatureProgression', 'Feature Progression'),
            ('itemMasteriesProgression', 'Weapon Mastery Progression'),
            ('spellsKnownProgressionFixedByLevel', 'Higher-Level Spells Learned'),
            ('spellsKnownProgressionFixedAllowLowerLevel', 'May Choose Lower-Level Spells'),
            ('preparedSpellsChange', 'Change Prepared Spells'),
        ):
            if data.get(field):
                self.line(label, self.values.structure(data[field], key=field))
        for group in features:
            for feature in group:
                if feature.get('name') == data['name']:
                    # The initial native subclass feature packages its introduction and nested features.
                    self.engine.native(feature, level, structural=structural, suppress_title=True)
                else:
                    self.entries.render(feature, level, structural=structural)

    def spell(self, data, level, *, structural):
        fields = {
            'level',
            'school',
            'meta',
            'time',
            'range',
            'components',
            'duration',
            'entries',
            'entriesHigherLevel',
            'classes',
            'scalingLevelDice',
        }
        taxonomy = {
            'abilityCheck',
            'affectsCreatureType',
            'conditionImmune',
            'conditionInflict',
            'damageImmune',
            'damageInflict',
            'damageResist',
            'damageVulnerable',
            'savingThrow',
            'spellAttack',
        }
        # Reverse-access indexes describe the global catalog, not this spell's rules.
        access_metadata = {'races', 'backgrounds', 'feats', 'optionalfeatures', 'rewards'}
        self.fields(data, fields, metadata=taxonomy | access_metadata)
        school = SCHOOLS.get(data['school'], data['school'])
        self.doc.add(
            '*'
            + (f'Level {data["level"]} {school}' if data['level'] else school + ' Cantrip')
            + '*'
        )
        self.line('Casting Time', self.values.time(data['time']))
        self.line('Range', self.values.spell_range(data['range']))
        components, parts = data['components'], []
        require(
            set(components) <= {'v', 's', 'm'},
            'SPELL_COMPONENTS',
            'Unsupported spell components',
            **self.engine.context(),
        )
        parts.extend(k.upper() for k in ('v', 's') if components.get(k))
        if components.get('m'):
            material = components['m']
            if material is True:
                parts.append('M')
            else:
                require(
                    isinstance(material, (str, dict)),
                    'SPELL_COMPONENTS',
                    'Unsupported material component',
                    **self.engine.context(),
                )
                if isinstance(material, dict):
                    require(
                        set(material) <= {'text', 'cost', 'consume'}
                        and isinstance(material.get('text'), str),
                        'SPELL_COMPONENTS',
                        'Unsupported material fields',
                        **self.engine.context(),
                    )
                    text = material['text']
                    details = []
                    if 'cost' in material:
                        cost = material['cost']
                        require(
                            type(cost) is int and cost >= 0,
                            'SPELL_COMPONENTS',
                            'Invalid material cost',
                            **self.engine.context(),
                        )
                        gold = f'{cost / 100:g}'
                        prose = self.inline(text, plain=True).replace(',', '')
                        units = {'CP': 1, 'SP': 10, 'EP': 50, 'GP': 100, 'PP': 1000}
                        prices = re.findall(
                            r'(?<![\d.])(\d+(?:\.\d+)?)\+?\s+(CP|SP|EP|GP|PP)\b', prose, re.I
                        )
                        if not any(
                            Fraction(amount) * units[unit.upper()] == cost
                            for amount, unit in prices
                        ):
                            details.append(gold + ' GP')
                    if 'consume' in material:
                        require(
                            type(material['consume']) is bool or material['consume'] == 'optional',
                            'SPELL_COMPONENTS',
                            'Unsupported material consumption',
                            **self.engine.context(),
                        )
                        if material['consume'] and 'consum' not in text.casefold():
                            details.append(
                                'optionally consumed'
                                if material['consume'] == 'optional'
                                else 'consumed'
                            )
                    material = '; '.join([text, *details])
                parts.append('M (' + self.inline(material) + ')')
        self.line('Components', ', '.join(parts))
        self.line('Duration', self.values.duration(data['duration']))
        if data.get('meta'):
            self.line('Casting Options', self.values.structure(data['meta']))
        classes = self.spell_classes(data)
        if classes:
            self.line('Classes', classes)
        self.entries.render(
            data['entries'], level, structural=structural, entry_depth=INLINE_ENTRY_DEPTH
        )
        self.entries.render(
            data.get('entriesHigherLevel', []),
            level,
            structural=structural,
            entry_depth=INLINE_ENTRY_DEPTH,
        )
        if data.get('scalingLevelDice'):
            groups = data['scalingLevelDice']
            for group in groups if isinstance(groups, list) else [groups]:
                require(
                    set(group) <= {'label', 'scaling'},
                    'SPELL_SCALING',
                    'Unsupported scaling fields',
                    **self.engine.context(),
                )
                prose = ' '.join(
                    narrative_strings(
                        [data['entries'], data.get('entriesHigherLevel', [])], self.inline
                    )
                )
                if not all(
                    re.search(
                        r'(?<![a-z0-9])' + re.escape(formula.casefold()) + r'(?![a-z0-9])', prose
                    )
                    for formula in group['scaling'].values()
                ):
                    self.entries.table(
                        {
                            'type': 'table',
                            'caption': group.get('label', 'Cantrip Scaling'),
                            'colLabels': ['Level', 'Dice'],
                            'rows': [[key, value] for key, value in group['scaling'].items()],
                        }
                    )

    def spell_classes(self, data):
        """Use main-list identities from the book; isolated cards use their own source."""
        classes = data.get('classes', {})
        require(
            isinstance(classes, dict)
            and set(classes)
            <= {'fromClassList', 'fromClassListVariant', 'fromSubclass', 'fromSubclassVariant'}
            and isinstance(classes.get('fromClassList', []), list),
            'SPELL_CLASSES',
            'Unsupported spell class index',
            **self.engine.context(),
        )
        domain = self.engine.domain
        book_classes = {
            (payload['name'].casefold(), payload['source'].casefold())
            for entity in domain.entities.values()
            if entity['prop'] == 'class'
            for payload in [domain.payload(entity)]
        }
        names = {}
        for reference in classes.get('fromClassList', []):
            require(
                isinstance(reference, dict)
                and set(reference) <= {'name', 'source', 'definedInSource'}
                and all(
                    isinstance(reference.get(k), str) and reference[k].strip()
                    for k in ('name', 'source')
                )
                and (
                    'definedInSource' not in reference
                    or isinstance(reference['definedInSource'], str)
                ),
                'SPELL_CLASSES',
                'Expected a source-labelled main class',
                **self.engine.context(),
            )
            name, source = reference['name'], reference['source']
            selected = (
                (name.casefold(), source.casefold()) in book_classes
                if book_classes
                else source.casefold() == data['source'].casefold()
            )
            definition = reference.get('definedInSource')
            if selected and (not definition or definition.casefold() == domain.id.casefold()):
                names.setdefault(name.casefold(), name)
        return ', '.join(self.inline(names[key]) for key in sorted(names))

    def item_fields(self, data):
        self.fields(
            data,
            set(ITEM_FIELDS)
            | {
                'entries',
                '_fullEntries',
                'rarity',
                'typeAlt',
                'dmg1',
                'dmg2',
                'dmgType',
                'inherits',
                'reqAttuneTags',
            },
            metadata=ITEM_TAXONOMY,
        )

    def item(self, data, level, *, structural, show_type=True):
        self.item_fields(data)
        item_type = (
            self.inline(data['_entryType'])
            if data.get('_entryType')
            else self.values.item_type(data.get('type', 'G'))
        )
        header = [item_type[:1].upper() + item_type[1:]] if item_type and show_type else []
        if data.get('rarity') not in (None, 'none', 'unknown'):
            header.append(data['rarity'])
        if header:
            self.doc.add('*' + ', '.join(header) + '*')
        if data.get('dmg1'):
            self.line(
                'Damage',
                self.inline(data['dmg1'])
                + (' ' + DAMAGE[data['dmgType']] if data.get('dmgType') else ''),
            )
        if data.get('dmg2'):
            self.line('Two-Handed Damage', self.inline(data['dmg2']))
        for field, label in ITEM_FIELDS.items():
            if field not in data:
                continue
            value = data[field]
            if field == 'weight':
                text = f'{value} lb.'
            elif field == 'value':
                text = f'{value / 100:g} GP'
            elif field == 'containerCapacity':
                text = self.values.capacity(value)
            elif field == 'carryingCapacity':
                text = f'{value} lb.'
            elif field == 'capCargo':
                text = f'{value} tons'
            elif field == 'reqAttune':
                text = (
                    'Required'
                    if value is True
                    else 'Required ' + self.inline(value)
                    if value
                    else 'Not required'
                )
            elif field == 'stealth':
                # The complete enhanced entry supplies the sentence; do not print it twice.
                if value and data.get('_fullEntries'):
                    continue
                text = 'Disadvantage on Dexterity (Stealth) checks' if value else 'No Disadvantage'
            elif field in ('mastery', 'property'):
                text = self.values.structure(value, key=field)
            elif field == 'classFeatures':
                references = []
                for uid in value:
                    parts = split_pipes(uid)
                    require(
                        len(parts) == 5,
                        'CLASS_FEATURE_UID',
                        'Unsupported class feature UID',
                        **self.engine.context(),
                    )
                    references.append(
                        self.values.uid(parts[0])
                        + ' ('
                        + parts[1].title()
                        + ' Level '
                        + parts[3]
                        + '; '
                        + parts[4].upper()
                        + ')'
                    )
                text = '; '.join(references)
            elif field == 'speed':
                text = self.values.speed(value)
            elif field in ('resist', 'immune', 'vulnerable'):
                text = self.values.defenses(value, field)
            else:
                text = self.values.structure(value, key=field)
            self.line(label, text)
        if data.get('typeAlt'):
            self.line('Alternative Type', self.values.item_type(data['typeAlt']))
        if data.get('reqAttuneTags') and not isinstance(data.get('reqAttune'), str):
            self.line('Attunement Requirements', self.values.prerequisite(data['reqAttuneTags']))
        self.entries.render(
            data.get('_fullEntries', data.get('entries', [])),
            level,
            structural=structural,
            entry_depth=INLINE_ENTRY_DEPTH,
        )

    def loot(self, data):
        self.fields(data, {'table', 'coins', 'crMin', 'crMax'})
        if 'crMin' in data:
            self.line('Challenge Rating', f'{data["crMin"]}–{data["crMax"]}')
        if data.get('coins'):
            self.line('Coins', self.values.structure(data['coins']))
        rows = []
        for i, entry in enumerate(data['table'], 1):
            if isinstance(entry, str):
                rows.append([i, entry])
            else:
                lower, upper = entry.get('min'), entry.get('max')
                roll = str(lower) if lower == upper else f'{lower}–{upper}'
                result = {key: value for key, value in entry.items() if key not in ('min', 'max')}
                rows.append([roll, self.values.structure(result)])
        self.entries.table({'type': 'table', 'colLabels': ['Roll', 'Result'], 'rows': rows})

    def monster(self, data):
        mechanics = {
            'size',
            'alignment',
            'ac',
            'hp',
            'speed',
            'initiative',
            'str',
            'dex',
            'con',
            'int',
            'wis',
            'cha',
            'save',
            'skill',
            'senses',
            'passive',
            'resist',
            'immune',
            'vulnerable',
            'conditionImmune',
            'gear',
            'languages',
            'cr',
            'pbNote',
            'trait',
            'action',
            'bonus',
            'reaction',
            'legendary',
            'spellcasting',
            'legendaryActions',
            'legendaryActionsLair',
            'legendaryHeader',
            'actionHeader',
            'bonusHeader',
            'reactionHeader',
            'traitHeader',
            'legendaryGroup',
            'alignmentPrefix',
        }
        metadata = {
            'group',
            'environment',
            'treasure',
            'dragonAge',
            'familiar',
            'summonedByClass',
            'summonedBySpell',
            'summonedBySpellLevel',
            'attachedItems',
            'savingThrowForced',
            'savingThrowForcedLegendary',
            'savingThrowForcedSpell',
            'conditionInflict',
            'conditionInflictLegendary',
            'conditionInflictSpell',
            'damageTagsSpell',
        }
        self.fields(data, mechanics, metadata=metadata)
        blocks = ['**' + self.inline(data['name']) + '**']
        kind = data['type']
        if isinstance(kind, str):
            kind_text = kind.title()
        else:
            tags = [
                v if isinstance(v, str) else (v.get('prefix', '') + ' ' + v['tag']).strip()
                for v in kind.get('tags', [])
            ]
            base_type = kind['type']
            base_text = (
                base_type.title()
                if isinstance(base_type, str)
                else ' or '.join(v.title() for v in base_type['choose'])
            )
            if kind.get('swarmSize'):
                base_text = (
                    'Swarm of '
                    + SIZES[kind['swarmSize']]
                    + ' '
                    + base_text
                    + ('es' if base_text.endswith('s') else 's')
                )
            kind_text = base_text + (
                ' (' + ', '.join(v.title() for v in tags) + ')' if tags else ''
            )
        alignment = self.inline(data.get('alignmentPrefix', '')) + ' '.join(
            ALIGNMENTS[v] for v in data.get('alignment', [])
        )
        blocks.append(
            '*'
            + ' or '.join(SIZES[v] for v in data['size'])
            + ' '
            + kind_text
            + (', ' + alignment if alignment else '')
            + '*'
        )
        acs = []
        for ac in data['ac']:
            if isinstance(ac, (str, int)):
                acs.append(self.inline(ac))
            elif 'special' in ac:
                acs.append(self.inline(ac['special']))
            else:
                acs.append(
                    str(ac['ac'])
                    + (
                        ' (' + ', '.join(map(self.inline, ac['from'])) + ')'
                        if ac.get('from')
                        else ''
                    )
                    + (' ' + self.inline(ac['condition']) if ac.get('condition') else '')
                )
        init = ability_mod(data.get('dex'))
        initiative = data.get('initiative')
        advantage = None
        if isinstance(initiative, int):
            init = initiative
        elif isinstance(initiative, dict):
            require(
                set(initiative) <= {'initiative', 'proficiency', 'advantageMode'},
                'INITIATIVE_FORMAT',
                'Unsupported initiative fields',
                **self.engine.context(),
            )
            if 'initiative' in initiative:
                init = initiative['initiative']
            elif initiative.get('proficiency'):
                bonus = pb(data.get('cr'))
                init = (
                    init + initiative['proficiency'] * bonus
                    if init is not None and bonus is not None
                    else None
                )
            advantage = initiative.get('advantageMode')
        init_text = (
            '—'
            if init is None
            else f'{init:+d} ({10 + init + (5 if advantage == "adv" else -5 if advantage == "dis" else 0)})'
        )
        if advantage:
            init_text += ' (' + ('Advantage' if advantage == 'adv' else 'Disadvantage') + ')'
        blocks.append('**AC:** ' + '; '.join(acs) + ' — **Initiative:** ' + init_text)
        hp = data['hp']
        require(
            set(hp) <= {'average', 'formula', 'special'},
            'HP_FORMAT',
            'Unsupported HP fields',
            **self.engine.context(),
        )
        blocks.append(
            '**HP:** '
            + (
                self.inline(hp['special'])
                if 'special' in hp
                else f'{hp["average"]} ({hp["formula"]})'
            )
        )
        blocks.append('**Speed:** ' + self.values.speed(data['speed']))
        scores = [self.values.structure(data[a]) for a in ABILITIES]
        mods = [ability_mod(data[a]) for a in ABILITIES]
        saves = [
            data.get('save', {}).get(a, f'{mod:+d}' if mod is not None else '—')
            for a, mod in zip(ABILITIES, mods)
        ]
        rows = [
            ('Score', scores),
            ('Mod', [f'{v:+d}' if v is not None else '—' for v in mods]),
            ('Save', saves),
        ]
        blocks.append(
            '| | '
            + ' | '.join(a.upper() for a in ABILITIES)
            + ' |\n|:---|'
            + '---:|' * 6
            + '\n'
            + '\n'.join('| ' + name + ' | ' + ' | '.join(values) + ' |' for name, values in rows)
        )
        self.engine.diagnostics.count('statblocks')
        if data.get('skill'):
            blocks.append(
                '**Skills:** '
                + ', '.join(
                    self.values.label(name) + ' ' + self.values.structure(value)
                    for name, value in data['skill'].items()
                )
            )
        for field, label in (
            ('vulnerable', 'Vulnerabilities'),
            ('resist', 'Resistances'),
            ('immune', 'Immunities'),
            ('conditionImmune', 'Condition Immunities'),
        ):
            if data.get(field):
                blocks.append('**' + label + ':** ' + self.values.defenses(data[field], field))
        if data.get('gear'):
            blocks.append('**Gear:** ' + self.values.structure(data['gear'], key='item'))
        passive = data.get('passive')
        if passive is None:
            perception = data.get('skill', {}).get('perception', ability_mod(data.get('wis')))
            if isinstance(perception, str) and re.fullmatch(r'[+-]?\d+', perception):
                perception = int(perception)
            if type(perception) is int:
                passive = 10 + perception
            elif isinstance(perception, str):
                passive = '10 + (' + self.inline(perception) + ')'
            else:
                require(
                    perception is None,
                    'PASSIVE_FORMAT',
                    'Unsupported Perception bonus',
                    **self.engine.context(),
                )
        senses = list(map(self.inline, data.get('senses', [])))
        if passive is not None:
            senses.append('Passive Perception ' + str(passive))
        if senses:
            blocks.append('**Senses:** ' + '; '.join(senses))
        if data.get('languages'):
            blocks.append('**Languages:** ' + ', '.join(map(self.inline, data['languages'])))
        if data.get('cr') is not None:
            cr = data['cr']
            number = cr['cr'] if isinstance(cr, dict) else cr
            xp = cr.get('xp', XP.get(number)) if isinstance(cr, dict) else XP.get(number)
            bonus = pb(cr)
            line = '**CR:** ' + str(number)
            extras = ([f'XP {xp:,}'] if xp is not None else []) + (
                [f'PB {bonus:+d}'] if bonus is not None else []
            )
            if extras:
                line += ' (' + '; '.join(extras) + ')'
            if isinstance(cr, dict) and 'xpLair' in cr:
                line += f'; XP in Lair {cr["xpLair"]:,}'
            blocks.append(line)
        if data.get('pbNote'):
            blocks.append('**PB:** ' + self.inline(data['pbNote']))
        for spell in data.get('spellcasting', []):
            require(
                spell.get('displayAs', 'trait')
                in {'trait', 'action', 'bonus', 'reaction', 'legendary'},
                'SPELLCASTING_POSITION',
                'Unsupported spellcasting section',
                **self.engine.context(),
            )
        for field, title in (
            ('trait', 'Traits'),
            ('action', 'Actions'),
            ('bonus', 'Bonus Actions'),
            ('reaction', 'Reactions'),
            ('legendary', 'Legendary Actions'),
        ):
            spells = [
                spell
                for spell in data.get('spellcasting', [])
                if spell.get('displayAs', 'trait') == field
            ]
            if not data.get(field) and not spells:
                continue
            blocks.extend(('---', '**' + title + '**'))
            if data.get(field + 'Header'):
                blocks.append(self.entries.compact(data[field + 'Header']))
            elif field == 'legendary':
                uses = data.get('legendaryActions', 3)
                lair = data.get('legendaryActionsLair', uses)
                blocks.append(
                    f'Legendary Action Uses: {uses}'
                    + (f' ({lair} in Lair)' if lair != uses else '')
                    + f". Immediately after another creature's turn, {data['name']} can expend a use to take one of the following actions. {data['name']} regains all expended uses at the start of each of its turns."
                )
            for action in data.get(field, []):
                blocks.append(
                    '**'
                    + self.inline(action.get('name', '')).rstrip('.')
                    + '.** '
                    + self.entries.compact(action.get('entries', []))
                )
            for spell in spells:
                blocks.append(self.spellcasting(spell))
        self.doc.add(quote('\n\n'.join(blocks)))

    def spellcasting(self, spell):
        allowed = {
            'name',
            'type',
            'headerEntries',
            'footerEntries',
            'ability',
            'displayAs',
            'hidden',
            'will',
            'constant',
            'daily',
            'rest',
            'restLong',
            'weekly',
            'monthly',
            'yearly',
            'recharge',
            'legendary',
            'spells',
            'charges',
            'chargesItem',
        }
        require(
            not set(spell) - allowed,
            'SPELLCASTING_FIELD',
            ', '.join(sorted(set(spell) - allowed)),
            **self.engine.context(),
        )
        require(
            spell.get('displayAs', 'trait')
            in {'trait', 'action', 'bonus', 'reaction', 'legendary'},
            'SPELLCASTING_POSITION',
            'Unsupported spellcasting section',
            **self.engine.context(),
        )
        out = [
            '**'
            + self.inline(spell['name']).rstrip('.')
            + '.** '
            + self.entries.compact(spell.get('headerEntries', []))
        ]
        for field, label in (('will', 'At will'), ('constant', 'Constant')):
            if spell.get(field):
                out.append('- ' + label + ': ' + ', '.join(map(self.inline, spell[field])))
        for field, label in (
            ('daily', 'day'),
            ('rest', 'rest'),
            ('restLong', 'Long Rest'),
            ('weekly', 'week'),
            ('monthly', 'month'),
            ('yearly', 'year'),
            ('recharge', 'recharge'),
            ('legendary', 'Legendary Action'),
        ):
            for frequency, spells in spell.get(field, {}).items():
                suffix = ' each' if frequency.endswith('e') else ''
                out.append(
                    f'- {frequency.rstrip("e")}/{label}{suffix}: '
                    + ', '.join(map(self.inline, spells))
                )
        if spell.get('spells'):
            for level, group in spell['spells'].items():
                out.append(
                    f'- Spell level {level}'
                    + (f' ({group["slots"]} slots)' if 'slots' in group else '')
                    + ': '
                    + ', '.join(map(self.inline, group['spells']))
                )
        if spell.get('charges'):
            out.append('Charges: ' + self.values.structure(spell['charges']))
        if spell.get('footerEntries'):
            out.append(self.entries.compact(spell['footerEntries']))
        return '\n\n'.join(out)
