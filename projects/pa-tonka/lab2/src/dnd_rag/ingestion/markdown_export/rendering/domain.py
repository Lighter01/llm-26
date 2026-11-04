"""Index the source tree and canonical placements without reloading entities."""

from collections import defaultdict

from ..common.model import at_pointer, pointer_token, require

ITEM_PROPS = frozenset(('item', 'baseitem', 'itemGroup', 'magicvariant'))
FEATURE_PROPS = frozenset(('classFeature', 'subclassFeature', 'optionalfeature', 'feat', 'card'))


def identity(prop, data):
    prop = 'item' if prop in ITEM_PROPS else prop
    keys = (
        'name',
        'source',
        'className',
        'classSource',
        'level',
        'subclassShortName',
        'subclassSource',
        'set',
    )
    return (prop, *(str(data.get(key, '')).casefold() for key in keys))


class Domain:
    def __init__(self, book, diagnostics):
        self.book = book
        self.id = book['book']['id']
        self.diagnostics = diagnostics
        self.entities = {}
        self.wrappers = {}
        self.source = {}
        self.source_objects = {}
        self.children = defaultdict(list)
        self.related = defaultdict(lambda: defaultdict(list))
        self.by_identity = defaultdict(list)
        self.root_at = defaultdict(list)
        self.rendered_occurrences = set()
        self.rendering = set()
        for chapter in book['chapters']:
            root_pointer = chapter['origin']['json_pointer']
            self._source(
                chapter['content'],
                chapter['chapter_index'],
                root_pointer,
                None,
                (),
            )
        for entity in book['domain']['entities']:
            key = entity['entity_id']
            require(key not in self.entities, 'DUPLICATE_ENTITY', key, book=self.id)
            self.entities[key] = entity
        for entity in self.entities.values():
            key = entity['entity_id']
            self.by_identity[identity(entity['prop'], self.payload(entity))].append(entity)
            placement = entity['canonical_placement']
            parent = placement['parent_entity_id']
            anchor = placement['anchor']
            require(anchor['book_id'] == self.id, 'CROSS_BOOK_ANCHOR', key, book=self.id)
            source_key = (anchor['chapter_index'], anchor['origin']['json_pointer'])
            require(
                source_key in self.source,
                'MISSING_ANCHOR',
                'No such source position',
                entity=key,
                anchor=source_key,
            )
            if parent is not None:
                require(parent in self.entities, 'MISSING_PARENT', parent, book=self.id, entity=key)
                self.children[parent].append(entity)
            elif entity['representation'] == 'domain_component':
                block = self.source[source_key]['block']
                self.root_at[block].append(entity)
            if entity['representation'] == 'book_insertion':
                wrapper = self.wrappers.get(entity['occurrence_id'])
                require(
                    wrapper is not None and wrapper['entity_id'] == key,
                    'MISSING_INSERTION',
                    'Canonical insertion has no matching wrapper',
                    entity=key,
                )
        for edge in book['domain']['relationships']:
            if edge['relation'] == 'inheritance_provenance':
                continue
            parent, child = edge['from_entity_id'], edge['to_entity_id']
            require(
                child in self.entities and (parent is None or parent in self.entities),
                'DANGLING_RELATION',
                edge['relation'],
                book=self.id,
            )
            if parent is not None and child not in self.related[parent][edge['relation']]:
                self.related[parent][edge['relation']].append(child)
        for key in self.entities:
            ancestors, current = set(), key
            while current is not None:
                require(current not in ancestors, 'PLACEMENT_CYCLE', current, book=self.id)
                ancestors.add(current)
                current = self.entities[current]['canonical_placement']['parent_entity_id']

    def _source(self, node, chapter, pointer, block, ancestors):
        if isinstance(node, dict) and node.get('type') == 'image':
            self.diagnostics.count('source_images_omitted')
        key = (chapter, pointer)
        # Row/cell anchors are scheduled after their table rather than inside it.
        if isinstance(node, dict) and node.get('type') in (
            'section',
            'entries',
            'table',
            'tableGroup',
            'list',
            'inset',
            'insetReadaloud',
        ):
            if not any(ancestor.get('type') == 'table' for ancestor in ancestors):
                block = key
        if isinstance(node, dict) and node.get('kind') == 'embedded_entity':
            block = key
        self.source[key] = {
            'node': node,
            'block': block or key,
            'ancestors': ancestors,
        }
        if isinstance(node, dict):
            self.source_objects[id(node)] = key
            if node.get('kind') == 'embedded_entity':
                occurrence = node['occurrence_id']
                require(
                    occurrence not in self.wrappers,
                    'DUPLICATE_OCCURRENCE',
                    occurrence,
                    book=self.id,
                )
                self.wrappers[occurrence] = node
                return
            for name, child in node.items():
                self._source(
                    child,
                    chapter,
                    pointer + '/' + pointer_token(name),
                    block,
                    ancestors + (node,),
                )
        elif isinstance(node, list):
            for index, child in enumerate(node):
                self._source(child, chapter, pointer + '/' + str(index), block, ancestors)

    def payload(self, entity):
        if entity['representation'] == 'domain_component':
            return entity['data']
        wrapper = self.wrappers.get(entity['occurrence_id'])
        require(wrapper is not None, 'MISSING_INSERTION', entity['occurrence_id'], book=self.id)
        return wrapper['data']

    def inline_entity(self, data):
        prop = data.get('__prop')
        if not prop:
            return None
        found = self.by_identity.get(identity(prop, data), [])
        require(
            len(found) <= 1, 'AMBIGUOUS_INLINE_ENTITY', data.get('name'), book=self.id, prop=prop
        )
        return found[0] if found else None

    def linked(self, entity, relation):
        return [self.entities[key] for key in self.related[entity['entity_id']].get(relation, [])]

    def done(self, entity):
        return (
            entity['representation'] == 'book_insertion'
            or entity['entity_id'] in self.diagnostics.components
        )

    def record(self, entity, decision, **evidence):
        if entity['representation'] == 'domain_component':
            self.diagnostics.components.setdefault(
                entity['entity_id'], {'prop': entity['prop'], 'decision': decision, **evidence}
            )

    def prune_shared(self, entity, represented):
        excluded = set()
        for item in entity.get('shared_content', []):
            parent = self.entities.get(item['parent_entity_id'])
            require(parent is not None, 'MISSING_SHARED_PARENT', entity['entity_id'], book=self.id)
            require(
                at_pointer(self.payload(entity), item['path'])
                == at_pointer(self.payload(parent), item['parent_path']),
                'SHARED_CONTENT_MISMATCH',
                item['path'],
                book=self.id,
                entity=entity['entity_id'],
            )
            if parent['entity_id'] in represented or item['path'].startswith('/images/'):
                excluded.add(item['path'])

        def prune(node, path=''):
            if isinstance(node, list):
                return [
                    prune(value, path + '/' + str(i))
                    for i, value in enumerate(node)
                    if path + '/' + str(i) not in excluded
                ]
            if isinstance(node, dict):
                return {
                    key: prune(value, path + '/' + pointer_token(key))
                    for key, value in node.items()
                    if path + '/' + pointer_token(key) not in excluded
                }
            return node

        return prune(self.payload(entity))

    def audit(self):
        missing = [
            key
            for key, entity in self.entities.items()
            if entity['representation'] == 'domain_component'
            and key not in self.diagnostics.components
        ]
        require(
            not missing,
            'UNPLACED_COMPONENTS',
            f'{len(missing)} components lack an export decision',
            book=self.id,
            examples=missing[:5],
        )
        require(
            self.rendered_occurrences == set(self.wrappers),
            'OCCURRENCE_COVERAGE',
            'Source insertion was omitted',
            book=self.id,
            missing=sorted(set(self.wrappers) - self.rendered_occurrences)[:5],
        )
