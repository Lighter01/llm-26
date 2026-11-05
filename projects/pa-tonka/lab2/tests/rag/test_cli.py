from dnd_rag.__main__ import main


def test_reset_selectors_exclusive():
    assert main(['reset-index', '--config', 'x.yaml', '--index-id', 'a' * 64]) == 2
    assert main(['reset-index']) == 2
    assert main(['reset-index', '--index-id', 'bad']) == 2


def test_help_has_implemented_commands(capsys):
    assert main(['--help']) == 0
    output = capsys.readouterr().out
    assert 'build-index' in output and 'reset-index' in output


def test_experiment_help_and_required_name(capsys):
    assert main(['experiment', '--help']) == 0
    assert '--experiment-name' in capsys.readouterr().out
    assert main(['experiment', '--config', 'x.yaml']) == 2
