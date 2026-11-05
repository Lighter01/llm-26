import json
from bisect import bisect_right
from pathlib import Path

import yaml

REVISION = 'f9972ac22e696a105c482202646979e33e4b5a1e'


def baseline_data():
    return {
        'schema_version': 1,
        'corpus': {'directory': 'data/corpus'},
        'embedding': {'revision': REVISION},
    }


def write_yaml(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data), encoding='utf-8')
    return path


def make_corpus(directory: Path):
    directory.mkdir(parents=True)
    body = (
        '\n# Intro\n\nWelcome 😀.\n\n## Parent\n\nParent introduction.\n\n'
        '### Child\n\n'
        + ('Repeated paragraph with Unicode café.\n\n' * 12)
        + '##### Detail\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n'
        + '```text\n# not a heading\n```\n\n###### Deep\n\nTail text.\n'
        + '## Parent\n\nAnother occurrence.\n'
    )
    headings = [
        (body.index(text), text)
        for text in ('# Intro\n', '## Parent\n', '### Child\n', '##### Detail\n', '###### Deep\n')
    ]
    headings.append((body.rindex('## Parent\n'), '## Parent\n'))
    paths = [
        ['Intro'],
        ['Intro', 'Parent'],
        ['Intro', 'Parent', 'Child'],
        ['Intro', 'Parent', 'Child', 'Detail'],
        ['Intro', 'Parent', 'Child', 'Detail', 'Deep'],
        ['Intro', 'Parent'],
    ]
    starts = [0] + [i + 1 for i, c in enumerate(body) if c == '\n']
    records = []
    for book in ('xphb', 'xdmg', 'xmm'):
        meta = {
            'book_id': book.upper(),
            'title': book + ' title',
            'source': '5etools',
            'upstream_sha': 'a' * 40,
        }
        (directory / f'{book}.md').write_text(
            '---\n' + yaml.safe_dump(meta) + '---\n\n' + body, encoding='utf-8'
        )
        for i, ((start, text), path) in enumerate(zip(headings, paths)):
            level = text.index(' ')
            end = next(
                (pos for pos, heading in headings[i + 1 :] if heading.index(' ') <= level),
                len(body),
            )
            records.append(
                {
                    'file': f'{book}.md',
                    'book_id': book.upper(),
                    'heading_path': path,
                    'start_char': start,
                    'end_char': end,
                    'line_start': bisect_right(starts, start),
                    'line_end': bisect_right(starts, end - 1),
                    'printed_pages': [4] if i == 0 else None,
                    'page_attribution': 'explicit' if i == 0 else 'unknown',
                }
            )
    (directory / 'source_map.jsonl').write_text(
        ''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8'
    )
    return directory


def make_gold(directory, corpus):
    directory.mkdir(parents=True, exist_ok=True)
    questions = []
    for prefix in ('phb', 'dmg', 'mm', 'multi'):
        filename = {'phb': 'xphb.md', 'dmg': 'xdmg.md', 'mm': 'xmm.md', 'multi': 'xphb.md'}[prefix]
        book = corpus.books[filename]
        for i in range(1, 6):
            questions.append(
                {
                    'id': f'{prefix}_{i:02}',
                    'question': f'{prefix} question {i}?',
                    'reference_answer': 'Fixture answer',
                    'answerable': True,
                    'evidence': [
                        {
                            'fact': 'Fixture fact',
                            'alternatives': [
                                {
                                    'file': filename,
                                    'heading_path': ['Intro'],
                                    'quote': book.body[1:20],
                                    **book.coordinates(1, 20),
                                }
                            ],
                        }
                    ],
                }
            )
    questions.extend(
        {
            'id': f'insufficient_{i:02}',
            'question': f'Unknown {i}?',
            'reference_answer': 'Not enough context',
            'answerable': False,
            'evidence': [],
        }
        for i in range(1, 4)
    )
    data = {
        'schema_version': 1,
        'questions': questions,
        'corpus': corpus.passport(),
        'raw_input_sha256': 'a' * 64,
    }
    path = write_yaml(directory / 'questions.yaml', data)
    report = {
        'status': 'PASS',
        'output_state': 'written',
        'errors': [],
        'counts': {
            'questions': 23,
            'answerable': 20,
            'insufficient': 3,
            'facts': 20,
            'alternatives': 20,
            'matched_alternatives': 20,
        },
        'corpus': corpus.passport(),
        'raw_input_sha256': 'a' * 64,
    }
    (directory / 'validation_report.json').write_text(json.dumps(report))
    return path
