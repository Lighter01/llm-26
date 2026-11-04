"""Failure paths which need distinct backup and cleanup state."""

import errno
from pathlib import Path

import pytest

from dnd_rag.ingestion.markdown_export import ExportError, export_build, render_build
from dnd_rag.ingestion.markdown_export import __main__ as cli
from dnd_rag.ingestion.markdown_export.publication import store
from helpers import assert_no_temporary_paths, change_book, file_bytes


def test_backup_reservation_failure_does_not_claim_empty_directory_contains_old_corpus(
    build, tmp_path, monkeypatch
):
    output = tmp_path / 'output'
    export_build(build, output)
    previous = file_bytes(output)
    original = Path.rmdir

    def fail_backup(path):
        if '.backup-' in path.name:
            raise OSError(errno.EACCES, 'injected reservation removal failure')
        return original(path)

    monkeypatch.setattr(Path, 'rmdir', fail_backup)
    with pytest.raises(ExportError) as error:
        export_build(build, output, force=True)
    assert error.value.code == 'PUBLICATION_IO'
    assert file_bytes(output) == previous
    assert_no_temporary_paths(output)


def test_interrupt_after_backup_rename_restores_original_corpus(build, tmp_path, monkeypatch):
    output = tmp_path / 'output'
    export_build(build, output)
    previous = file_bytes(output)
    original = store.os.replace

    def interrupt_after_rename(source, destination):
        original(source, destination)
        if Path(source) == output:
            raise KeyboardInterrupt

    monkeypatch.setattr(store.os, 'replace', interrupt_after_rename)
    with pytest.raises(KeyboardInterrupt):
        export_build(build, output, force=True)
    assert file_bytes(output) == previous
    assert_no_temporary_paths(output)


def test_cleanup_failure_notes_retain_paths_on_original_error_and_cli(
    build, tmp_path, monkeypatch, capsys
):
    output = tmp_path / 'output'
    export_build(build, output)
    previous = file_bytes(output)
    original = store.shutil.rmtree

    def fail_write(*args):
        raise OSError(errno.ENOSPC, 'injected full disk')

    def fail_cleanup(path):
        if '.stage-' in Path(path).name:
            raise OSError(errno.EACCES, 'injected cleanup failure')
        original(path)

    monkeypatch.setattr(store, '_write_stage', fail_write)
    monkeypatch.setattr(store.shutil, 'rmtree', fail_cleanup)
    with pytest.raises(ExportError) as error:
        export_build(build, output, force=True)
    retained = list(tmp_path.glob('.output.stage-*'))
    assert len(retained) == 1
    assert str(retained[0]) in '\n'.join(error.value.__notes__)
    assert file_bytes(output) == previous
    result = cli.main(['--input-build', str(build), '--output-dir', str(output), '--force'])
    assert result == 1
    stderr = capsys.readouterr().err
    assert 'PUBLICATION_IO' in stderr and 'Cleanup failed; retained ' in stderr


@pytest.mark.parametrize('use_cli', [False, True])
def test_interrupt_after_completed_commit_keeps_new_output_and_reports_commit(
    build, tmp_path, monkeypatch, capsys, use_cli
):
    output = tmp_path / 'output'
    export_build(build, output)
    previous = file_bytes(output)
    change_book(
        build,
        lambda book: book['chapters'][0]['content']['entries'].append(
            'New complete book revision.'
        ),
    )
    expected = render_build(build).files
    original = store.os.replace

    def interrupt_after_commit(source, destination):
        original(source, destination)
        if '.stage-' in Path(source).name:
            raise KeyboardInterrupt

    monkeypatch.setattr(store.os, 'replace', interrupt_after_commit)
    if use_cli:
        assert (
            cli.main(['--input-build', str(build), '--output-dir', str(output), '--force']) == 130
        )
        assert 'Publication already committed' in capsys.readouterr().err
    else:
        with pytest.raises(KeyboardInterrupt) as error:
            export_build(build, output, force=True)
        assert 'Publication already committed' in '\n'.join(error.value.__notes__)
    assert file_bytes(output) == expected != previous
    assert_no_temporary_paths(output)
