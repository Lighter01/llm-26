"""Fixtures are synthetic; integration reads only an explicitly selected build."""

import json
from pathlib import Path

import pytest

from dnd_rag.ingestion.markdown_export import read_build, render_build
from helpers import write_build


def pytest_addoption(parser):
    parser.addoption(
        '--input-build',
        type=Path,
        help='Existing verified resolved build (never assembled by tests)',
    )


@pytest.fixture
def fixture_data():
    def load(name):
        return json.loads(
            (Path(__file__).parent / 'fixtures' / (name + '.json')).read_text(encoding='utf-8')
        )

    return load


@pytest.fixture(scope='session')
def input_build(request):
    path = request.config.getoption('--input-build')
    if path is None:
        pytest.fail(
            'Integration requires --input-build PATH; use -m "not integration" for unit tests. No build is guessed or generated.'
        )
    return path.resolve(strict=True)


@pytest.fixture(scope='session')
def source_books(input_build):
    return {book['book']['id']: book for book in read_build(input_build)}


@pytest.fixture(scope='session')
def corpus(input_build):
    return render_build(input_build)


@pytest.fixture(scope='session')
def rendered(corpus):
    return {book.book_id: book for book in corpus.books}


@pytest.fixture
def build(tmp_path):
    path = tmp_path / 'input'
    write_build(path)
    return path
