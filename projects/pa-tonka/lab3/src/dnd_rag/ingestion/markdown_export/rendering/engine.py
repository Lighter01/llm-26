"""Compose chapters and canonical domain components at their source positions."""

import copy
import re
from contextlib import contextmanager

from ..common.model import Diagnostics, RenderedBook, require
from .document import Document
from .domain import FEATURE_PROPS, Domain
from .entries import Entries
from .inline import InlineRenderer
from .pages import PageIndex, Pages
from .payloads import Payloads
from .representation import (
    deck_roll_projection,
    named_entries_represented,
    numbered_table_represented,
    represented,
)
from .selection import select_content
from .values import Values


class Engine:
    inline_props = FEATURE_PROPS

    def __init__(self, book):
        self.book = book
        self.diagnostics = Diagnostics(book['book']['id'])
        self.domain = Domain(book, self.diagnostics)
        self.pages = PageIndex(self.domain)
        self.page_context = Pages(source=self.domain.id.casefold())
        self.source_context = None
        self.context_path = []
        self.entity_stack = []
        self.inline = InlineRenderer(self.context)
        self.doc = Document(
            self.domain.id, book['book']['title'], book['upstream']['checkout_sha'], self.inline
        )
        self.entries = Entries(self)
        self.values = Values(self)
        self.payloads = Payloads(self)
        self.represented = set()
        self.attached_blocks = set()
        self.source_levels = {}
        self.deferred_legendary = []
        self.deferred_group_children = []

    def context(self):
        return {
            'book': self.book['book']['id'],
            'heading_path': (self.doc.path or self.context_path) if hasattr(self, 'doc') else [],
            'source_position': self.source_context,
            'entity': self.entity_stack[-1]['entity_id'] if self.entity_stack else None,
        }

    def fork(self, document):
        other = copy.copy(self)
        other.doc = document
        other.context_path = self.doc.path or self.context_path
        other.entity_stack = list(self.entity_stack)
        other.inline = InlineRenderer(other.context)
        other.entries, other.values, other.payloads = Entries(other), Values(other), Payloads(other)
        return other

    @contextmanager
    def page_scope(self, pages):
        previous = self.page_context
        self.page_context = pages
        try:
            yield
        finally:
            self.page_context = previous

    def navigation_group(self, node):
        # A common native navigation form; validate shape and letter against the children.
        # Book/chapter names and positions are deliberately not part of this rule.
        match = re.fullmatch(r'.+ \(([A-Z])\)', node.get('name', ''))
        entries = node.get('entries', [])
        return bool(
            match
            and entries
            and all(
                isinstance(e, dict)
                and e.get('type') == 'section'
                and e.get('name', '')[:1].upper() == match[1]
                for e in entries
            )
        )

    def wrapper(self, wrapper, level, *, structural=True, suppress_title=False, data_override=None):
        occurrence = wrapper['occurrence_id']
        require(
            occurrence not in self.domain.rendered_occurrences,
            'DOUBLE_SOURCE_TRAVERSAL',
            occurrence,
            **self.context(),
        )
        self.domain.rendered_occurrences.add(occurrence)
        self.diagnostics.count('source_insertions')
        entity = self.domain.entities[wrapper['entity_id']]
        source = self.domain.source_objects.get(id(wrapper))
        if source:
            ancestors = self.domain.source[source]['ancestors']
            owner = next((n.get('name') for n in reversed(ancestors) if n.get('name')), None)
            suppress_title |= owner == wrapper['data'].get('name')
        self.native(
            data_override if data_override is not None else wrapper['data'],
            level,
            prop=entity['prop'],
            entity=entity,
            structural=structural,
            suppress_title=suppress_title,
            original=True,
            source_wrapper=wrapper,
        )
        if source:
            self.source_levels[source] = level if suppress_title else level + 1
            self.after_source(source, level, structural=structural)

    def native(
        self,
        data,
        level,
        *,
        prop=None,
        entity=None,
        structural=True,
        suppress_title=False,
        original=False,
        source_wrapper=None,
    ):
        prop = prop or data.get('__prop')
        require(bool(prop), 'MISSING_PAYLOAD_TYPE', data.get('name'), **self.context())
        if entity is None:
            entity = self.domain.inline_entity(data)
            if (
                entity
                and entity['representation'] == 'domain_component'
                and prop in self.inline_props
            ):
                data = self.payloads.complete_inline_rule(data, self.domain.payload(entity))
        if (
            prop == 'card'
            and entity is not None
            and not original
            and self.card_represented(entity, data)
        ):
            return
        selection = select_content(self, entity) if entity and not original else None
        if selection:
            self.domain.record(entity, selection.decision, **selection.evidence)
            if selection.data is None:
                self.represented.add(entity['entity_id'])
                self.entity_stack.append(entity)
                self.extra_children(entity, level, structural=structural)
                self.entity_stack.pop()
                return
            data = selection.data
            self.entries.label(data['name'], level, structural=False)
            suppress_title = True
        if entity:
            self.domain.record(
                entity,
                'rendered_in_parent' if self.entity_stack and not original else 'rendered',
                parent=self.entity_stack[-1]['entity_id'] if self.entity_stack else None,
                reason='typed native payload at its canonical parent/anchor',
            )
            self.entity_stack.append(entity)
        pages = (
            self.pages.entity(entity, data, self.page_context, wrapper=source_wrapper)
            if entity
            else self.pages.node(data, self.page_context)
        )
        with self.page_scope(pages):
            name = data.get('name') or data.get('abbreviation')
            if name and prop in ('classFeature', 'subclassFeature') and data.get('level'):
                name = f'Level {data["level"]}: {name}'
            if name and not suppress_title:
                level = self.entries.label(
                    name,
                    level,
                    structural=structural,
                    page=pages.page,
                    fallback=pages.fallback,
                    partial=pages.page is None,
                )
            else:
                self.doc.evidence(pages.page, unknown=pages.page is None, fallback=pages.fallback)
            if prop != 'legendaryGroup' and not prop.endswith('Fluff'):
                self.fluffs(entity, level, structural=structural)
            self.payloads.render(data, prop, level, structural=structural, partial=bool(selection))
            if entity:
                self.represented.add(entity['entity_id'])
                if prop.endswith('Fluff'):
                    self.register_shared_parents(entity)
                self.extra_children(entity, level, structural=structural)
                self.entity_stack.pop()

    def fluffs(self, entity, level, *, structural):
        if entity is None:
            return
        for fluff in self.domain.linked(entity, 'companion_fluff'):
            if fluff['representation'] == 'book_insertion':
                continue  # Its original source occurrence is retained by the chapter walk.
            self.fluff(fluff, level, structural=structural)

    def fluff(self, entity, level, *, structural):
        data = self.domain.payload(entity)
        self.payloads.fields(data, {'entries', 'images'})
        if not data.get('entries'):
            require(
                set(data)
                <= {
                    'name',
                    'source',
                    'images',
                    '__prop',
                    '_isCopy',
                    'className',
                    'classSource',
                    'shortName',
                },
                'FLUFF_FIELDS',
                'Image-only fluff has unexpected content',
                **self.context(),
            )
            self.domain.record(entity, 'metadata_only', reason='image-only companion fluff')
            self.represented.add(entity['entity_id'])
            return
        for shared in entity.get('shared_content', []):
            if shared['path'].startswith('/images/'):
                continue
            parent = self.domain.entities[shared['parent_entity_id']]
            if (
                parent['representation'] == 'domain_component'
                and parent['entity_id'] not in self.represented
            ):
                self.fluff(parent, level, structural=structural)
        data = self.domain.prune_shared(entity, self.represented)
        self.domain.record(
            entity, 'rendered', reason='companion lore; verified shared paths suppressed'
        )
        pages = self.pages.entity(entity, data, self.page_context)
        with self.page_scope(pages):
            self.doc.evidence(pages.page, unknown=pages.page is None, fallback=pages.fallback)
            for entry in data.get('entries', []):
                self.entries.render(entry, level, structural=structural, skip_name=data.get('name'))
            self.represented.add(entity['entity_id'])
            self.extra_children(entity, level, structural=structural)

    def extra_children(self, entity, level, *, structural):
        for child in self.domain.children[entity['entity_id']]:
            if self.domain.done(child):
                continue
            if child['prop'].endswith('Fluff'):
                self.fluff(child, level, structural=structural)
            elif self.deferred_group_children and entity['prop'].endswith('Fluff'):
                self.deferred_group_children[-1].setdefault(child['entity_id'], child)
            elif child['prop'] == 'legendaryGroup' and self.deferred_legendary:
                self.deferred_legendary[-1].setdefault(child['entity_id'], child)
            else:
                self.supplement(child, level, structural=structural)

    def register_shared_parents(self, entity):
        if entity.get('shared_content'):
            self.domain.prune_shared(
                entity, self.represented
            )  # Verify even original fluff insertions.
        parents = {}
        for shared in entity.get('shared_content', []):
            parents.setdefault(shared['parent_entity_id'], set()).add(shared['parent_path'])
        for key, covered in parents.items():
            parent = self.domain.entities[key]
            paths = {
                '/entries/' + str(i)
                for i, _ in enumerate(self.domain.payload(parent).get('entries', []))
            }
            if paths <= covered and parent['representation'] == 'domain_component':
                self.payloads.fields(self.domain.payload(parent), {'entries', 'images'})
                self.domain.record(
                    parent,
                    'already_represented',
                    reason='all parent lore blocks occur at verified shared paths',
                    child=entity['entity_id'],
                )
                self.represented.add(key)

    def local_source(self, entity):
        anchor = entity['canonical_placement']['anchor']
        info = self.domain.source[(anchor['chapter_index'], anchor['origin']['json_pointer'])]
        node = info['node']
        if not isinstance(node, dict):
            for ancestor in reversed(info['ancestors']):
                if ancestor.get('type') in ('table', 'entries', 'section'):
                    return ancestor
        return node

    def canonical_scopes(self, entity):
        key = entity['canonical_placement']['parent_entity_id']
        while key is not None:
            parent = self.domain.entities[key]
            yield self.domain.payload(parent)
            key = parent['canonical_placement']['parent_entity_id']

    def entry_represented(self, entry, scope):
        return represented(entry, scope, self.inline)

    def ancestor_represents(self, entry):
        return any(
            self.entry_represented(entry, self.domain.payload(entity))
            for entity in reversed(self.entity_stack[:-1])
        )

    def card_represented(self, entity, data):
        self.payloads.fields(data, {'entries', 'face', 'set'})
        for scope in self.canonical_scopes(entity):
            if named_entries_represented(data['name'], data.get('entries', []), scope, self.inline):
                self.domain.record(
                    entity,
                    'already_represented',
                    reason='card title and complete ordered rules occur together in the declared containing item',
                )
                self.represented.add(entity['entity_id'])
                return True
        return False

    def deck_represented(self, entity):
        data = self.domain.payload(entity)
        self.payloads.fields(data, {'entries', 'cards', 'back', 'hasCardArt'})
        required = list(data.get('entries', []))
        for card in data['cards']:
            require(isinstance(card, dict), 'UNRESOLVED_CARD', str(card), **self.context())
            self.payloads.fields(card, {'entries', 'face', 'set'})
        for scope in self.canonical_scopes(entity):
            if (
                (required or data['cards'])
                and all(
                    self.entry_represented(entry, scope)
                    or deck_roll_projection(entry, scope, self.inline)
                    for entry in required
                )
                and all(
                    named_entries_represented(
                        card['name'], card.get('entries', []), scope, self.inline
                    )
                    for card in data['cards']
                )
            ):
                self.domain.record(
                    entity,
                    'already_represented',
                    reason='complete deck/card content and roll-column projection occur in containing item',
                )
                return True
        return False

    def represented_definition(self, entity):
        if entity['prop'] not in ('itemProperty', 'itemMastery', 'itemType'):
            return False
        data = self.domain.payload(entity)
        expected = data.get('entries', [])
        allowed = {
            'name',
            'source',
            'page',
            'entries',
            'abbreviation',
            'template',
            '__prop',
            'basicRules2024',
            'srd52',
            '_isCopy',
        }
        require(
            set(data) <= allowed, 'DEFINITION_FIELDS', 'Unknown definition fields', **self.context()
        )
        if not expected:
            self.domain.record(
                entity, 'metadata_only', reason='category label without additional rules'
            )
            return True
        parent_id = entity['canonical_placement']['parent_entity_id']
        local = (
            self.domain.payload(self.domain.entities[parent_id])
            if parent_id
            else self.local_source(entity)
        )
        if self.entry_represented(expected, local):
            self.domain.record(
                entity,
                'already_represented',
                reason='complete ordered definition entries occur in declared parent/anchor',
                parent=parent_id,
            )
            return True
        return False

    def loot_projection(self, entity):
        if entity['prop'] not in ('gems', 'artObjects', 'magicItems'):
            return False
        data = self.domain.payload(entity)
        local = self.local_source(entity)
        self.payloads.fields(data, {'table', 'coins', 'crMin', 'crMax'})
        if any(key in data for key in ('coins', 'crMin', 'crMax')):
            return False
        # The named value category and every roll/result association must agree.
        if entity['prop'] in ('gems', 'artObjects') and all(
            isinstance(v, str) for v in data['table']
        ):
            if numbered_table_represented(data['table'], local, self.inline, data['name']):
                self.domain.record(
                    entity,
                    'already_represented',
                    reason='value category and complete numbered treasure rows match the source table',
                )
                return True
        return False

    def supplement(self, entity, level, *, structural):
        if self.domain.done(entity):
            return
        key = entity['entity_id']
        require(key not in self.domain.rendering, 'RENDER_CYCLE', key, **self.context())
        self.domain.rendering.add(key)
        relation = entity['canonical_placement']['relation']
        parent_id = entity['canonical_placement']['parent_entity_id']
        if entity['prop'] == 'itemEntry':
            self.payloads.fields(self.domain.payload(entity), {'entriesTemplate'})
            require(
                relation == 'structural_string_reference' and parent_id is not None,
                'UNPLACED_TEMPLATE',
                key,
                **self.context(),
            )
            parent = self.domain.payload(self.domain.entities[parent_id])
            require(
                parent.get('_fullEntries') or parent.get('entries'),
                'EMPTY_TEMPLATE_PARENT',
                key,
                **self.context(),
            )
            self.domain.record(
                entity,
                'template_expanded',
                parent=parent_id,
                reason='resolved native item entries contain the template expansion',
            )
        elif relation in ('generated_item_base_item', 'generated_item_template'):
            parent = self.domain.entities[parent_id]
            derivation = (
                parent.get('derivation')
                if parent['representation'] == 'domain_component'
                else self.domain.wrappers[parent['occurrence_id']]['derivation']
            )
            field = 'base_item' if relation.endswith('base_item') else 'template'
            require(
                derivation is not None and derivation[field]['target']['entity_id'] == key,
                'DERIVATION_COMPONENT',
                key,
                **self.context(),
            )
            self.payloads.item_fields(self.domain.payload(entity))
            self.domain.record(
                entity,
                'native_derivation',
                parent=parent_id,
                reason='base/template mechanics are materialized in the concrete item',
            )
        elif self.represented_definition(entity) or self.loot_projection(entity):
            pass
        elif entity['prop'] == 'deck' and self.deck_represented(entity):
            pass
        elif entity['prop'] == 'card' and self.card_represented(
            entity, self.domain.payload(entity)
        ):
            pass
        elif entity['prop'].endswith('Fluff'):
            self.fluff(entity, level, structural=structural)
        elif entity['prop'] == 'legendaryGroup':
            self.domain.record(
                entity, 'rendered', reason='lair/regional mechanics at canonical group'
            )
            data = self.domain.payload(entity)
            with self.page_scope(self.pages.entity(entity, data, self.page_context)):
                self.payloads.render(data, 'legendaryGroup', level, structural=structural)
        else:
            data = self.domain.payload(entity)
            current = self.doc.path[-1] if self.doc.path else None
            suppress = current == data.get('name')
            if parent_id and relation in (
                'item_companion_representation',
                'summoned_by_spell',
                'summoned_by_class',
            ):
                suppress |= self.domain.payload(self.domain.entities[parent_id]).get(
                    'name'
                ) == data.get('name')
            self.native(
                data,
                level,
                prop=entity['prop'],
                entity=entity,
                structural=structural,
                suppress_title=suppress,
            )
        self.represented.add(key)
        self.extra_children(entity, level, structural=structural)
        self.domain.rendering.remove(key)

    def after_source(self, source, level, *, structural):
        if source in self.attached_blocks or source not in self.domain.root_at:
            return
        self.attached_blocks.add(source)
        level = self.source_levels.get(source, level)
        for entity in self.domain.root_at[source]:
            self.supplement(entity, level, structural=structural)

    def before_source(self, source, level, *, structural):
        if source in self.attached_blocks or source not in self.domain.root_at:
            return
        node = self.domain.source[source]['node']
        if not isinstance(node, dict) or not node.get('name'):
            return
        integrated = []
        for entity in self.domain.root_at[source]:
            if entity['prop'] == 'item' and node.get('entries'):
                # Let the book prose precede any still-missing item content.
                continue
            if (
                self.domain.payload(entity).get('name') == node['name']
                or entity['canonical_placement']['relation'] == 'documented_label_alias'
            ):
                # The real named source section is already the logical entity heading.
                self.native(
                    self.domain.payload(entity),
                    level,
                    entity=entity,
                    prop=entity['prop'],
                    structural=structural,
                    suppress_title=True,
                )
                integrated.append(entity)
        if len(integrated) == len(self.domain.root_at[source]):
            self.attached_blocks.add(source)

    def monster_group(self, node, level, source):
        if node.get('type') not in ('section', 'entries') or not node.get('name'):
            return False
        children = node.get('entries', [])
        wrappers = [
            n for n in children if isinstance(n, dict) and n.get('kind') == 'embedded_entity'
        ]
        monsters = [n for n in wrappers if n['lookup']['prop'] == 'monster']
        fluffs = [n for n in wrappers if n['lookup']['prop'] == 'monsterFluff']
        if (
            not monsters
            or len(fluffs) != 1
            or any(
                not isinstance(n, dict)
                or n.get('kind') != 'embedded_entity'
                and n.get('type') != 'image'
                for n in children
            )
        ):
            return False
        pages = self.page_context
        group_level = self.entries.label(
            node['name'],
            level,
            page=pages.page,
            fallback=pages.fallback,
            partial=pages.page is None,
        )
        self.source_levels[source] = group_level
        self.before_source(source, group_level, structural=True)
        deferred, payload = [], fluffs[0]['data']
        if len(monsters) > 1:
            roots = []
            for root in payload.get('entries', []):
                if isinstance(root, dict) and root.get('name') == payload['name']:
                    prose = []
                    for entry in root.get('entries', []):
                        if (
                            isinstance(entry, dict)
                            and entry.get('type') in ('entries', 'section')
                            and entry.get('name')
                        ):
                            deferred.append(entry)
                        else:
                            prose.append(entry)
                    roots.append({**root, 'entries': prose})
                else:
                    roots.append(root)
            payload = {**payload, 'entries': roots}
        additions = {}
        self.deferred_group_children.append(additions)
        self.wrapper(fluffs[0], group_level, suppress_title=True, data_override=payload)
        effects = {}
        self.deferred_legendary.append(effects)
        for wrapper in monsters:
            self.wrapper(
                wrapper, group_level, suppress_title=wrapper['data'].get('name') == node['name']
            )
        # Other typed insertions remain source ordered if a future group contains them.
        for wrapper in wrappers:
            if wrapper not in monsters and wrapper not in fluffs:
                self.wrapper(wrapper, group_level)
        self.deferred_legendary.pop()
        self.deferred_group_children.pop()
        for child in children:
            if child.get('type') == 'image':
                self.diagnostics.count('omitted_images')
        for entity in additions.values():
            self.supplement(entity, group_level, structural=True)
        for entry in deferred:
            self.entries.render(entry, group_level)
        for entity in effects.values():
            self.supplement(entity, group_level + (1 if deferred else 0), structural=True)
        return True

    def render(self):
        for chapter in self.book['chapters']:
            self.source_context = (chapter['chapter_index'], chapter['origin']['json_pointer'])
            pages = self.pages.sources[self.source_context]
            self.doc.heading(
                chapter['title'],
                1,
                page=pages.page,
                fallback=pages.fallback,
            )
            self.entries.render(
                chapter['content'],
                2,
                source=self.source_context,
                skip_name=chapter['content'].get('name'),
            )
        self.domain.audit()
        markdown, body, source_map = self.doc.finish()
        require(
            not any(
                token in body
                for token in (
                    '{@',
                    '{#',
                    '[object Object]',
                    'undefined',
                    '![',
                    'summonSpellLevel',
                    '{{',
                )
            ),
            'OUTPUT_ARTIFACT',
            'Active tags/templates or a renderer artifact remain',
            book=self.domain.id,
        )
        self.diagnostics.counts['headings'] = len(source_map)
        self.diagnostics.counts['chapters'] = len(self.book['chapters'])
        return RenderedBook(self.domain.id, markdown, body, source_map, self.diagnostics)
