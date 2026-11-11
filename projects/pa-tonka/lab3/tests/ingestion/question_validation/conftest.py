"""Small independent books and a complete v1 question set; no exporter runs."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

FILES = ('xphb.md', 'xdmg.md', 'xmm.md')
BODY = (
    '# Rules\n\n## First\n\nPréface 🐉: Alpha rule.\nRepeat rule.\naaaa\n\n'
    '## Second\n\nBeta rule.\nRepeat rule.\n'
)


def alternative(file='xphb.md', section='First', quote='Alpha rule.'):
    return {'file': file, 'heading_path': ['Rules', section], 'quote': quote}


@pytest.fixture
def write_corpus(tmp_path):
    def write(bodies=None, records=None):
        directory = tmp_path / 'corpus'
        directory.mkdir(exist_ok=True)
        bodies = bodies or dict.fromkeys(FILES, BODY)
        if records is None:
            records = []
            for file, body in bodies.items():
                split = body.index('## Second')
                for path, start, end in (
                    (['Rules'], 0, len(body)),
                    (['Rules', 'First'], body.index('## First'), split),
                    (['Rules', 'Second'], split, len(body)),
                ):
                    records.append(
                        {
                            'file': file,
                            'heading_path': path,
                            'start_char': start,
                            'end_char': end,
                            'line_start': body.count('\n', 0, start) + 1,
                            'line_end': body.count('\n', 0, end - 1) + 1,
                        }
                    )
        for file, body in bodies.items():
            prefix = f'---\nbook_id: {Path(file).stem.upper()}\n---\n\n'
            (directory / file).write_bytes((prefix + body).encode('utf-8'))
        (directory / 'source_map.jsonl').write_bytes(
            ''.join(json.dumps(record, ensure_ascii=False) + '\n' for record in records).encode(
                'utf-8'
            )
        )
        return directory, bodies, records

    return write


@pytest.fixture
def case(tmp_path, write_corpus):
    questions = []
    for group, file in zip(('phb', 'dmg', 'mm'), FILES, strict=True):
        for number in range(1, 6):
            alternatives = [alternative(file)]
            if number == 1:
                alternatives.append(alternative(file, 'Second', 'Beta rule.'))
            questions.append(
                {
                    'id': f'{group}_{number:02}',
                    'question': 'Which rule applies?',
                    'reference_answer': 'The stated rule applies.',
                    'answerable': True,
                    'evidence': [{'fact': 'A required fact.', 'alternatives': alternatives}],
                }
            )
    for number in range(1, 6):
        question = copy.deepcopy(questions[0])
        question['id'] = f'multi_{number:02}'
        question['evidence'] = [
            {'fact': 'First book fact.', 'alternatives': [alternative()]},
            {
                'fact': 'Second book fact.',
                'alternatives': [alternative('xdmg.md', 'Second', 'Beta rule.')],
            },
        ]
        questions.append(question)
    for number in range(1, 4):
        question = copy.deepcopy(questions[0])
        question.update(id=f'insufficient_{number:02}', answerable=False, evidence=[])
        questions.append(question)
    directory, bodies, records = write_corpus()
    context = SimpleNamespace(
        input=tmp_path / 'raw.yaml',
        corpus=directory,
        output=tmp_path / 'validated',
        document={'schema_version': 1, 'questions': questions},
        bodies=bodies,
        records=records,
    )

    def save(raw=None):
        text = raw if raw is not None else yaml.safe_dump(context.document, sort_keys=False)
        context.input.write_bytes(text.encode('utf-8'))
        return context.input

    context.save = save
    save()
    return context
