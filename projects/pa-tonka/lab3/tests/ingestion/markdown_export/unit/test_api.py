"""Public API rejects malformed book envelopes with domain errors."""

import pytest

from dnd_rag.ingestion.markdown_export import ExportError, render_book
from helpers import add_entity, change_book, empty_book, run_cli


@pytest.mark.parametrize(
    ('field', 'value', 'code'),
    [
        ('scope', None, 'INCOMPLETE_BOOK'),
        ('scope', [], 'INCOMPLETE_BOOK'),
        ('chapters', [None], 'CHAPTERS'),
        ('chapters', ['text'], 'CHAPTERS'),
        ('chapters', [{'chapter_index': False}], 'CHAPTER_ORDER'),
        ('book', None, 'BOOK_ID'),
        ('domain', None, 'INVALID_PAYLOAD'),
        ('upstream', None, 'INVALID_PAYLOAD'),
    ],
)
def test_invalid_envelope_is_a_contextual_export_error(field, value, code):
    book = empty_book()
    book[field] = value
    with pytest.raises(ExportError) as error:
        render_book(book)
    assert error.value.code == code


@pytest.mark.parametrize('value', [None, [], 'not a book'])
def test_nonobject_book_fails_without_python_traceback(value):
    with pytest.raises(ExportError, match='INVALID_PAYLOAD'):
        render_book(value)


@pytest.mark.parametrize(('field', 'value'), [('scope', None), ('chapters', [None])])
def test_cli_handles_invalid_envelope_without_traceback(build, tmp_path, field, value):
    change_book(build, lambda b: b.update({field: value}))
    output = tmp_path / 'output'
    result = run_cli(tmp_path, '--input-build', build, '--output-dir', output)
    assert result.returncode == 1 and 'Traceback' not in result.stderr
    assert not output.exists()


def test_invalid_native_numeric_value_is_a_contextual_export_error(fixture_data):
    monster = fixture_data('monster')
    monster['initiative'] = {'initiative': 1.5}
    book = empty_book('XMM')
    add_entity(book, monster, 'monster', insertion=True)
    with pytest.raises(ExportError) as error:
        render_book(book)
    assert error.value.code == 'INVALID_PAYLOAD'
    assert error.value.context['book'] == 'XMM'
    assert error.value.context['heading_path'][-1] == monster['name']


def test_cli_handles_invalid_native_numeric_value_without_traceback(build, tmp_path, fixture_data):
    monster = fixture_data('monster')
    monster['initiative'] = {'initiative': 1.5}
    change_book(build, lambda book: add_entity(book, monster, 'monster', insertion=True))
    output = tmp_path / 'output'
    result = run_cli(tmp_path, '--input-build', build, '--output-dir', output)
    assert result.returncode == 1 and 'INVALID_PAYLOAD' in result.stderr
    assert monster['name'] in result.stderr and 'Traceback' not in result.stderr
    assert not output.exists()


def test_unknown_schema_and_incomplete_scope_fail():
    book = empty_book()
    book['schema_version'] = 'future'
    with pytest.raises(ExportError, match='UNSUPPORTED_SCHEMA'):
        render_book(book)
    book['schema_version'] = '1.0.0'
    book['scope']['book_complete'] = False
    with pytest.raises(ExportError, match='INCOMPLETE_BOOK'):
        render_book(book)
