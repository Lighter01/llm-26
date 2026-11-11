"""Strict audit of the saved Codex YAML, independent of its builder.

Checks the raw contract and exact quotes using both source_map and a separately
parsed Markdown heading tree. Semantic review is separate in semantic_review.json.
This helper does not publish production validated/questions.yaml or change inputs.
"""

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / 'data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8'
INPUT = ROOT / 'data/questions/questions_codex.yaml'
OUTPUT = Path(__file__).resolve().parent
EXPECTED = [
    f'{group}_{n:02}'
    for group, count in (('phb', 5), ('dmg', 5), ('mm', 5), ('multi', 5), ('insufficient', 3))
    for n in range(1, count + 1)
]


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in result:
            raise ValueError(f'Duplicate YAML key: {key!r}')
        result[key] = loader.construct_object(v, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def markdown_sections(body):
    """Independently derive exact heading paths and subtree character ranges."""
    stack = []
    records = []
    for match in re.finditer(r'^(#{1,6}) (.+)$', body, re.MULTILINE):
        level = len(match.group(1))
        # source_map stores logical titles, without exported bracket escapes.
        # This decodes heading labels only; quotes are never normalized.
        heading = re.sub(r'\\+(?=[\[\]])', '', match.group(2))
        while stack and stack[-1]['level'] >= level:
            stack.pop()['end_char'] = match.start()
        item = {
            'level': level,
            'heading_path': [r['heading'] for r in stack] + [heading],
            'heading': heading,
            'start_char': match.start(),
            'end_char': len(body),
        }
        records.append(item)
        stack.append(item)
    return records


def spans(body, quote):
    result = []
    pos = 0
    while (start := body.find(quote, pos)) >= 0:
        result.append((start, start + len(quote)))
        pos = start + 1
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default='mechanical_report.json')
    args = parser.parse_args()
    raw = INPUT.read_bytes()
    documents = list(yaml.load_all(raw, Loader=UniqueLoader))
    assert len(documents) == 1, 'Exactly one YAML document required'
    doc = documents[0]
    tree = yaml.compose(raw, Loader=yaml.SafeLoader)
    assert type(doc) is dict and set(doc) == {'schema_version', 'questions'}
    assert type(doc['schema_version']) is int and doc['schema_version'] == 1
    questions = doc['questions']
    assert type(questions) is list and len(questions) == 23
    assert [q['id'] for q in questions] == EXPECTED
    map_bytes = (CORPUS / 'source_map.jsonl').read_bytes()
    records = [json.loads(line) for line in map_bytes.decode('utf-8').splitlines()]
    corpus = {}
    for filename in ('xphb.md', 'xdmg.md', 'xmm.md'):
        data = (CORPUS / filename).read_bytes()
        assert b'\r' not in data
        full = data.decode('utf-8')
        assert full.startswith('---\n')
        close = full.index('\n---\n', 4) + len('\n---\n')
        assert full[close] == '\n'
        prefix = full[: close + 1]
        body = full[close + 1 :]
        source_map = [r for r in records if r['file'] == filename]
        independent = markdown_sections(body)
        expected_ranges = {
            (tuple(r['heading_path']), r['start_char'], r['end_char']) for r in source_map
        }
        parsed_ranges = {
            (tuple(r['heading_path']), r['start_char'], r['end_char']) for r in independent
        }
        assert parsed_ranges == expected_ranges, (
            f'Independent heading tree disagrees for {filename}'
        )
        assert len(source_map) == len(independent)
        corpus[filename] = {
            'body': body,
            'sections': source_map,
            'independent': independent,
            'prefix_lines': prefix.count('\n'),
            'file_sha256': digest(data),
            'body_sha256': digest(body.encode('utf-8')),
        }

    styles = collections.Counter()

    def check_styles(node, field=None):
        if isinstance(node, yaml.MappingNode):
            for key, val in node.value:
                check_styles(val, key.value)
        elif isinstance(node, yaml.SequenceNode):
            for val in node.value:
                check_styles(val, field)
        elif isinstance(node, yaml.ScalarNode) and node.tag.endswith(':str'):
            if field in ('quote', 'reference_answer'):
                assert node.style == '|', (field, node.style)
                assert not node.value.endswith('\n'), 'Expected |- chomping'
                styles[field] += 1
            else:
                assert node.style == '"', (field, node.value)

    check_styles(tree)

    per_question = []
    all_alts = []
    for q in questions:
        qid = q['id']
        assert set(q) == {'id', 'question', 'reference_answer', 'answerable', 'evidence'}, qid
        for key in ('id', 'question', 'reference_answer'):
            assert type(q[key]) is str and q[key].strip(), (qid, key)
        assert type(q['answerable']) is bool
        assert q['answerable'] == (not qid.startswith('insufficient_'))
        assert type(q['evidence']) is list and bool(q['evidence']) == q['answerable']
        own_book = {'phb': 'xphb.md', 'dmg': 'xdmg.md', 'mm': 'xmm.md'}.get(qid.split('_')[0])
        facts = []
        file_sets = []
        own_paths = set()
        for fi, fact in enumerate(q['evidence'], 1):
            assert set(fact) == {'fact', 'alternatives'}, (qid, fi)
            assert type(fact['fact']) is str and fact['fact'].strip()
            assert type(fact['alternatives']) is list and fact['alternatives']
            files = set()
            alternatives = []
            seen = set()
            for ai, alt in enumerate(fact['alternatives'], 1):
                assert set(alt) == {'file', 'heading_path', 'quote'}, (qid, fi, ai)
                assert alt['file'] in corpus
                assert type(alt['heading_path']) is list and alt['heading_path']
                assert all(type(s) is str and s.strip() for s in alt['heading_path'])
                assert type(alt['quote']) is str and alt['quote'].strip()
                key = (alt['file'], tuple(alt['heading_path']), alt['quote'])
                assert key not in seen, (qid, fi, 'Duplicate alternative')
                seen.add(key)
                book = corpus[alt['file']]
                sections = [r for r in book['sections'] if r['heading_path'] == alt['heading_path']]
                matches = spans(book['body'], alt['quote'])
                scoped = [
                    (s, e)
                    for s, e in matches
                    if any(r['start_char'] <= s and e <= r['end_char'] for r in sections)
                ]
                independent = [
                    (s, e)
                    for s, e in matches
                    if any(
                        r['heading_path'] == alt['heading_path']
                        and r['start_char'] <= s
                        and e <= r['end_char']
                        for r in book['independent']
                    )
                ]
                assert scoped == independent
                assert len(scoped) == 1, (qid, fi, ai, len(scoped), alt['heading_path'])
                start, end = scoped[0]
                assert book['body'][start:end] == alt['quote']
                # The raw input remains coordinate-free; only this separate audit has lines.
                line_first = book['body'].count('\n', 0, start) + 1 + book['prefix_lines']
                line_last = book['body'].count('\n', 0, end - 1) + 1 + book['prefix_lines']
                result = {
                    'alternative_number': ai,
                    'file': alt['file'],
                    'heading_path': alt['heading_path'],
                    'unique_exact_match': True,
                    'file_line_start': line_first,
                    'file_line_end': line_last,
                }
                alternatives.append(result)
                all_alts.append(result)
                files.add(alt['file'])
                if alt['file'] == own_book:
                    own_paths.add(tuple(alt['heading_path']))
            if own_book:
                assert own_book in files, (qid, fi, 'Missing own-book evidence')
            file_sets.append(files)
            facts.append({'fact_number': fi, 'fact': fact['fact'], 'alternatives': alternatives})
        if qid.startswith('multi_'):
            assert not set.intersection(*file_sets), (qid, 'One book supports every labelled fact')
        per_question.append(
            {
                'id': qid,
                'answerable': q['answerable'],
                'fact_count': len(facts),
                'alternative_count': sum(len(f['alternatives']) for f in facts),
                'own_book_paths': [list(p) for p in sorted(own_paths)],
                'facts': facts,
            }
        )
    cross_section = {}
    for group in ('phb', 'dmg', 'mm'):
        cross_section[group] = [
            q['id']
            for q in per_question
            if q['id'].startswith(group + '_') and len(q['own_book_paths']) > 1
        ]
        assert cross_section[group]
    summary = {
        'status': 'PASS',
        'questions': len(questions),
        'answerable': sum(q['answerable'] for q in questions),
        'insufficient': sum(not q['answerable'] for q in questions),
        'facts': sum(len(q['evidence']) for q in questions),
        'alternatives': len(all_alts),
        'unique_exact_matches': len(all_alts),
        'structural_errors': 0,
        'quote_or_path_errors': 0,
        'facts_with_multiple_alternatives': sum(
            len(f['alternatives']) > 1 for q in questions for f in q['evidence']
        ),
        'cross_section_candidates': cross_section,
        'independent_heading_tree_matches_source_map': True,
        'literal_scalar_counts': dict(styles),
    }
    report = {
        'input': str(INPUT.relative_to(ROOT)),
        'raw_input_sha256': digest(raw),
        'source_map_sha256': digest(map_bytes),
        'corpus': {
            name: {k: book[k] for k in ('file_sha256', 'body_sha256')}
            for name, book in corpus.items()
        },
        'summary': summary,
        'questions': per_question,
        'scope': 'PASS covers structure, exact unique quotes, both heading trees, and labelled file coverage. '
        'Truth, evidence sufficiency, source necessity, language, and insufficient cases are reviewed separately.',
    }
    path = OUTPUT / args.report
    assert path.parent == OUTPUT
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
