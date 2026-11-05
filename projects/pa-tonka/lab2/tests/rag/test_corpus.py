import json

import pytest

from dnd_rag.contracts import RagError
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.ingestion.question_validation.corpus import load_corpus as validator_load
from tests.rag.fixtures import make_corpus


def test_body_coordinates_match_validator(tmp_path):
    directory = make_corpus(tmp_path / 'corpus')
    corpus = load_corpus(directory)
    errors = []
    original = validator_load(directory, errors)
    assert errors == []
    for name, book in corpus.books.items():
        assert book.body.startswith('\n# Intro')
        assert book.body.endswith('\n')
        assert book.body == original.files[name].body
        for start, end in [(0, 1), (2, 24), (0, len(book.body)), (5, 90)]:
            assert book.coordinates(start, end) == original.files[name].coordinates(start, end)


@pytest.mark.parametrize('damage', ['crlf', 'range', 'crossing'])
def test_invalid_corpus_rejected(tmp_path, damage):
    directory = make_corpus(tmp_path / 'corpus')
    if damage == 'crlf':
        path = directory / 'xphb.md'
        path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
    else:
        path = directory / 'source_map.jsonl'
        records = [json.loads(line) for line in path.read_text().splitlines()]
        if damage == 'range':
            records[0]['line_end'] = 10000
        else:
            records[2]['end_char'] = records[1]['end_char'] + 2
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))
    with pytest.raises(RagError):
        load_corpus(directory)
