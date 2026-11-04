"""Filesystem failures are injected before/at the directory commit boundary."""

import errno
from pathlib import Path

import pytest

from dnd_rag.ingestion.markdown_export import ExportError, export_build
from dnd_rag.ingestion.markdown_export.publication import store as publish
from helpers import PROJECT, assert_no_temporary_paths, change_book, file_bytes, run_cli, snapshot


@pytest.mark.parametrize('empty_directory', [False, True])
def test_create_four_files_and_force_is_byte_identical(build, tmp_path, empty_directory):
    output = tmp_path / 'output'
    if empty_directory:
        output.mkdir()
    before = file_bytes(build)
    result = export_build(build, output)
    assert result.output_dir == output and result.status == 'created'
    assert file_bytes(output) == result.corpus.files and not result.warnings
    original = snapshot(output)
    with pytest.raises(ExportError, match='OUTPUT_EXISTS'):
        export_build(build, output)
    assert snapshot(output) == original
    forced = export_build(build, output, force=True)
    assert forced.status == 'replaced' and file_bytes(output) == result.corpus.files
    assert file_bytes(build) == before
    assert_no_temporary_paths(output)


def test_force_replaces_partial_or_damaged_exporter_files(build, tmp_path):
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'xphb.md').write_bytes(b'damaged')
    result = export_build(build, output, force=True)
    assert file_bytes(output) == result.corpus.files
    assert_no_temporary_paths(output)


@pytest.mark.parametrize('force', [False, True])
@pytest.mark.parametrize('kind', ['extra', 'symlink', 'directory', 'file', 'target_symlink'])
def test_never_replaces_unowned_files_directories_or_links(build, tmp_path, force, kind):
    output = tmp_path / 'output'
    sentinel = tmp_path / 'sentinel'
    sentinel.write_text('Keep me', encoding='utf-8')
    if kind == 'file':
        output.write_text('Keep directory name file', encoding='utf-8')
    elif kind == 'target_symlink':
        actual = tmp_path / 'actual'
        actual.mkdir()
        output.symlink_to(actual, target_is_directory=True)
    else:
        output.mkdir()
        if kind == 'extra':
            (output / 'notes.txt').write_text('Keep notes', encoding='utf-8')
        elif kind == 'directory':
            (output / 'xphb.md').mkdir()
        else:
            (output / 'xphb.md').symlink_to(sentinel)
    with pytest.raises(ExportError, match='OUTPUT_(CONTENT|PATH)'):
        export_build(build, output, force=force)
    assert sentinel.read_text() == 'Keep me'
    if kind == 'extra':
        assert (output / 'notes.txt').read_text() == 'Keep notes'
    elif kind in ('symlink', 'target_symlink'):
        assert (output / 'xphb.md' if kind == 'symlink' else output).is_symlink()
    elif kind == 'file':
        assert output.read_text() == 'Keep directory name file'
    else:
        assert (output / 'xphb.md').is_dir()
    assert_no_temporary_paths(output)


@pytest.mark.parametrize(
    'where', ['same', 'child', 'parent', 'aliased_child', 'source', 'external']
)
def test_output_cannot_overlap_inputs_or_project_dependencies(build, tmp_path, where):
    if where == 'same':
        output = build
    elif where == 'child':
        output = build / 'markdown'
    elif where == 'parent':
        output = tmp_path
    elif where == 'aliased_child':
        (tmp_path / 'alias').symlink_to(build, target_is_directory=True)
        output = tmp_path / 'alias' / 'markdown'
    else:
        output = PROJECT / (
            'src/dnd_rag/ingestion/book_assembly/never-create'
            if where == 'source'
            else 'external/never-create'
        )
    before = file_bytes(build)
    with pytest.raises(ExportError, match='OUTPUT_OVERLAP'):
        export_build(build, output, force=True)
    assert file_bytes(build) == before
    if where not in ('same', 'parent'):
        assert not output.exists()


@pytest.mark.parametrize(
    ('existing', 'failure'),
    [
        (existing, failure)
        for existing in (False, True)
        for failure in ('write', 'stage_validation', 'commit', 'interrupt')
    ]
    + [(True, 'backup_rename')],
)
def test_failed_export_keeps_previous_corpus_and_removes_temporary_paths(
    build, tmp_path, monkeypatch, existing, failure
):
    output = tmp_path / 'output'
    previous = None
    if existing:
        export_build(build, output)
        previous = file_bytes(output)
        change_book(
            build,
            lambda b: b['chapters'][0]['content']['entries'].append(
                'A new revision with different bytes.'
            ),
        )
    original_replace = publish.os.replace

    def rename(source, destination):
        if (failure == 'backup_rename' and Path(source) == output) or (
            failure in ('commit', 'interrupt') and '.stage-' in Path(source).name
        ):
            if failure == 'interrupt':
                raise KeyboardInterrupt
            raise OSError(errno.EIO, 'injected rename failure')
        original_replace(source, destination)

    if failure == 'write':

        def partial_write(stage, corpus):
            (stage / 'xphb.md').write_bytes(corpus.files['xphb.md'][:20])
            raise OSError(errno.ENOSPC, 'injected full disk')

        monkeypatch.setattr(publish, '_write_stage', partial_write)
    elif failure == 'stage_validation':
        original_write = publish._write_stage

        def corrupt(stage, corpus):
            original_write(stage, corpus)
            (stage / 'xphb.md').write_bytes(b'corruption\n')

        monkeypatch.setattr(publish, '_write_stage', corrupt)
    else:
        monkeypatch.setattr(publish.os, 'replace', rename)
    with pytest.raises(KeyboardInterrupt if failure == 'interrupt' else ExportError):
        export_build(build, output, force=True)
    if existing:
        assert file_bytes(output) == previous
    else:
        assert not output.exists()
    assert_no_temporary_paths(output)


def test_rollback_failure_preserves_original_backup_for_recovery(build, tmp_path, monkeypatch):
    output = tmp_path / 'output'
    export_build(build, output)
    previous = file_bytes(output)
    original = publish.os.replace

    def fail(source, destination):
        if '.stage-' in Path(source).name or '.backup-' in Path(source).name:
            raise OSError(errno.EIO, 'injected failure')
        original(source, destination)

    monkeypatch.setattr(publish.os, 'replace', fail)
    with pytest.raises(ExportError, match='ROLLBACK_FAILED') as error:
        export_build(build, output, force=True)
    backup = Path(error.value.context['backup'])
    assert file_bytes(backup) == previous and not output.exists()
    assert not list(tmp_path.glob('.output.stage-*'))
    assert not (tmp_path / '.output.export.lock').exists()


def test_cleanup_error_reports_retained_backup_after_success(build, tmp_path, monkeypatch):
    output = tmp_path / 'output'
    export_build(build, output)
    original = publish.shutil.rmtree

    def fail(path):
        if '.backup-' in Path(path).name:
            raise OSError(errno.EACCES, 'injected cleanup failure')
        original(path)

    monkeypatch.setattr(publish.shutil, 'rmtree', fail)
    result = export_build(build, output, force=True)
    assert file_bytes(output) == result.corpus.files
    assert len(result.warnings) == 1 and '.backup-' in result.warnings[0]
    assert not (tmp_path / '.output.export.lock').exists()


def test_existing_lock_is_not_removed_or_overridden(build, tmp_path):
    output = tmp_path / 'output'
    lock = tmp_path / '.output.export.lock'
    lock.mkdir()
    with pytest.raises(ExportError, match='OUTPUT_LOCKED'):
        export_build(build, output, force=True)
    assert lock.is_dir() and not output.exists()
    assert not list(tmp_path.glob('.output.stage-*'))


def test_force_regenerates_changed_input_rather_than_reusing_old_output(build, tmp_path):
    output = tmp_path / 'output'
    export_build(build, output)
    previous = file_bytes(output)
    change_book(build, lambda b: b['chapters'][0]['content']['entries'].append('New book prose.'))
    result = export_build(build, output, force=True)
    assert file_bytes(output) == result.corpus.files != previous
    assert b'New book prose.' in (output / 'xphb.md').read_bytes()
    assert_no_temporary_paths(output)


@pytest.mark.parametrize('force', [False, True])
def test_current_working_directory_is_never_replaced(build, tmp_path, force):
    output = tmp_path / 'output'
    if force:
        export_build(build, output)
    else:
        output.mkdir()
    before = snapshot(output)
    identity = output.stat().st_ino
    arguments = ['--input-build', build, '--output-dir', '.']
    if force:
        arguments.append('--force')
    result = run_cli(output, *arguments)
    assert result.returncode == 1 and 'OUTPUT_OVERLAP' in result.stderr
    assert output.stat().st_ino == identity and snapshot(output) == before
    assert_no_temporary_paths(output)
