import hashlib
import json

import pytest

from dnd_rag.ingestion.markdown_export import ExportError, read_build, render_build
from helpers import file_bytes, write_build


def test_manifest_order_four_artifacts_and_input_immutability(tmp_path):
    order = ('XMM', 'XPHB', 'XDMG')
    write_build(tmp_path, order=order)
    before = file_bytes(tmp_path)
    corpus = render_build(tmp_path)
    assert [book.book_id for book in corpus.books] == list(order)
    assert set(corpus.files) == {'xphb.md', 'xdmg.md', 'xmm.md', 'source_map.jsonl'}
    records = [
        json.loads(line)
        for line in corpus.files['source_map.jsonl'].decode('utf-8').split('\n')[:-1]
    ]
    assert [r['book_id'] for r in records] == list(order)
    assert all(raw.endswith(b'\n') and b'\r' not in raw for raw in corpus.files.values())
    assert corpus.files == render_build(tmp_path).files
    assert file_bytes(tmp_path) == before


@pytest.mark.parametrize(
    ('mutation', 'code'),
    [
        ('manifest_version', 'UNSUPPORTED_MANIFEST'),
        ('schema', 'UNSUPPORTED_SCHEMA'),
        ('validation', 'FAILED_INPUT_BUILD'),
        ('missing_book', 'BOOK_SET'),
        ('size', 'INPUT_INTEGRITY'),
        ('hash', 'INPUT_INTEGRITY'),
        ('identity', 'INPUT_IDENTITY'),
        ('snapshot', 'MIXED_SNAPSHOT'),
        ('missing_file', 'INVALID_BUILD'),
        ('invalid_json', 'INVALID_BUILD'),
    ],
)
def test_invalid_build_fails_before_rendering(tmp_path, mutation, code):
    manifest = write_build(tmp_path)
    metadata = manifest['books']['XPHB']
    path = tmp_path / metadata['path']
    if mutation == 'manifest_version':
        manifest['manifest_version'] = '3.0.0'
    elif mutation == 'schema':
        manifest['schema']['version'] = '2.0.0'
    elif mutation == 'validation':
        manifest['validation']['status'] = 'FAIL'
    elif mutation == 'missing_book':
        manifest['books'].pop('XMM')
    elif mutation == 'size':
        metadata['bytes'] += 1
    elif mutation == 'hash':
        metadata['file_sha256'] = '0' * 64
    elif mutation == 'missing_file':
        path.unlink()
    else:
        book = json.loads(path.read_bytes())
        if mutation == 'identity':
            book['book']['id'] = 'XMM'
        elif mutation == 'snapshot':
            book['upstream']['checkout_sha'] = 'a' * 40
        raw = b'{' if mutation == 'invalid_json' else json.dumps(book).encode('utf-8')
        path.write_bytes(raw)
        metadata.update(bytes=len(raw), file_sha256=hashlib.sha256(raw).hexdigest())
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ExportError) as error:
        read_build(tmp_path)
    assert error.value.code == code


@pytest.mark.parametrize('symlink', [False, True])
def test_input_path_cannot_escape_build(tmp_path, symlink):
    build = tmp_path / 'build'
    manifest = write_build(build)
    outside = tmp_path / 'outside.json'
    outside.write_bytes((build / 'xphb.resolved.json').read_bytes())
    if symlink:
        (build / 'link.json').symlink_to(outside)
        manifest['books']['XPHB']['path'] = 'link.json'
    else:
        manifest['books']['XPHB']['path'] = '../outside.json'
    (build / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ExportError, match='INPUT_PATH'):
        read_build(build)


def test_build_directory_is_explicit_and_never_discovered(tmp_path):
    write_build(tmp_path / 'valid')
    with pytest.raises(ExportError, match='INVALID_BUILD'):
        read_build(tmp_path)


@pytest.mark.parametrize(
    'damage',
    [
        'duplicate_key',
        'nan',
        'utf8',
        'manifest_array',
        'manifest_symlink',
        'absolute_path',
        'bad_size',
        'bad_digest',
        'bad_sha',
        'missing_sha',
    ],
)
def test_strict_manifest_boundary(tmp_path, damage):
    build = tmp_path / 'build'
    manifest = write_build(build)
    path = build / 'manifest.json'
    if damage == 'duplicate_key':
        path.write_text(
            '{"manifest_version":"2.0.0", "manifest_version":"2.0.0"}', encoding='utf-8'
        )
    elif damage == 'nan':
        path.write_text('{"not_json": NaN}', encoding='utf-8')
    elif damage == 'utf8':
        path.write_bytes(b'\xff')
    elif damage == 'manifest_array':
        path.write_text('[]', encoding='utf-8')
    elif damage == 'manifest_symlink':
        outside = tmp_path / 'manifest.json'
        path.rename(outside)
        path.symlink_to(outside)
    else:
        if damage == 'absolute_path':
            manifest['books']['XPHB']['path'] = str(build / 'xphb.resolved.json')
        elif damage == 'bad_size':
            manifest['books']['XPHB']['bytes'] = True
        elif damage == 'bad_digest':
            manifest['books']['XPHB']['file_sha256'] = 'not a SHA'
        elif damage == 'bad_sha':
            manifest['upstream']['checkout_sha'] = '../escape'
        else:
            manifest.pop('upstream')
        path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ExportError):
        read_build(build)


@pytest.mark.parametrize(
    'raw',
    [
        b'{"book":{},"book":{}}',
        b'{"value": Infinity}',
        b'\xff',
        b'{"value":1e999}',
        b'{"title":"\\ud800"}',
    ],
)
def test_invalid_json_book_cannot_hide_behind_a_matching_hash(tmp_path, raw):
    manifest = write_build(tmp_path)
    path = tmp_path / 'xphb.resolved.json'
    path.write_bytes(raw)
    manifest['books']['XPHB'].update(bytes=len(raw), file_sha256=hashlib.sha256(raw).hexdigest())
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ExportError, match='INVALID_BUILD'):
        read_build(tmp_path)
