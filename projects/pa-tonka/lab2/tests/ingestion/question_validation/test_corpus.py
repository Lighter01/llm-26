import hashlib
import json

import pytest

from dnd_rag.ingestion.question_validation.corpus import find_candidates, load_corpus


def test_body_and_coordinates_preserve_unicode_and_all_whitespace(case):
    errors = []
    corpus = load_corpus(case.corpus, errors)
    assert errors == []
    book = corpus.files['xphb.md']
    assert book.body == case.bodies['xphb.md']
    assert book.body_sha256 == hashlib.sha256(book.body.encode('utf-8')).hexdigest()
    assert (
        corpus.source_map_sha256
        == hashlib.sha256((case.corpus / 'source_map.jsonl').read_bytes()).hexdigest()
    )
    start = book.body.index('Alpha')
    assert start != len(book.body[:start].encode('utf-8'))
    assert book.coordinates(start, start + 5) == {
        'start_char': start,
        'end_char': start + 5,
        'line_start': 5,
        'line_end': 5,
    }


@pytest.mark.parametrize(
    ('section', 'quote', 'count'),
    [
        ('First', 'Alpha', 1),
        ('First', 'Alpha rule.\n', 1),
        ('First', 'Repeat rule.', 1),
        ('Second', 'Repeat rule.', 1),
        ('First', 'aaa', 2),
        ('First', 'missing', 0),
        ('Missing', 'Alpha', 0),
        ('First', '\n\n## Second', 0),
    ],
)
def test_scoped_exact_matching_and_overlaps(case, section, quote, count):
    corpus = load_corpus(case.corpus, [])
    matches = find_candidates(corpus, 'xphb.md', ['Rules', section], quote)
    assert len(matches) == count
    for match in matches:
        body = case.bodies['xphb.md']
        start, end = match['start_char'], match['end_char']
        assert body[start:end] == quote
        assert match['line_start'] == body.count('\n', 0, start) + 1
        assert match['line_end'] == body.count('\n', 0, end - 1) + 1


def test_duplicate_ranges_do_not_duplicate_a_candidate(case):
    with (case.corpus / 'source_map.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(case.records[1]) + '\n')
    errors = []
    corpus = load_corpus(case.corpus, errors)
    assert errors == []
    assert len(corpus.sections[('xphb.md', ('Rules', 'First'))]) == 2
    assert len(find_candidates(corpus, 'xphb.md', ['Rules', 'First'], 'Alpha')) == 1


def test_repeated_heading_path_keeps_both_occurrences(case):
    case.records[2]['heading_path'] = ['Rules', 'First']
    (case.corpus / 'source_map.jsonl').write_text(
        ''.join(json.dumps(record) + '\n' for record in case.records), encoding='utf-8'
    )
    errors = []
    corpus = load_corpus(case.corpus, errors)
    assert errors == []
    matches = find_candidates(corpus, 'xphb.md', ['Rules', 'First'], 'Repeat rule.')
    assert len(matches) == 2
    assert matches[0]['start_char'] < matches[1]['start_char']


def test_quote_can_cover_a_section_exactly_through_its_last_lf(case):
    corpus = load_corpus(case.corpus, [])
    body = case.bodies['xphb.md']
    start, end = body.index('## First'), body.index('## Second')
    matches = find_candidates(corpus, 'xphb.md', ['Rules', 'First'], body[start:end])
    assert len(matches) == 1
    assert matches[0]['start_char'] == start and matches[0]['end_char'] == end
    assert matches[0]['line_end'] == body.count('\n', 0, end - 1) + 1


def test_one_separator_is_removed_and_the_remaining_body_is_untouched(case):
    file = case.corpus / 'xphb.md'
    raw = file.read_bytes().replace(b'---\n\n# Rules', b'---\n\n\n# Rules')
    file.write_bytes(raw)
    # The map is now stale, but body extraction must still retain the extra newline.
    errors = []
    corpus = load_corpus(case.corpus, errors)
    assert corpus.files['xphb.md'].body == '\n' + case.bodies['xphb.md']
    assert errors


@pytest.mark.parametrize(
    'damage', ['range', 'line', 'boolean', 'path', 'json', 'deep_json', 'crlf', 'utf8']
)
def test_malformed_corpus_is_reported(case, damage):
    map_path = case.corpus / 'source_map.jsonl'
    records = case.records
    if damage == 'range':
        records[0]['end_char'] += 9999
    elif damage == 'line':
        records[0]['line_end'] += 1
    elif damage == 'boolean':
        records[0]['start_char'] = False
    elif damage == 'path':
        records[0]['heading_path'] = [None]
    if damage in ('range', 'line', 'boolean', 'path'):
        map_path.write_text('\n'.join(json.dumps(record) for record in records), encoding='utf-8')
    elif damage == 'json':
        map_path.write_text('{broken}\n', encoding='utf-8')
    elif damage == 'deep_json':
        map_path.write_text('[' * 2000 + '0' + ']' * 2000 + '\n', encoding='utf-8')
    elif damage == 'crlf':
        file = case.corpus / 'xphb.md'
        file.write_bytes(file.read_bytes().replace(b'\n', b'\r\n'))
    else:
        (case.corpus / 'xphb.md').write_bytes(b'\xff')
    errors = []
    load_corpus(case.corpus, errors)
    assert errors
    assert all(error['code'] and error['message'] for error in errors)
    if damage not in ('crlf', 'utf8'):
        assert any(error.get('source_map_line') == 1 for error in errors)
