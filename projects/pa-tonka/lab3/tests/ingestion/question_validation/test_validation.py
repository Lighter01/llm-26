import copy
import hashlib
import json

import pytest
import yaml

from dnd_rag.ingestion.question_validation import validate_questions


def run(case):
    return validate_questions(case.input, case.corpus, case.output)


def test_complete_dataset_preserves_values_and_adds_verified_coordinates(case):
    before = {file: file.read_bytes() for file in [case.input, *case.corpus.iterdir()]}
    result = run(case)
    assert result.report['status'] == 'PASS'
    assert result.report['counts'] == {
        'questions': 23,
        'answerable': 20,
        'insufficient': 3,
        'facts': 25,
        'alternatives': 28,
        'matched_alternatives': 28,
    }
    assert result.report['cross_section_candidates'] == {
        'phb': ['phb_01'],
        'dmg': ['dmg_01'],
        'mm': ['mm_01'],
    }
    assert result.report['manual_review_required']
    assert result.report['output_state'] == 'written'
    assert sum(result.report['sources'].values()) == 28
    assert sum(item['alternatives'] for item in result.report['sections']) == 28
    document = yaml.safe_load(result.questions_path.read_bytes())
    assert document.pop('raw_input_sha256') == hashlib.sha256(case.input.read_bytes()).hexdigest()
    passport = document.pop('corpus')
    assert set(passport['files']) == set(case.bodies)
    assert (
        passport['source_map_sha256']
        == hashlib.sha256((case.corpus / 'source_map.jsonl').read_bytes()).hexdigest()
    )
    for file, body in case.bodies.items():
        assert passport['files'][file] == {
            'body_sha256': hashlib.sha256(body.encode('utf-8')).hexdigest()
        }
    for question in document['questions']:
        for fact in question['evidence']:
            for alternative in fact['alternatives']:
                start, end = (alternative.pop(key) for key in ('start_char', 'end_char'))
                first, last = (alternative.pop(key) for key in ('line_start', 'line_end'))
                body = case.bodies[alternative['file']]
                assert body[start:end] == alternative['quote']
                assert (first, last) == (
                    body.count('\n', 0, start) + 1,
                    body.count('\n', 0, end - 1) + 1,
                )
    assert document == case.document
    assert {file: file.read_bytes() for file in before} == before
    assert str(case.input.parent) not in result.questions_path.read_text(encoding='utf-8')
    assert json.loads((case.output / 'validation_report.json').read_bytes()) == result.report


def test_question_order_and_cross_book_alternatives_are_preserved(case):
    question = case.document['questions'][0]
    extra = copy.deepcopy(case.document['questions'][5]['evidence'][0]['alternatives'][0])
    question['evidence'][0]['alternatives'].append(extra)
    case.document['questions'].reverse()
    case.save()
    result = run(case)
    assert result.report['status'] == 'PASS'
    actual = yaml.safe_load(result.questions_path.read_bytes())
    assert [q['id'] for q in actual['questions']] == [q['id'] for q in case.document['questions']]
    assert len(actual['questions'][-1]['evidence'][0]['alternatives']) == 3


@pytest.mark.parametrize('trailing_lf', [False, True])
def test_yaml_literal_chomping_is_respected_exactly(case, trailing_lf):
    class Literal(str):
        pass

    class Dumper(yaml.SafeDumper):
        pass

    Dumper.add_representer(
        Literal,
        lambda dumper, value: dumper.represent_scalar('tag:yaml.org,2002:str', value, style='|'),
    )
    quote = 'Alpha rule.' + ('\n' if trailing_lf else '')
    case.document['questions'][0]['evidence'][0]['alternatives'][0]['quote'] = Literal(quote)
    raw = yaml.dump(case.document, Dumper=Dumper, sort_keys=False)
    assert ('quote: |\n' if trailing_lf else 'quote: |-\n') in raw
    case.save(raw)
    result = run(case)
    assert result.report['status'] == 'PASS'
    alternative = yaml.safe_load(result.questions_path.read_bytes())['questions'][0]['evidence'][0][
        'alternatives'
    ][0]
    assert alternative['quote'] == quote
    assert alternative['line_start'] == alternative['line_end'] == 5


@pytest.mark.parametrize('separator', ['\x85', '\u2028', '\u2029'], ids=['NEL', 'LS', 'PS'])
def test_unicode_line_separators_survive_output_yaml(case, write_corpus, separator):
    quote = f'Préface 🐉:{separator}more\n'
    answer = f'First answer.{separator}Second answer.\nThird answer.'
    bodies = {file: body.replace('Préface 🐉:', quote) for file, body in case.bodies.items()}
    write_corpus(bodies=bodies)
    question = case.document['questions'][0]
    question['reference_answer'] = answer
    question['evidence'][0]['alternatives'][0]['quote'] = quote
    # Escaped input scalars avoid YAML's own normalization of a raw NEL character.
    case.save(yaml.safe_dump(case.document, sort_keys=False, allow_unicode=False))
    result = run(case)
    assert result.report['status'] == 'PASS'
    actual = yaml.safe_load(result.questions_path.read_bytes())['questions'][0]
    assert actual['reference_answer'] == answer
    alternative = actual['evidence'][0]['alternatives'][0]
    assert alternative['quote'] == quote
    assert alternative['line_start'] == alternative['line_end'] == 5
    assert bodies['xphb.md'][alternative['start_char'] : alternative['end_char']] == quote


@pytest.mark.parametrize('field', ['id', 'reference_answer', 'quote'])
def test_escaped_lone_surrogate_fails_with_a_readable_report(case, field):
    question = case.document['questions'][0]
    if field == 'quote':
        question['evidence'][0]['alternatives'][0][field] = '\ud800'
    else:
        question[field] = '\ud800'
    case.save()
    assert b'\\uD800' in case.input.read_bytes()
    result = run(case)
    assert result.report['status'] == 'FAIL' and result.questions_path is None
    assert result.report['errors']
    assert json.loads((case.output / 'validation_report.json').read_bytes()) == result.report
    assert not (case.output / 'questions.yaml').exists()


@pytest.mark.parametrize(
    ('path', 'value'),
    [
        (('schema_version',), True),
        (('schema_version',), 1.0),
        (('questions',), {}),
        (('questions', 0, 'id'), []),
        (('questions', 0, 'question'), '   '),
        (('questions', 0, 'reference_answer'), None),
        (('questions', 0, 'answerable'), 1),
        (('questions', 0, 'answerable'), 'true'),
        (('questions', 0, 'evidence'), []),
        (('questions', 0, 'evidence'), {}),
        (('questions', 0, 'evidence', 0, 'fact'), ''),
        (('questions', 0, 'evidence', 0, 'alternatives'), []),
        (('questions', 0, 'evidence', 0, 'alternatives', 0, 'file'), '../xphb.md'),
        (('questions', 0, 'evidence', 0, 'alternatives', 0, 'heading_path'), []),
        (('questions', 0, 'evidence', 0, 'alternatives', 0, 'heading_path'), ['Rules', None]),
        (('questions', 0, 'evidence', 0, 'alternatives', 0, 'quote'), '\n  '),
    ],
)
def test_invalid_types_and_empty_values_fail_without_publication(case, path, value):
    node = case.document
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    case.save()
    result = run(case)
    assert result.report['status'] == 'FAIL'
    assert result.report['errors']
    assert result.questions_path is None
    assert not (case.output / 'questions.yaml').exists()


@pytest.mark.parametrize('level', ['root', 'question', 'fact', 'alternative'])
@pytest.mark.parametrize('change', ['extra', 'missing'])
def test_exact_field_sets_at_every_level(case, level, change):
    question = case.document['questions'][0]
    fact = question['evidence'][0]
    nodes = {
        'root': (case.document, 'schema_version'),
        'question': (question, 'reference_answer'),
        'fact': (fact, 'fact'),
        'alternative': (fact['alternatives'][0], 'quote'),
    }
    node, key = nodes[level]
    if change == 'extra':
        node['unexpected'] = 'extra'
    else:
        del node[key]
    case.save()
    assert run(case).report['status'] == 'FAIL'


@pytest.mark.parametrize(
    'failure', ['duplicate', 'unknown', 'missing', 'negative', 'own', 'multi', 'sections']
)
def test_dataset_and_source_consistency_rules(case, failure):
    questions = case.document['questions']
    if failure == 'duplicate':
        questions[1]['id'] = questions[0]['id']
    elif failure == 'unknown':
        questions[1]['id'] = 'phb_99'
    elif failure == 'missing':
        questions.pop()
    elif failure == 'negative':
        questions[-1]['evidence'] = copy.deepcopy(questions[0]['evidence'])
    elif failure == 'own':
        questions[0]['evidence'] = copy.deepcopy(questions[5]['evidence'])
    elif failure == 'multi':
        questions[15]['evidence'][1]['alternatives'][0]['file'] = 'xphb.md'
    else:
        questions[0]['evidence'][0]['alternatives'].pop()
    case.save()
    result = run(case)
    assert result.report['status'] == 'FAIL'
    assert result.report['errors']


@pytest.mark.parametrize(
    'kind', ['duplicate_key', 'documents', 'syntax', 'unsafe_tag', 'unhashable']
)
def test_yaml_errors_are_readable(case, kind):
    raw = {
        'duplicate_key': case.input.read_text(encoding='utf-8') + '\nschema_version: 1\n',
        'documents': 'schema_version: 1\nquestions: []\n---\n{}\n',
        'syntax': 'questions: [\n',
        'unsafe_tag': '!!python/tuple [1, 2]\n',
        'unhashable': '? [not, hashable]\n: value\n',
    }[kind]
    case.save(raw)
    result = run(case)
    assert result.report['status'] == 'FAIL'
    assert result.report['errors'][0]['message']
    assert result.report['errors'][0]['line'] >= 1
    assert result.report['errors'][0]['column'] >= 1
    assert result.questions_path is None


@pytest.mark.parametrize('kind', ['path', 'quote', 'ambiguous'])
def test_quote_errors_include_record_context_and_candidates(case, kind):
    alternative = case.document['questions'][0]['evidence'][0]['alternatives'][0]
    if kind == 'path':
        alternative['heading_path'] = ['Rules', 'Missing']
    elif kind == 'quote':
        alternative['quote'] = 'Alpha RULE.'
    else:
        alternative.update(heading_path=['Rules'], quote='Repeat rule.')
    case.save()
    result = run(case)
    assert result.report['status'] == 'FAIL'
    errors = [error for error in result.report['errors'] if error.get('id') == 'phb_01']
    error = next(error for error in errors if error.get('alternative_number') == 1)
    assert error['fact_number'] == 1 and error['file'] == 'xphb.md'
    assert error['heading_path'] == alternative['heading_path']
    if kind == 'ambiguous':
        assert len(error['candidates']) == 2


def test_independent_errors_are_accumulated(case):
    questions = case.document['questions']
    questions[0]['question'] = ''
    questions[1]['evidence'][0]['alternatives'][0]['quote'] = 'Absent quote.'
    questions[2]['answerable'] = 'true'
    case.save()
    errors = run(case).report['errors']
    assert {'phb_01', 'phb_02', 'phb_03'} <= {error.get('id') for error in errors}


def test_missing_input_and_books_produce_reports(case):
    case.input.unlink()
    (case.corpus / 'xphb.md').unlink()
    result = run(case)
    assert result.report['status'] == 'FAIL'
    assert len(result.report['errors']) >= 2
    assert (case.output / 'validation_report.json').is_file()
