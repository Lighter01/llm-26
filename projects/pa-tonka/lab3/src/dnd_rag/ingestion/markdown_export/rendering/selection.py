"""Choose missing catalog content using evidence local to its book placement.

The source chapter remains authoritative. This module neither changes source
nodes nor compares unrelated sections, and returns only an in-memory view.
"""

import re
from dataclasses import dataclass
from fractions import Fraction

from ..common.model import require
from .inline import split_pipes
from .payloads import CACHE_FIELDS, COMMON_METADATA, RULE_DATA_FIELDS
from .representation import (
    PROVENANCE,
    labelled_list_represented,
    normalized,
    represented,
    visible_nodes,
)


@dataclass
class Selection:
    data: dict | None
    decision: str
    evidence: dict


def text(value, inline):
    return ' '.join(inline(value, plain=True).split()).casefold()


def reference(value, tag):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\{@' + re.escape(tag) + r' ([^{}]+)\}', value)
    if not match:
        return None
    parts = split_pipes(match[1])
    return tuple(part.strip().casefold() for part in parts[:2]) if len(parts) >= 2 else None


def source_info(engine, entity):
    anchor = entity['canonical_placement']['anchor']
    return engine.domain.source[(anchor['chapter_index'], anchor['origin']['json_pointer'])]


def select_content(engine, entity):
    """A choice exists only for supported, evidenced alternate representations."""
    if entity['representation'] != 'domain_component':
        return None
    prop = entity['prop']
    relation = entity['canonical_placement']['relation']
    data = engine.domain.payload(entity)
    if prop == 'language' and auxiliary_language(data, source_info(engine, entity)['node']):
        engine.payloads.fields(data, {'typicalSpeakers'})
        return Selection(
            None,
            'metadata_only',
            {'reason': 'speaker index at a creature placement, without language rules'},
        )
    if prop == 'item' and relation == 'defining_table_reference':
        return select_item(engine, entity, data)
    if prop == 'item' and relation in ('named_source_section_or_row', 'documented_label_alias'):
        return select_anchored_item(engine, entity, data)
    if prop == 'item' and relation == 'pack_content':
        return select_bundle_member(engine, entity, data)
    if prop == 'reward' and relation == 'facility_reward':
        return select_reward(engine, entity, data)
    return None


def auxiliary_language(data, anchor):
    if set(data) - PROVENANCE - {'name'} != {'typicalSpeakers'}:
        return False
    speakers = data['typicalSpeakers']
    if (
        not isinstance(speakers, list)
        or not speakers
        or not all(reference(speaker, 'creature') for speaker in speakers)
    ):
        return False
    if reference(anchor, 'creature'):
        return True
    return any(
        isinstance(node, dict)
        and node.get('kind') == 'embedded_entity'
        and node.get('lookup', {}).get('prop') == 'monster'
        for node in visible_nodes(anchor)
    )


def choice(engine, entity, data, covered, *, entries=None, conflict=None):
    """Retain all unproved fields, including fields outside the coverage adapters."""
    if not covered:
        return None
    preferred = conflict.get('fields', {}) if conflict else {}
    remaining = {
        key: value
        for key, value in data.items()
        if key not in covered
        and key not in preferred
        and key not in COMMON_METADATA | CACHE_FIELDS
        and not key.endswith('Tags')
    }
    # Typed adapters print type even though it is common metadata.
    if 'type' in data and 'type' not in covered:
        remaining['type'] = data['type']
    if entries is not None:
        remaining.pop('_fullEntries', None)
        remaining.pop('entries', None)
        if entries:
            remaining['entries'] = entries
    partial = bool(remaining)
    view = {key: data[key] for key in ('name', 'source', 'page', '__prop') if key in data}
    view.update(remaining)
    if conflict:
        decision = 'source_preferred'
    elif partial:
        decision = 'rendered_in_parent' if engine.entity_stack else 'rendered'
    else:
        decision = 'already_represented'
    evidence = {
        'reason': 'local book rules/table fields and catalog metadata checked individually',
        'coverage': covered,
        'remaining_fields': sorted(remaining),
        'source_anchor': entity['canonical_placement']['anchor']['origin']['json_pointer'],
        'parent': entity['canonical_placement']['parent_entity_id'],
    }
    if conflict:
        evidence['conflict'] = conflict
        engine.diagnostics.note('DOMAIN_SOURCE_CONFLICT', entity=entity['entity_id'], **conflict)
    return Selection(view if partial else None, decision, evidence)


def entry_matches(entries, source, inline, entity):
    """Consume each source occurrence once, in book order."""
    source_values = [normalized(node, inline) for node in source]
    matches = []
    cursor = 0
    for index, entry in enumerate(entries):
        expected = normalized(entry, inline)
        position = next(
            (i for i in range(cursor, len(source)) if source_values[i] == expected), None
        )
        if position is not None:
            matches.append(index)
            cursor = position + sum(
                1 for _ in visible_nodes(source[position], children=('entries',))
            )
        else:
            require(
                expected not in source_values[:cursor],
                'AMBIGUOUS_DOMAIN_COVERAGE',
                'Catalog rule order/multiplicity conflicts with the local book sequence',
                entity=entity['entity_id'],
            )
    return matches


def item_rule_nodes(node, owners, shared, inline):
    """Only this item's named rules and its explicitly linked shared templates."""
    if shared and normalized(node, inline) in shared:
        yield from visible_nodes(node, children=('entries',))
    elif isinstance(node, list):
        for child in node:
            yield from item_rule_nodes(child, owners, shared, inline)
    elif isinstance(node, dict):
        if any(node is owner for owner in owners):
            yield from visible_nodes(node.get('entries', []), children=('entries',))
        else:
            yield from item_rule_nodes(node.get('entries', []), owners, shared, inline)


def quantity(value, inline):
    match = re.fullmatch(
        r'((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|[0-9]+/[1-9][0-9]*|[0-9]*½)'
        r'\s*(lb\.|[csegp]p)(\s+\([^()]+\))?',
        text(value, inline),
    )
    if not match:
        return None
    number = match[1].replace(',', '')
    if number.endswith('½'):
        amount = Fraction(number[:-1] or 0) + Fraction(1, 2)
    else:
        amount = Fraction(number)
    return amount, match[2], (match[3] or '').strip()


def table_fields(data, cells, inline):
    covered, conflicts = {}, {}
    for field, column, unit in (('weight', 'weight', 'lb.'), ('value', 'cost', None)):
        if field not in data or not isinstance(cells.get(column), str):
            continue
        parsed = quantity(cells[column], inline)
        if not parsed:
            continue
        amount, actual_unit, note = parsed
        if unit:
            if actual_unit != unit or note != text(data.get('weightNote', ''), inline):
                continue
        else:
            multiplier = {'cp': 1, 'sp': 10, 'ep': 50, 'gp': 100, 'pp': 1000}.get(actual_unit)
            if multiplier is None or note:
                continue
            amount *= multiplier
        if amount == Fraction(str(data[field])):
            covered[field] = 'book property: ' + column
            if field == 'weight' and note:
                covered['weightNote'] = 'same weight qualifier in book property'
        else:
            conflicts[field] = {'book': cells[column], 'catalog': data[field]}
    return covered, conflicts


def select_item(engine, entity, data):
    """Compare a typed defining row with its own rules and linked templates."""
    engine.payloads.item_fields(data)
    inline = engine.inline
    info = source_info(engine, entity)
    table = next((n for n in reversed(info['ancestors']) if n.get('type') == 'table'), None)
    scope = next(
        (n for n in reversed(info['ancestors']) if n.get('type') in ('section', 'entries')),
        None,
    )
    if table is None or scope is None:
        return None
    uid = (data['name'].casefold(), data['source'].casefold())
    if reference(info['node'], 'item') != uid:
        return None
    rows = [
        row
        for row in table.get('rows', [])
        if isinstance(row, list) and row and reference(row[0], 'item') == uid
    ]
    require(
        len(rows) <= 1,
        'AMBIGUOUS_DOMAIN_COVERAGE',
        'Expected one defining item row',
        entity=entity['entity_id'],
    )
    if not rows:
        return None  # Wrapped/spanned rows retain the complete catalog view.
    columns = [text(label, inline) for label in table.get('colLabels', [])]
    if len(columns) != len(rows[0]) or len(set(columns)) != len(columns):
        return None
    cells = dict(zip(columns, rows[0]))
    covered, conflicts = table_fields(data, cells, inline)

    source = list(visible_nodes(scope.get('entries', []), children=('entries',)))
    names = {text(data['name'], inline), text(info['node'], inline)}
    if isinstance(cells.get('cost'), str):
        names |= {name + ' (' + text(cells['cost'], inline) + ')' for name in names}
    named = [
        node
        for node in source
        if isinstance(node, dict) and text(node.get('name', ''), inline) in names
    ]
    require(
        len(named) <= 1,
        'AMBIGUOUS_DOMAIN_COVERAGE',
        'Multiple local item definitions',
        entity=entity['entity_id'],
    )
    entries = data.get('_fullEntries', data.get('entries', []))
    if not isinstance(entries, list):
        return None
    shared = []
    for template in engine.domain.linked(entity, 'structural_string_reference'):
        if template['prop'] == 'itemEntry':
            payload = engine.domain.payload(template)
            engine.payloads.fields(payload, {'entriesTemplate'})
            shared.extend(normalized(entry, inline) for entry in payload.get('entriesTemplate', []))
    candidates = list(item_rule_nodes(scope.get('entries', []), named, shared, inline))
    matches = entry_matches(entries, candidates, inline, entity)
    remaining = list(entries)
    conflict = None
    if matches:
        remaining = [entry for index, entry in enumerate(entries) if index not in matches]
        if len(named) == 1 and remaining:
            conflict = conflicting_lead(remaining, named[0].get('entries', []), inline)
            if conflict:
                remaining.remove(remaining[0])
    else:
        projection = container_projection(data['name'], entries, source, inline)
        if projection:
            remaining = []
            covered['entries'] = 'complete labelled container alternative in book rule'
    if len(remaining) == len(entries):
        return None  # This card still supplies its own missing description.
    if conflicts:
        conflict = {**(conflict or {}), 'fields': conflicts}
    covered.setdefault(
        'entries',
        {'method': 'ordered local entry matches', 'matched': len(matches), 'total': len(entries)},
    )
    if '_fullEntries' in data:
        covered['_fullEntries'] = 'effective rendered description'
    if not remaining:
        if data.get('rarity') == 'none':
            covered['rarity'] = 'no rarity rule'
        item_type = data.get('type', '').split('|')[0]
        if (
            item_type == 'G'
            or item_type == 'EXP'
            and any(
                re.search(r'\bexplosives?\b', text(value, inline))
                for value in (scope.get('name', ''), table.get('caption', ''))
            )
        ):
            covered['type'] = 'catalog category; book context retained'
        if 'age' in data:
            covered['age'] = 'catalog technology-era filter'
        if 'valueRarity' in data and text(cells.get('cost', ''), inline) == '—':
            policy = re.compile(
                r"if no cost is given [^.]+, it can't typically be bought\. "
                r'if you make these [^.]+ available for purchase, treat them as (\w+) magic items\.'
            )
            if any(
                (match := policy.search(text(node, inline)))
                and match[1] == data['valueRarity'].casefold()
                for node in scope.get('entries', [])
                if isinstance(node, str)
            ):
                covered['valueRarity'] = 'unpriced defining row and explicit purchase policy'
    return choice(engine, entity, data, covered, entries=remaining, conflict=conflict)


def select_anchored_item(engine, entity, data):
    """Compare descriptions/property lists at a declared section or service alias."""
    engine.payloads.item_fields(data)
    info = source_info(engine, entity)
    anchor = info['node']
    inline = engine.inline
    cells, covered = {}, {}
    entries = data.get('_fullEntries', data.get('entries', []))
    if not isinstance(entries, list):
        return None
    if isinstance(anchor, dict) and anchor.get('type') in ('section', 'entries'):
        title = re.fullmatch(r'(.+) \(([^()]+)\)', text(anchor.get('name', ''), inline))
        if title and title[1] == text(data['name'], inline) and quantity(title[2], inline):
            cells['cost'] = title[2]
        source = list(visible_nodes(anchor.get('entries', []), children=('entries',)))
        matches = entry_matches(entries, source, inline, entity)
        for index, entry in enumerate(entries):
            if index in matches:
                continue
            if any(labelled_list_represented(entry, node, inline) for node in source):
                matches.append(index)
                continue
            if (
                isinstance(entry, dict)
                and entry.get('type') == 'wrapper'
                and entry.get('data') == {'item__mergedEntryTag': 'type'}
                and set(entry) <= PROVENANCE | {'type', 'wrapped', 'data'}
            ):
                wrapped = entry.get('wrapped', {})
                if (
                    not isinstance(wrapped, dict)
                    or wrapped.get('type') != 'entries'
                    or set(wrapped) - PROVENANCE - {'type', 'name', 'entries'}
                ):
                    continue
                types = engine.domain.linked(entity, 'item_type')
                if any(
                    represented(wrapped, engine.domain.payload(item_type), inline)
                    for item_type in types
                ) and any(
                    represented(wrapped.get('entries', []), ancestor, inline)
                    for ancestor in info['ancestors'][1:]
                ):
                    matches.append(index)
                    covered['type'] = 'linked type rules already present in enclosing book section'
        remaining = [entry for index, entry in enumerate(entries) if index not in matches]
        if not matches:
            return None
        covered['entries'] = {
            'method': 'named book entries and complete labelled-list/type projections',
            'matched': len(matches),
            'total': len(entries),
        }
        for node in visible_nodes(anchor.get('entries', [])):
            if (
                isinstance(node, dict)
                and node.get('type') == 'item'
                and text(node.get('name', ''), inline) == 'weight:'
            ):
                value = node.get('entries', [node.get('entry')])
                if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
                    require(
                        'weight' not in cells,
                        'AMBIGUOUS_DOMAIN_COVERAGE',
                        'Multiple named Weight properties',
                        entity=entity['entity_id'],
                    )
                    cells['weight'] = value[0]
    else:
        # A declared label alias can point to a service row with no description.
        row = next(
            (node for node in reversed(info['ancestors']) if node.get('type') == 'row'), None
        )
        table = next(
            (node for node in reversed(info['ancestors']) if node.get('type') == 'table'), None
        )
        if entries or row is None or table is None:
            return None
        values, labels = row.get('row', []), table.get('colLabels', [])
        if len(values) != len(labels) or not values or values[0] != anchor:
            return None
        cells = dict(zip((text(label, inline) for label in labels), values))
        remaining = []
        covered['entries'] = 'service label without a description'
        covered['type'] = 'catalog taxonomy for a service row'
    properties, conflicts = table_fields(data, cells, inline)
    covered.update(properties)
    if data.get('rarity') == 'none':
        covered['rarity'] = 'no rarity rule'
    if data.get('type', '').split('|')[0] == 'G':
        covered['type'] = 'catalog adventuring-gear category'
    if '_fullEntries' in data:
        covered['_fullEntries'] = 'effective rendered description'
    return choice(
        engine,
        entity,
        data,
        covered,
        entries=remaining,
        conflict={'fields': conflicts} if conflicts else None,
    )


def select_bundle_member(engine, entity, data):
    """A single-kind bundle can represent the same rules and proportional fields."""
    engine.payloads.item_fields(data)
    parent_id = entity['canonical_placement']['parent_entity_id']
    parent = engine.domain.entities.get(parent_id)
    decision = engine.diagnostics.components.get(parent_id, {})
    if (
        parent is None
        or parent['prop'] != 'item'
        or 'packContents' not in decision.get('remaining_fields', [])
    ):
        return None
    payload = engine.domain.payload(parent)
    contents = payload.get('packContents', [])
    if (
        not isinstance(contents, list)
        or len(contents) != 1
        or not isinstance(contents[0], dict)
        or set(contents[0]) != {'item', 'quantity'}
    ):
        return None
    uid, count = contents[0]['item'], contents[0]['quantity']
    if (
        not isinstance(uid, str)
        or uid.casefold() != (data['name'] + '|' + data['source']).casefold()
        or type(count) is not int
        or count <= 0
    ):
        return None
    entries = data.get('_fullEntries', data.get('entries', []))
    if (
        not entries
        or 'entries' in decision['remaining_fields']
        or not decision.get('coverage', {}).get('entries')
        or normalized(entries, engine.inline)
        != normalized(payload.get('_fullEntries', payload.get('entries', [])), engine.inline)
    ):
        return None
    covered = {'entries': 'same complete rules in book-covered single-kind bundle'}
    for field in ('weight', 'value'):
        if (
            field in data
            and field in decision['coverage']
            and Fraction(str(data[field])) * count == Fraction(str(payload[field]))
        ):
            covered[field] = f'{count} identical units equal the book-covered bundle field'
    if data.get('type') == payload.get('type'):
        covered['type'] = 'same item category as the represented bundle'
    if data.get('rarity') == payload.get('rarity'):
        covered['rarity'] = 'same rarity as the represented bundle'
    if '_fullEntries' in data:
        covered['_fullEntries'] = 'effective rendered description'
    return choice(engine, entity, data, covered, entries=[])


def conflicting_lead(entries, source, inline):
    """Report alternate introductory clauses; never declare them equivalent.

    The complete rule after the first comma must match exactly. The source
    clause is retained; diagnostics carry both clauses for explicit review.
    """
    if not entries or not isinstance(entries[0], str):
        return None
    catalog_lead, comma, rest = text(entries[0], inline).partition(', ')
    if not comma:
        return None
    candidates = []
    for node in source:
        if isinstance(node, str):
            book_lead, comma, book_rest = text(node, inline).partition(', ')
            if comma and book_rest == rest and book_lead != catalog_lead:
                candidates.append({'catalog_clause': catalog_lead, 'book_clause': book_lead})
    return candidates[0] if len(candidates) == 1 else None


def container_projection(name, entries, source, inline):
    """Verify a complete, explicitly labelled damage alternative, not matching dice.

    Container-specific catalog prose must equal the entire book paragraph after
    selecting its labelled branch and substituting the container noun.
    """
    variant = re.fullmatch(r'(.+) \(([^()]+)\)', name)
    if not variant or len(entries) != 1 or not isinstance(entries[0], str):
        return False
    alternative = re.compile(r'\d+ \([^()]+\) \w+ damage \(for an? ([^()]+)\)')
    for owner in source:
        if not isinstance(owner, dict) or text(owner.get('name', ''), inline) != text(
            variant[1], inline
        ):
            continue
        for paragraph in owner.get('entries', []):
            if not isinstance(paragraph, str):
                continue
            plain = text(paragraph, inline)
            branches = list(alternative.finditer(plain))
            if len(branches) < 2 or any(
                plain[a.end() : b.start()] != ' or ' for a, b in zip(branches, branches[1:])
            ):
                continue
            selected = [m for m in branches if m[1] == variant[2].casefold()]
            if len(selected) != 1:
                continue
            value = selected[0][0].rsplit(' (for ', 1)[0]
            projected = plain[: branches[0].start()] + value + plain[branches[-1].end() :]
            projected = re.sub(r'\bcontainer\b', lambda _: variant[2].casefold(), projected)
            if projected == text(entries[0], inline):
                return True
    return False


def select_reward(engine, entity, data):
    engine.payloads.fields(data, RULE_DATA_FIELDS)
    parent_id = entity['canonical_placement']['parent_entity_id']
    parent = engine.domain.entities.get(parent_id)
    if parent is None or parent['prop'] != 'facility':
        return None
    payload = engine.domain.payload(parent)
    inline = engine.inline
    owners = [
        node
        for node in visible_nodes(payload.get('entries', []))
        if isinstance(node, dict)
        and text(node.get('name', ''), inline) == text(data['name'], inline)
    ]
    require(
        len(owners) <= 1,
        'AMBIGUOUS_DOMAIN_COVERAGE',
        'Multiple named reward rules in the canonical facility',
        entity=entity['entity_id'],
    )
    if not owners or not isinstance(data.get('entries'), list) or not data['entries']:
        return None
    source = list(visible_nodes(owners[0].get('entries', []), children=('entries',)))
    matches = entry_matches(data['entries'], source, inline, entity)
    if not matches:
        return None
    remaining = [entry for index, entry in enumerate(data['entries']) if index not in matches]
    covered = {
        'entries': {
            'method': 'named rule sequence in canonical facility',
            'matched': len(matches),
            'total': len(data['entries']),
        }
    }
    prose = ' '.join(text(node, inline) for node in source if isinstance(node, str))
    if data.get('type') and re.search(
        r'\bgain a magical ' + re.escape(data['type'].casefold()) + r'\b', prose
    ):
        covered['type'] = 'explicit reward type in facility prose'
    uid = (payload['name'] + '|' + payload.get('source', engine.domain.id)).casefold()
    if data.get('seeAlsoFacility') == [uid]:
        covered['seeAlsoFacility'] = 'back-reference to canonical parent'
    if reward_spell_represented(data.get('additionalSpells'), owners[0].get('entries', []), inline):
        covered['additionalSpells'] = 'same typed spell, one nonrenewable use in facility prose'
    return choice(engine, entity, data, covered, entries=remaining)


def reward_spell_represented(spells, entries, inline):
    for paragraph in entries:
        if not isinstance(paragraph, str):
            continue
        match = re.search(
            r'The [^.]+ allows you to cast (\{@spell [^{}]+\}) (?:once )?without expending a spell slot(?: or using Material components)?\.',
            paragraph,
        )
        if not match or 'or until you use it.' not in text(paragraph, inline):
            continue
        uid = reference(match[1], 'spell')
        if uid and spells == [{'innate': {'_': {'limited': {'1': ['|'.join(uid)]}}}}]:
            return True
    return False
