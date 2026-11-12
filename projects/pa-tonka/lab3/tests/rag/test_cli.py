from dnd_rag.__main__ import main


def test_admin_help_and_invalid_index(capsys):
    assert main(['--help']) == 0
    output = capsys.readouterr().out
    assert 'inspect-index' in output
    assert main(['build-index', '--help']) == 0
    assert '--config' in capsys.readouterr().out
    assert main(['reset-index', '--index-id', 'invalid']) == 2


def test_game_data_help_exposes_only_real_paths(capsys):
    assert main(['prepare-game-data', '--help']) == 0
    output = capsys.readouterr().out
    assert '--source' in output and '--output' in output
