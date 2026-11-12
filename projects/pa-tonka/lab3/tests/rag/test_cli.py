from dnd_rag.__main__ import main


def test_admin_help_and_invalid_index(capsys):
    assert main(['--help']) == 0
    output = capsys.readouterr().out
    assert 'inspect-index' in output
    assert main(['build-index', '--help']) == 0
    assert '--config' in capsys.readouterr().out
    assert main(['reset-index', '--index-id', 'invalid']) == 2
