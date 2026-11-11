"""Local evidence that complete entry structures already occur in a parent.

Numbers, ordering, list styles, table associations and unknown fields remain
part of the comparison. Only provenance and table layout metadata are ignored.
"""

import re

PROVENANCE = frozenset(
    ('id', 'source', 'page', '__prop', 'srd', 'srd52', 'basicRules', 'basicRules2024')
)
TABLE_LAYOUT = frozenset(
    ('colStyles', 'rowStyles', 'isStriped', 'isRollable', 'rollMode', 'isNameGenerator')
)
VISIBLE_CHILDREN = (
    'name',
    'entries',
    '_fullEntries',
    'entry',
    'items',
    'rows',
    'row',
    'colLabels',
    'colLabelRows',
    'wrapped',
    'caption',
    'table',
    'footnotes',
    'intro',
    'outro',
)


def normalized(value, inline):
    if isinstance(value, str):
        return ('text', ' '.join(inline(value, plain=True).split()).casefold())
    if isinstance(value, list):
        return ('list', tuple(normalized(child, inline) for child in value))
    if isinstance(value, dict):
        if value.get('type') == 'wrapper' and set(value) <= PROVENANCE | {
            'type',
            'wrapped',
            'data',
        }:
            return normalized(value['wrapped'], inline)
        fields = {key: child for key, child in value.items() if key not in PROVENANCE}
        if value.get('type') == 'table':
            fields = {key: child for key, child in fields.items() if key not in TABLE_LAYOUT}
        if 'entries' in fields and fields.get('type', 'entries') in ('section', 'entries'):
            fields['type'] = 'entries'
        return (
            'object',
            tuple(sorted((key, normalized(child, inline)) for key, child in fields.items())),
        )
    return (type(value).__name__, value)


def visible_nodes(node, children=VISIBLE_CHILDREN):
    yield node
    if isinstance(node, dict):
        if node.get('kind') == 'embedded_entity':
            yield from visible_nodes(node['data'], children)
            return
        for key in children:
            if key in node:
                yield from visible_nodes(node[key], children)
    elif isinstance(node, list):
        for child in node:
            yield from visible_nodes(child, children)


def narrative_strings(node, inline):
    """Normalize main prose to check whether it already describes cantrip scaling."""
    children = (
        'name',
        'entries',
        '_fullEntries',
        'entry',
        'items',
        'rows',
        'row',
        'colLabels',
        'colLabelRows',
        'wrapped',
        'caption',
        'table',
    )
    return {
        ' '.join(inline(value, plain=True).split()).casefold()
        for value in visible_nodes(node, children)
        if isinstance(value, str)
    }


def represented(entry, scope, inline):
    """Match one complete subtree or an ordered, contiguous entry sequence."""
    if isinstance(entry, list) and not entry:
        return False
    expected = normalized(entry, inline)
    for candidate in visible_nodes(scope):
        actual = normalized(candidate, inline)
        if expected == actual:
            return True
        if isinstance(entry, list) and isinstance(candidate, list):
            wanted, available = expected[1], actual[1]
            if any(
                available[i : i + len(wanted)] == wanted
                for i in range(len(available) - len(wanted) + 1)
            ):
                return True
    return False


def named_entries_represented(name, entries, scope, inline):
    """Keep a card's complete rule sequence associated with its own title."""
    if not entries:
        return represented(name, scope, inline)
    expected = normalized(entries if isinstance(entries, list) else [entries], inline)[1]
    for candidate in visible_nodes(scope):
        if not isinstance(candidate, dict) or normalized(
            candidate.get('name', ''), inline
        ) != normalized(name, inline):
            continue
        body = candidate.get('entries', candidate.get('entry', []))
        actual = normalized(body if isinstance(body, list) else [body], inline)[1]
        if any(
            actual[i : i + len(expected)] == expected
            for i in range(len(actual) - len(expected) + 1)
        ):
            return True
    return False


def ordered_entries_represented(entries, body, inline):
    """Check one owner's rule sequence, allowing additional inline paragraphs."""
    expected = normalized(entries if isinstance(entries, list) else [entries], inline)[1]
    available = normalized(body if isinstance(body, list) else [body], inline)[1]
    index = 0
    for entry in available:
        if index < len(expected) and entry == expected[index]:
            index += 1
    return index == len(expected)


def labelled_list_represented(entry, source, inline):
    """Prove an ordered projection of complete named list items.

    Native item grammar allows `entry: text` and `entries: [text]`. Extra
    source rows, such as Weight, stay in their original list and order.
    """

    def rows(node):
        if not isinstance(node, dict) or node.get('type') != 'list' or not node.get('items'):
            return None
        result = []
        for item in node['items']:
            if not isinstance(item, dict) or item.get('type') != 'item' or not item.get('name'):
                return None
            item = dict(item)
            if 'entry' in item and 'entries' not in item:
                item['entries'] = [item.pop('entry')]
            result.append(normalized(item, inline))
        return result

    expected, available = rows(entry), rows(source)
    if (
        not expected
        or not available
        or normalized({k: v for k, v in entry.items() if k != 'items'}, inline)
        != normalized({k: v for k, v in source.items() if k != 'items'}, inline)
    ):
        return False
    index = 0
    for row in available:
        if index < len(expected) and row == expected[index]:
            index += 1
    return index == len(expected)


def deck_roll_projection(entry, scope, inline):
    """Prove a deck's two-column view against one complete parent roll column."""
    if not isinstance(entry, dict) or entry.get('type') != 'table':
        return False
    rows = entry.get('rows')
    if not rows or not all(
        isinstance(row, list) and len(row) == 2 and all(isinstance(c, str) for c in row)
        for row in rows
    ):
        return False
    labels = entry.get('colLabels')
    if not isinstance(labels, list) or len(labels) != 2:
        return False

    def norm(text):
        return normalized(text, inline)[1].replace('–', '-')

    if not all(re.fullmatch(r'\d+(?:-\d+)?', norm(row[0])) for row in rows):
        return False
    for source in visible_nodes(scope):
        if not isinstance(source, dict) or source.get('type') != 'table':
            continue
        source_labels = source.get('colLabels', [])
        if (
            len(source_labels) < 2
            or norm(source_labels[-1]) != norm(labels[-1])
            or norm(source.get('caption', '')) != norm(entry.get('caption', ''))
        ):
            continue
        remaining = (
            set(entry) - PROVENANCE - TABLE_LAYOUT - {'type', 'rows', 'colLabels', 'caption'}
        )
        if any(
            key not in source or not represented(entry[key], source[key], inline)
            for key in remaining
        ):
            continue
        for index in range(len(source_labels) - 1):
            pairs = {
                (norm(row[index]), norm(row[-1]))
                for row in source.get('rows', [])
                if isinstance(row, list)
                and len(row) == len(source_labels)
                and all(isinstance(c, str) for c in row)
            }
            if all((norm(a), norm(b)) in pairs for a, b in rows):
                return True
    return False


def numbered_table_represented(values, scope, inline, caption):
    """Match every numbered loot result and its value category in the anchor."""
    expected = [
        (normalized(str(i), inline), normalized(value, inline)) for i, value in enumerate(values, 1)
    ]
    for table in visible_nodes(scope):
        if not isinstance(table, dict) or table.get('type') != 'table':
            continue
        if normalized(table.get('caption', ''), inline) != normalized(caption, inline):
            continue
        rows = table.get('rows', [])
        if len(rows) != len(expected) or not all(
            isinstance(row, list)
            and len(row) == 2
            and type(row[0]) in (str, int)
            and isinstance(row[1], str)
            for row in rows
        ):
            continue
        actual = [(normalized(str(row[0]), inline), normalized(row[1], inline)) for row in rows]
        if expected and actual == expected:
            return True
    return False
