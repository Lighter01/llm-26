"""Native entry AST, lists, tables and separated blocks."""

import re

from ..common.model import ExportError, pointer_token, require
from .document import Document
from .inline import ABILITIES

# Paragraph-rule nesting is independent of the emitted Markdown heading level.
INLINE_ENTRY_DEPTH = 2
ENTRY_CONTAINERS = frozenset(
    ('section', 'entries', 'options', 'variantInner', 'variant', 'inline', 'inlineBlock')
)

ENTRY_METADATA = frozenset(
    (
        'id',
        'source',
        'page',
        'srd',
        'srd52',
        'basicRules',
        'basicRules2024',
        'style',
        'styles',
        'columns',
        'colStyles',
        'rowStyles',
        'isNamePrefix',
        'data',
        'name',
        'type',
        'className',
        'classSource',
        'subclassShortName',
        'subclassSource',
        'level',
        'header',
        '__prop',
        'hasFluffImages',
        'nameDot',
        'gainSubclassFeature',
    )
)


def quote(text):
    return '\n'.join('> ' + line if line else '>' for line in text.rstrip('\n').split('\n'))


class Entries:
    def __init__(self, engine):
        self.engine = engine

    @property
    def doc(self):
        return self.engine.doc

    @property
    def inline(self):
        return self.engine.inline

    def compact(self, node, *, boxed=False):
        temporary = Document(
            self.doc.book_id,
            self.doc.title,
            self.doc.upstream_sha,
            self.inline,
            evidence_sink=self.doc.evidence,
        )
        other = self.engine.fork(temporary)
        other.entries.render(node, structural=False, boxed=boxed)
        return ''.join(temporary.parts).rstrip('\n')

    def label(self, text, level, *, structural=True, page=None, fallback=None, partial=False):
        if structural and level <= 6:
            self.doc.heading(text, level, page=page, fallback=fallback, partial=partial)
            return level + 1
        if structural:
            self.engine.diagnostics.note(
                'DEEP_SECTION_LABEL',
                heading_path=self.doc.path,
                title=self.inline(text, plain=True),
            )
        if page is not None or fallback is not None or partial:
            self.doc.evidence(page, unknown=partial or page is None, fallback=fallback)
        self.doc.add('**' + self.inline(text) + '**')
        return level

    def render(
        self,
        node,
        level=2,
        *,
        source=None,
        structural=True,
        skip_name=None,
        boxed=False,
        route=True,
        entry_depth=0,
        prefix='',
    ):
        if node is None:
            raise ExportError(
                'NULL_ENTRY', 'Null is not a renderable entry', **self.engine.context()
            )
        if prefix and not (isinstance(node, (str, int, float)) or isinstance(node, list) and node):
            self.doc.add(prefix.rstrip())
            prefix = ''
        if isinstance(node, (str, int, float)) and not isinstance(node, bool):
            text = self.inline(node)
            text = re.sub(r'(?m)^(#{1,6})(?=\s)', r'\\\1', text)
            text = re.sub(r'(?m)^( {0,3})([=-]+)([ \t]*)$', r'\1\\\2\3', text)
            self.doc.add(prefix + text)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                child_source = (source[0], source[1] + '/' + str(i)) if source else None
                self.render(
                    value,
                    level,
                    source=child_source,
                    structural=structural,
                    boxed=boxed,
                    entry_depth=entry_depth,
                    prefix=prefix if i == 0 else '',
                )
        elif isinstance(node, dict):
            if source:
                self.engine.source_context = source
            if route and node.get('__prop') in self.engine.inline_props:
                # Classify its canonical origin before the raw page can seed
                # a context for children or inherited evidence.
                self.engine.native(node, level, structural=structural)
            else:
                pages = self.engine.pages.node(node, self.engine.page_context, source)
                with self.engine.page_scope(pages):
                    if node.get('kind') == 'embedded_entity':
                        self.engine.wrapper(node, level, structural=structural)
                    elif source and self.engine.monster_group(node, level, source):
                        pass
                    else:
                        self._node(
                            node, level, source, structural, skip_name, boxed, entry_depth, pages
                        )
        else:
            raise ExportError(
                'ENTRY_VALUE', f'Unsupported value {type(node).__name__}', **self.engine.context()
            )
        if source:
            self.engine.after_source(source, level, structural=structural)

    def _node(self, node, level, source, structural, skip_name, boxed, entry_depth, pages):
        kind = node.get('type', 'entries')

        def child(value, field, *, depth=level, **options):
            child_source = (source[0], source[1] + '/' + pointer_token(field)) if source else None
            self.render(
                value,
                depth,
                source=child_source,
                structural=structural,
                boxed=boxed,
                entry_depth=entry_depth,
                **options,
            )

        if kind in ('image', 'gallery'):
            self.engine.diagnostics.count(
                'omitted_images' if kind == 'image' else 'omitted_galleries'
            )
            return
        if kind not in ENTRY_CONTAINERS:
            self.doc.evidence(
                pages.page,
                unknown=node.get('page') is not None and pages.page is None,
                fallback=pages.fallback,
            )
        if kind in ENTRY_CONTAINERS:
            allowed = ENTRY_METADATA | {'entries', 'prerequisite', 'count', 'cost', 'consumes'}
            self._fields(node, allowed)
            name = node.get('name')
            prefix = ''
            transparent = source and self.engine.navigation_group(node)
            if source:
                owner = next(
                    (
                        n.get('name')
                        for n in reversed(self.engine.domain.source[source]['ancestors'])
                        if n.get('name')
                    ),
                    None,
                )
                if owner == name:
                    skip_name = name
            if name and name != skip_name and not transparent:
                inline_title = kind in ('inline', 'inlineBlock') or (
                    kind != 'section' and entry_depth >= INLINE_ENTRY_DEPTH
                )
                if structural and inline_title:
                    title = self.inline(name, plain=True).strip()
                    require(bool(title), 'HEADING', 'Empty inline title', **self.engine.context())
                    punctuation = '' if title.endswith(('.', ':', '?', '!')) else '.'
                    prefix = '***' + self.inline(title) + punctuation + '*** '
                    self.doc.evidence(
                        pages.page, unknown=pages.page is None, fallback=pages.fallback
                    )
                else:
                    level = self.label(
                        name,
                        level,
                        structural=structural,
                        page=pages.page,
                        fallback=pages.fallback,
                        partial=pages.page is None,
                    )
            elif not transparent and (pages.page is not None or node.get('page') is not None):
                self.doc.evidence(pages.page, unknown=pages.page is None, fallback=pages.fallback)
            if prefix and (
                source in self.engine.domain.root_at
                or node.get('prerequisite')
                or kind == 'options'
                and node.get('count') is not None
                or node.get('cost')
                or node.get('consumes')
            ):
                self.doc.add(prefix.rstrip())
                prefix = ''
            if source:
                self.engine.source_levels[source] = level
                self.engine.before_source(source, level, structural=structural)
            if node.get('prerequisite'):
                self.doc.add(
                    '**Prerequisite:** ' + self.engine.values.prerequisite(node['prerequisite'])
                )
            if kind == 'options' and node.get('count') is not None:
                self.doc.add(f'Choose {node["count"]} of the following options:')
            for field in ('cost', 'consumes'):
                if node.get(field):
                    self.doc.add(
                        '**' + field.title() + ':** ' + self.engine.values.structure(node[field])
                    )
            # Entry nesting includes anonymous containers; a real section opens
            # a fresh context independently of its absolute Markdown level.
            entry_depth = 0 if kind == 'section' else entry_depth + 1
            child(node.get('entries', []), 'entries', depth=level, prefix=prefix)
        elif kind == 'wrapper':
            self._fields(node, ENTRY_METADATA | {'wrapped'})
            if node.get('data', {}).get('item__mergedEntryTag'):
                wrapped = node['wrapped']
                if not isinstance(wrapped, dict) or wrapped.get('entries') or wrapped.get('entry'):
                    self.render(wrapped, level, structural=False)
            else:
                child(node['wrapped'], 'wrapped')
        elif kind in ('inset', 'insetReadaloud', 'quote'):
            self._fields(node, ENTRY_METADATA | {'entries', 'by', 'from', 'skipMarks'})
            pieces = []
            if node.get('name'):
                pieces.append('**' + self.inline(node['name']) + '**')
            pieces.append(self.compact(node.get('entries', []), boxed=True))
            if node.get('by'):
                attribution = '— ' + self.inline(node['by'])
                if node.get('from'):
                    attribution += ', *' + self.inline(node['from']) + '*'
                pieces.append(attribution)
            elif node.get('from'):
                pieces.append('— ' + self.inline(node['from']))
            text = '\n\n'.join(filter(None, pieces))
            self.doc.add(text if boxed else quote(text))
        elif kind == 'list':
            self._fields(node, ENTRY_METADATA | {'items', 'start'})
            if node.get('name'):
                self.doc.add('**' + self.inline(node['name']) + '**')
            ordered = 'decimal' in node.get('style', '')
            pieces = []
            for i, item in enumerate(node.get('items', []), node.get('start', 1)):
                text = self.compact(item, boxed=boxed)
                if not text:
                    continue
                marker = f'{i}. ' if ordered else '- '
                lines = text.split('\n')
                pieces.append(
                    marker
                    + lines[0]
                    + ''.join(
                        '\n' + ' ' * len(marker) + line if line else '\n' for line in lines[1:]
                    )
                )
            self.doc.add('\n'.join(pieces))
        elif kind in ('item', 'itemSpell', 'itemSub'):
            self._fields(node, ENTRY_METADATA | {'entry', 'entries'})
            label = node.get('name', '').rstrip(': .')
            text = self.compact(node.get('entry', node.get('entries', [])), boxed=boxed)
            self.doc.add(('**' + self.inline(label) + ':** ' if label else '') + text)
        elif kind == 'table':
            self.table(node)
        elif kind == 'tableGroup':
            self._fields(node, ENTRY_METADATA | {'tables', 'caption'})
            if node.get('name') or node.get('caption'):
                self.doc.add('**' + self.inline(node.get('name') or node['caption']) + '**')
            child(node.get('tables', []), 'tables')
        elif kind in ('abilityGeneric', 'abilityDc', 'abilityAttackMod'):
            self._fields(node, ENTRY_METADATA | {'entry', 'attributes', 'text'})
            if kind == 'abilityGeneric':
                text = self.inline(node.get('entry', node.get('text', '')))
            else:
                attributes = ' or '.join(ABILITIES.get(a, a.title()) for a in node['attributes'])
                text = (
                    (
                        '8 + your Proficiency Bonus + your '
                        if kind == 'abilityDc'
                        else 'your Proficiency Bonus + your '
                    )
                    + attributes
                    + ' modifier'
                )
            self.doc.add(
                ('**' + self.inline(node['name']) + ':** ' if node.get('name') else '') + text
            )
        elif kind in ('bonus', 'bonusSpeed', 'dice'):
            self.doc.add(self.cell(node))
        elif kind == 'statblockInline':
            require(
                'statblockData' in node,
                'UNRESOLVED_STATBLOCK',
                node.get('name'),
                **self.engine.context(),
            )
            self.engine.native(
                node['statblockData'], level, prop=node.get('statblockType'), structural=structural
            )
        else:
            raise ExportError('UNKNOWN_ENTRY_TYPE', kind, **self.engine.context())

    def _fields(self, node, allowed):
        unknown = set(node) - allowed
        require(
            not unknown,
            'UNKNOWN_ENTRY_FIELD',
            ', '.join(sorted(unknown)),
            entry_type=node.get('type'),
            **self.engine.context(),
        )

    def cell(self, value, *, nested=False):
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = self.inline(value)
        elif isinstance(value, dict):
            kind = value.get('type')
            if kind in ('cell', 'cellHeader'):
                if 'entry' in value:
                    text = self.cell(value['entry'], nested=True)
                elif 'roll' in value:
                    roll = value['roll']
                    if 'exact' in roll:
                        text = str(roll['exact'])
                    else:
                        lower, upper = roll['min'], roll['max']
                        if roll.get('pad'):
                            text = f'{lower:02d}–{upper:02d}'
                        else:
                            text = str(lower) if lower == upper else f'{lower}–{upper}'
                else:
                    raise ExportError(
                        'EMPTY_CELL', 'Cell has neither entry nor roll', **self.engine.context()
                    )
            elif kind == 'bonus':
                text = f'{value["value"]:+d}'
            elif kind == 'bonusSpeed':
                text = f'{value["value"]:+d} ft.'
            elif kind == 'dice':
                text = self.engine.values.structure(value)
            else:
                text = self.compact(value)
        elif isinstance(value, list):
            text = '; '.join(self.cell(item, nested=True) for item in value)
        else:
            raise ExportError('CELL_VALUE', type(value).__name__, **self.engine.context())
        return text if nested else text.replace('|', '\\|').replace('\n', '<br>')

    def _expand_cells(self, cells):
        expanded = []
        for cell in cells:
            expanded.append(self.cell(cell))
            if isinstance(cell, dict) and cell.get('width', 1) > 1:
                expanded.extend([''] * (cell['width'] - 1))
        return expanded

    def table(self, node):
        self._fields(
            node,
            ENTRY_METADATA
            | {
                'caption',
                'colLabels',
                'colLabelRows',
                'rows',
                'footnotes',
                'intro',
                'outro',
                'name',
                'isStriped',
                'isRollable',
                'rollMode',
                'isNameGenerator',
            },
        )
        self.engine.diagnostics.count('tables')
        if node.get('caption'):
            self.doc.add('**' + self.inline(node['caption']) + '**')
        if node.get('intro'):
            self.render(node['intro'], structural=False)
        labels = node.get('colLabels')
        if labels is None and node.get('colLabelRows'):
            labels = node['colLabelRows'][-1]
            for row in node['colLabelRows'][:-1]:
                groups = [
                    self.cell(c)
                    + (f' ({c.get("width", 1)} columns)' if isinstance(c, dict) else '')
                    for c in row
                ]
                self.doc.add('Column groups: ' + '; '.join(groups) + '.')
            self.engine.diagnostics.note(
                'GROUPED_TABLE_HEADER', caption=node.get('caption'), heading_path=self.doc.path
            )
        rows = []
        for row in node.get('rows', []):
            row = row['row'] if isinstance(row, dict) and row.get('type') == 'row' else row
            require(
                isinstance(row, list), 'TABLE_ROW', 'Expected row array', **self.engine.context()
            )
            rows.append(self._expand_cells(row))
        width = max([len(labels or []), *(len(row) for row in rows)], default=0)
        require(width > 0, 'EMPTY_TABLE', 'Table has no columns', **self.engine.context())
        labels = self._expand_cells(labels or []) or [''] * width
        width = max(width, len(labels))
        labels += [''] * (width - len(labels))

        def pipe(row):
            return '| ' + ' | '.join(row + [''] * (width - len(row))) + ' |'

        self.doc.add('\n'.join((pipe(labels), pipe(['---'] * width), *(pipe(row) for row in rows))))
        for field in ('footnotes', 'outro'):
            if node.get(field):
                self.render(node[field], structural=False)
