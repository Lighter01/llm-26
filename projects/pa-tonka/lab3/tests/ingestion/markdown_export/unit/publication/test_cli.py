import pytest

from dnd_rag.ingestion.markdown_export import ExportError
from dnd_rag.ingestion.markdown_export import __main__ as cli
from helpers import change_book, file_bytes, run_cli, snapshot, write_build


def test_help_and_required_input_have_no_side_effects(tmp_path):
    help_result = run_cli(tmp_path, '--help')
    assert help_result.returncode == 0
    assert all(flag in help_result.stdout for flag in ('--input-build', '--output-dir', '--force'))
    result = run_cli(tmp_path)
    assert result.returncode == 2 and '--input-build' in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_default_output_location_and_repeated_force(tmp_path):
    build = tmp_path / 'build'
    manifest = write_build(build, order=('XMM', 'XDMG', 'XPHB'))
    before = snapshot(build)
    expected = tmp_path / 'data/markdown/5etools' / manifest['upstream']['checkout_sha']
    first = run_cli(tmp_path, '--input-build', build)
    assert first.returncode == 0, first.stderr
    assert first.stdout.index('XMM:') < first.stdout.index('XDMG:') < first.stdout.index('XPHB:')
    assert 'created' in first.stdout and str(expected) in first.stdout
    corpus = snapshot(expected)
    second = run_cli(tmp_path, '--input-build', build)
    assert (
        second.returncode == 1
        and 'OUTPUT_EXISTS' in second.stderr
        and 'Traceback' not in second.stderr
    )
    assert snapshot(expected) == corpus
    forced = run_cli(tmp_path, '--input-build', build, '--force', seed='97')
    assert forced.returncode == 0 and 'replaced' in forced.stdout
    assert file_bytes(expected) == {name: raw for name, (raw, _) in corpus.items()}
    assert snapshot(build) == before
    assert not list(expected.parent.glob('.*'))


@pytest.mark.parametrize('failure', ['missing', 'hash', 'tag'])
def test_cli_failure_preserves_previous_valid_output(tmp_path, failure):
    build = tmp_path / 'build'
    write_build(build)
    output = tmp_path / 'output'
    assert run_cli(tmp_path, '--input-build', build, '--output-dir', output).returncode == 0
    before = snapshot(output)
    if failure == 'missing':
        (build / 'xphb.resolved.json').unlink()
    elif failure == 'hash':
        (build / 'xphb.resolved.json').write_bytes(b'damaged')
    else:
        change_book(
            build,
            lambda b: b['chapters'][0]['content']['entries'].append(
                'Before {@future Valuable rules}'
            ),
        )
    result = run_cli(tmp_path, '--input-build', build, '--output-dir', output, '--force')
    assert result.returncode == 1 and 'Traceback' not in result.stderr
    if failure == 'tag':
        assert 'UNKNOWN_TAG' in result.stderr and 'First Part' in result.stderr
    else:
        assert 'INPUT_' in result.stderr or 'INVALID_BUILD' in result.stderr
    assert snapshot(output) == before
    assert not list(tmp_path.glob('.output.*'))


def test_main_keyboard_interrupt_and_io_errors_are_clear(monkeypatch, capsys):
    def cancel(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, 'export_build', cancel)
    assert cli.main(['--input-build', 'explicit']) == 130
    assert 'cancelled' in capsys.readouterr().err

    def fail(*args, **kwargs):
        raise ExportError('PUBLICATION_IO', 'disk full')

    monkeypatch.setattr(cli, 'export_build', fail)
    assert cli.main(['--input-build', 'explicit']) == 1
    assert 'PUBLICATION_IO: disk full' in capsys.readouterr().err
