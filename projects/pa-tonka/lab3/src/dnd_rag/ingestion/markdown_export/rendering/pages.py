"""Classify physical book positions before emitting source-map evidence.

Catalog origins are usable only for a same-book definition consistent with its
local placement. Neighboring source landmarks constrain that check; their page
numbers are never used to invent an end page or to clamp original book nodes.
"""

import bisect
import re
from dataclasses import dataclass, replace

from .domain import ITEM_PROPS
from .inline import ENTITY_TAGS
from .representation import VISIBLE_CHILDREN

PAGE_CHILDREN = frozenset(VISIBLE_CHILDREN) | {'tables'}

PAGE_NODES = frozenset(
    (
        'section',
        'entries',
        'options',
        'variant',
        'variantInner',
        'inline',
        'inlineBlock',
        'inset',
        'insetReadaloud',
        'quote',
        'list',
        'item',
        'itemSpell',
        'itemSub',
        'table',
        'tableGroup',
        'abilityGeneric',
        'abilityDc',
        'abilityAttackMod',
    )
)


def page_number(value):
    return value if type(value) is int and value >= 0 else None


def reference_title(node):
    name = node.get('name')
    if not isinstance(name, str):
        return False
    match = re.fullmatch(r'\{@(\w+) [^{}]+\}', name.strip())
    return bool(match and match[1] in ENTITY_TAGS)


@dataclass(frozen=True, slots=True)
class Pages:
    page: int | None = None
    fallback: int | None = None
    limit: int | None = None
    source: str | None = None
    role: str = 'unknown'

    def contains(self, page):
        return (
            page is not None
            and self.fallback is not None
            and page >= self.fallback
            and (self.limit is None or page <= self.limit)
        )


class PageIndex:
    def __init__(self, domain):
        self.domain = domain
        self.book = domain.id.casefold()
        self.sources = {}
        self.peers = {}
        chapters = {
            (c['chapter_index'], c['origin']['json_pointer']): c for c in domain.book['chapters']
        }
        ends, visible, stack, landmarks = {}, {}, [], []
        for index, (key, info) in enumerate(domain.source.items()):
            while stack and (key[0] != stack[-1][0] or not key[1].startswith(stack[-1][1] + '/')):
                ends[stack.pop()] = index
            stack.append(key)
            node = info['node']
            direct_parent = stack[-2] if len(stack) > 1 else None
            visible[key] = key in chapters or (
                direct_parent is not None
                and visible[direct_parent]
                and (
                    isinstance(domain.source[direct_parent]['node'], list)
                    or key[1].rsplit('/', 1)[-1] in PAGE_CHILDREN
                )
            )
            parent_key = next(
                (k for k in reversed(stack[:-1]) if isinstance(domain.source[k]['node'], dict)),
                None,
            )
            parent = self.sources[parent_key] if parent_key is not None else Pages(source=self.book)
            source = (
                str(node.get('source') or parent.source or self.book).casefold()
                if isinstance(node, dict)
                else parent.source
            )
            origin = {}
            if key in chapters:
                origin = chapters[key]['origin']
            elif isinstance(node, dict) and node.get('kind') == 'embedded_entity':
                origin = node.get('placement', {}).get('origin', {})
            page = None
            if (
                origin.get('source', '').casefold() == self.book
                and origin.get('page_attribution') == 'explicit'
            ):
                page = page_number(origin.get('printed_page'))
            elif (
                visible[key]
                and isinstance(node, dict)
                and node.get('type', 'entries') in PAGE_NODES
                and source == self.book
                and not reference_title(node)
            ):
                page = page_number(node.get('page'))
            fallback = page if page is not None else parent.fallback
            if (
                key in chapters
                and fallback is None
                and origin.get('source', '').casefold() == self.book
            ):
                fallback = page_number(origin.get('printed_page'))
            if page is not None:
                role = 'book_position'
            elif isinstance(node, dict) and reference_title(node):
                role = 'reference_target'
            else:
                role = 'section_start' if fallback is not None else 'unknown'
            self.sources[key] = Pages(page, fallback, source=source, role=role)
            if page is not None:
                landmarks.append((index, page))
        for key in stack:
            ends[key] = len(domain.source)
        starts = [position for position, _ in landmarks]
        for key, evidence in self.sources.items():
            first = bisect.bisect_left(starts, ends[key])
            limit = next(
                (
                    landmarks[i][1]
                    for i in range(first, len(landmarks))
                    if evidence.fallback is None or landmarks[i][1] > evidence.fallback
                ),
                None,
            )
            self.sources[key] = replace(evidence, limit=limit)

        # Original typed sibling definitions refine the scope of their native
        # children, e.g. class features. Only already compatible origins qualify.
        groups = {}
        for key, info in domain.source.items():
            wrapper = info['node']
            if not isinstance(wrapper, dict) or wrapper.get('kind') != 'embedded_entity':
                continue
            entity = domain.entities[wrapper['entity_id']]
            evidence = self.entity(entity, wrapper['data'], wrapper=wrapper)
            prop = 'item' if entity['prop'] in ITEM_PROPS else entity['prop']
            group = (key[0], key[1].rsplit('/', 1)[0], prop)
            groups.setdefault(group, []).append((key, evidence))
        for siblings in groups.values():
            for index, (key, evidence) in enumerate(siblings):
                if evidence.page is None:
                    continue
                following = next(
                    (
                        other.page
                        for _, other in siblings[index + 1 :]
                        if other.page is not None and other.page > evidence.page
                    ),
                    None,
                )
                if following is not None:
                    self.peers[key] = following

    def node(self, node, context, source=None):
        key = source or self.domain.source_objects.get(id(node))
        if key is not None:
            return self.sources[key]
        namespace = str(node.get('source') or context.source or self.book).casefold()
        candidate = page_number(node.get('page'))
        page = (
            candidate
            if namespace == self.book and not reference_title(node) and context.contains(candidate)
            else None
        )
        if page is not None:
            role = 'native_entry'
        elif reference_title(node):
            role = 'reference_target'
        else:
            role = 'section_start' if context.fallback is not None else 'unknown'
        return Pages(
            page,
            page if page is not None else context.fallback,
            context.limit,
            namespace,
            role,
        )

    def entity(self, entity, data, context=None, *, wrapper=None):
        if wrapper is not None:
            key = self.domain.source_objects.get(id(wrapper))
        else:
            anchor = entity['canonical_placement']['anchor']
            key = (anchor['chapter_index'], anchor['origin']['json_pointer'])
        base = self.sources[key]
        fallback, limit = base.fallback, base.limit
        if context is not None and wrapper is None:
            starts = [p for p in (fallback, context.fallback) if p is not None]
            limits = [p for p in (limit, context.limit) if p is not None]
            fallback, limit = max(starts, default=None), min(limits, default=None)
        namespace = str(data.get('source') or entity['data_origin']['source']).casefold()
        scope = Pages(fallback=fallback, limit=limit, source=namespace)
        origin = (
            wrapper.get('entity_origin', entity['data_origin'])
            if wrapper
            else entity['data_origin']
        )
        candidate = page_number(origin.get('printed_page'))
        if wrapper is not None and base.page is not None:
            page, role = base.page, 'book_position'
        elif (
            namespace == self.book
            and origin.get('source', '').casefold() == self.book
            and origin.get('page_attribution') == 'explicit'
            and origin.get('lookup_source') != 'ambiguous_physical_candidates'
            and scope.contains(candidate)
        ):
            page, role = candidate, 'local_definition'
        else:
            page, role = None, 'section_start' if fallback is not None else 'unknown'
        if wrapper is not None and key in self.peers:
            limit = min(limit, self.peers[key]) if limit is not None else self.peers[key]
        return Pages(page, page if page is not None else fallback, limit, namespace, role)
