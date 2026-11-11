import pytest


def pytest_addoption(parser):
    for option in ('qdrant', 'models', 'llama'):
        parser.addoption(f'--run-{option}', action='store_true', default=False)


def pytest_collection_modifyitems(config, items):
    for item in items:
        for kind in ('qdrant', 'models', 'llama'):
            if item.get_closest_marker(f'rag_{kind}') and not config.getoption(f'--run-{kind}'):
                item.add_marker(pytest.mark.skip(reason=f'Opt in with --run-{kind}'))
