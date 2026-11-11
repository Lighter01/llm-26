"""CLI publication and failure behavior on the explicit complete corpus."""

import pytest

from helpers import (
    assert_no_temporary_paths,
    change_book,
    copy_build,
    file_bytes,
    run_cli,
    snapshot,
)


@pytest.mark.integration
def test_full_books_cli_create_force_and_failed_render(input_build, corpus, tmp_path):
    output = tmp_path / 'complete'
    first = run_cli(tmp_path, '--input-build', input_build, '--output-dir', output, seed='11')
    assert first.returncode == 0, first.stderr
    assert file_bytes(output) == corpus.files
    forced = run_cli(
        tmp_path, '--input-build', input_build, '--output-dir', output, '--force', seed='23'
    )
    assert forced.returncode == 0, forced.stderr
    assert file_bytes(output) == corpus.files
    copied = tmp_path / 'copied-input'
    copy_build(input_build, copied)
    before = snapshot(output)
    change_book(
        copied, lambda b: b['chapters'][0]['content']['entries'].append('{@future Lost content}')
    )
    failure = run_cli(tmp_path, '--input-build', copied, '--output-dir', output, '--force')
    assert failure.returncode == 1 and 'UNKNOWN_TAG' in failure.stderr
    assert snapshot(output) == before
    assert_no_temporary_paths(output)
