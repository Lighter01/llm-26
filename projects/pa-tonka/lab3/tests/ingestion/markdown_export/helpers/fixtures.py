"""Small synthetic resolved containers and explicit manifest integrity updates."""

import hashlib
import json


def origin(book_id='XPHB', page=10, pointer='/source/0', attribution='explicit'):
    return {
        'source': book_id,
        'printed_page': page,
        'page_attribution': attribution,
        'json_pointer': pointer,
    }


def empty_book(book_id='XPHB', entries=None):
    return {
        'schema_version': '1.0.0',
        'artifact_kind': 'resolved_book',
        'scope': dict.fromkeys(
            (
                'all_source_chapters',
                'embedded_references_resolved',
                'domain_enrichment',
                'book_complete',
            ),
            True,
        ),
        'book': {'id': book_id, 'title': 'Fixture: "Book" — 🐉'},
        'upstream': {'checkout_sha': '1234567890abcdef' * 2 + '12345678'},
        'chapters': [
            {
                'chapter_index': 0,
                'title': 'First Part',
                'origin': origin(book_id),
                'content': {'type': 'section', 'name': 'First Part', 'entries': entries or []},
            }
        ],
        'domain': {'entities': [], 'relationships': []},
    }


def add_entity(
    book,
    data,
    prop,
    *,
    parent=None,
    insertion=False,
    anchor='/source/0',
    relation='structural_reference',
    page=12,
):
    book_id = book['book']['id']
    key = f'entity:{len(book["domain"]["entities"])}'
    placement = {
        'parent_entity_id': parent,
        'relation': relation,
        'anchor': {'book_id': book_id, 'chapter_index': 0, 'origin': origin(book_id, 10, anchor)},
    }
    entity = {
        'entity_id': key,
        'prop': prop,
        'canonical_placement': placement,
        'representation': 'book_insertion' if insertion else 'domain_component',
        'data_origin': origin(data.get('source', book_id), page),
    }
    if insertion:
        occurrence = 'occurrence:' + key
        entity['occurrence_id'] = occurrence
        book['chapters'][0]['content']['entries'].append(
            {
                'kind': 'embedded_entity',
                'data': data,
                'entity_id': key,
                'occurrence_id': occurrence,
                'lookup': {'prop': prop},
            }
        )
    else:
        entity['data'] = data
    book['domain']['entities'].append(entity)
    if parent is not None:
        book['domain']['relationships'].append(
            {'from_entity_id': parent, 'to_entity_id': key, 'relation': relation}
        )
    return entity


def write_build(path, *, order=('XPHB', 'XDMG', 'XMM')):
    path.mkdir(exist_ok=True)
    manifest = {
        'manifest_version': '2.0.0',
        'schema': {'version': '1.0.0'},
        'validation': {'status': 'PASS'},
        'books': {},
    }
    for book_id in order:
        book = empty_book(book_id, ['Text for ' + book_id])
        manifest['upstream'] = book['upstream']
        raw = (json.dumps(book, ensure_ascii=False) + '\n').encode('utf-8')
        name = book_id.lower() + '.resolved.json'
        (path / name).write_bytes(raw)
        manifest['books'][book_id] = {
            'path': name,
            'bytes': len(raw),
            'file_sha256': hashlib.sha256(raw).hexdigest(),
        }
    (path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


def change_book(build, callback, book_id='XPHB'):
    """Alter a synthetic/copied input and refresh its manifest integrity fields."""
    manifest_path = build / 'manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    metadata = manifest['books'][book_id]
    path = build / metadata['path']
    book = json.loads(path.read_bytes())
    callback(book)
    raw = json.dumps(book).encode('utf-8')
    path.write_bytes(raw)
    metadata.update(bytes=len(raw), file_sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
