"""Strict raw-question schema and exact evidence checks; no semantic inference."""

from collections import Counter

import yaml
from yaml.constructor import ConstructorError

from .corpus import BOOK_FILES, Corpus, find_candidates

EXPECTED_IDS = {
    f'{group}_{number:02}'
    for group, count in (('phb', 5), ('dmg', 5), ('mm', 5), ('multi', 5), ('insufficient', 3))
    for number in range(1, count + 1)
}
OWN_BOOKS = {'phb': 'xphb.md', 'dmg': 'xdmg.md', 'mm': 'xmm.md'}
MANUAL_REVIEW = (
    'PASS verifies structure and exact quote attribution only. Manually check English, '
    'reference-answer correctness, evidence sufficiency, source/section necessity, '
    'alternative completeness, and insufficient-data cases.'
)


class UniqueLoader(yaml.SafeLoader):
    """Safe YAML, including rejection of duplicate and unhashable mapping keys."""

    def construct_scalar(self, node):
        value = super().construct_scalar(node)
        value.encode('utf-8')  # Reject escaped lone surrogates, which UTF-8 cannot represent.
        return value

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as error:
                raise ConstructorError(
                    None, None, 'Unhashable mapping key', key_node.start_mark
                ) from error
            if duplicate:
                raise ConstructorError(
                    None, None, f'Duplicate mapping key: {key!r}', key_node.start_mark
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_questions(raw: bytes, errors: list[dict]):
    try:
        return yaml.load(raw.decode('utf-8'), Loader=UniqueLoader)
    except (
        UnicodeError,
        yaml.YAMLError,
        RecursionError,
        ValueError,
        KeyError,
        AttributeError,
    ) as error:
        # PyYAML's bool/timestamp constructors can leak native exceptions for bad scalars.
        item = {'code': 'INPUT_YAML', 'message': str(error), 'path': '$'}
        mark = getattr(error, 'problem_mark', None)
        if mark is not None:
            item.update(line=mark.line + 1, column=mark.column + 1)
        errors.append(item)
        return None


def nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


class _Validator:
    """One small traversal, retaining errors while skipping malformed subtrees."""

    def __init__(self, corpus: Corpus, errors: list[dict]):
        self.corpus = corpus
        self.errors = errors
        self.counts = dict.fromkeys(
            (
                'questions',
                'answerable',
                'insufficient',
                'facts',
                'alternatives',
                'matched_alternatives',
            ),
            0,
        )
        self.sources = dict.fromkeys(BOOK_FILES, 0)
        self.sections = Counter()
        self.questions = []
        self.cross_section = {group: [] for group in OWN_BOOKS}

    def error(self, code, message, path, **context):
        self.errors.append({'code': code, 'message': message, 'path': path, **context})

    def mapping(self, value, fields, path, context):
        if not isinstance(value, dict):
            self.error('TYPE', 'Expected an object', path, **context)
            return False
        missing = set(fields) - value.keys()
        extra = value.keys() - set(fields)
        if missing or extra:
            self.error(
                'FIELDS',
                f'Missing fields: {sorted(missing)}; unexpected fields: {sorted(map(repr, extra))}',
                path,
                **context,
            )
        return True

    def text(self, value, path, context):
        if not nonempty_text(value):
            self.error('TEXT', 'Expected a nonempty string', path, **context)
            return False
        return True

    def alternative(self, alt, path, context):
        if not self.mapping(alt, ('file', 'heading_path', 'quote'), path, context):
            return None
        filename, heading, quote = (alt.get(key) for key in ('file', 'heading_path', 'quote'))
        valid_file = isinstance(filename, str) and filename in BOOK_FILES
        valid_heading = (
            isinstance(heading, list) and bool(heading) and all(map(nonempty_text, heading))
        )
        context = {
            **context,
            'file': filename if isinstance(filename, str) else None,
            'heading_path': heading if valid_heading else None,
        }
        if not valid_file:
            self.error('FILE', f'Expected one of {BOOK_FILES}', path + '.file', **context)
        if not valid_heading:
            self.error(
                'HEADING_PATH',
                'Expected a nonempty list of nonempty strings',
                path + '.heading_path',
                **context,
            )
        valid_quote = self.text(quote, path + '.quote', context)
        if not (valid_file and valid_heading and valid_quote):
            return None
        self.sources[filename] += 1
        self.sections[(filename, tuple(heading))] += 1
        result = dict(alt)
        if filename not in self.corpus.files:
            return result  # The independent corpus error already explains the missing book.
        ranges = self.corpus.sections.get((filename, tuple(heading)), [])
        candidates = find_candidates(self.corpus, filename, heading, quote)
        if len(candidates) != 1:
            if not ranges:
                code = 'HEADING_NOT_FOUND'
            else:
                code = 'QUOTE_NOT_FOUND' if not candidates else 'QUOTE_AMBIGUOUS'
            self.error(
                code,
                f'Found {len(candidates)} exact matches in the specified section ranges. '
                'Check/refine heading_path or expand the verbatim quote.',
                path,
                candidates=candidates,
                **context,
            )
            return result
        result.update(candidates[0])
        self.counts['matched_alternatives'] += 1
        return result

    def fact(self, fact, path, context):
        if not self.mapping(fact, ('fact', 'alternatives'), path, context):
            return None
        self.text(fact.get('fact'), path + '.fact', context)
        alternatives = fact.get('alternatives')
        if not isinstance(alternatives, list) or not alternatives:
            self.error(
                'ALTERNATIVES', 'Expected a nonempty list', path + '.alternatives', **context
            )
            return None
        self.counts['alternatives'] += len(alternatives)
        checked = [
            self.alternative(
                alt, f'{path}.alternatives[{index}]', {**context, 'alternative_number': index + 1}
            )
            for index, alt in enumerate(alternatives)
        ]
        return {**fact, 'alternatives': [alt for alt in checked if alt is not None]}

    def question(self, question, path, index, seen):
        context = {'question_number': index + 1}
        if not self.mapping(
            question,
            ('id', 'question', 'reference_answer', 'answerable', 'evidence'),
            path,
            context,
        ):
            return None
        qid = question.get('id')
        if isinstance(qid, str):
            context['id'] = qid
            if qid in seen:
                self.error('DUPLICATE_ID', f'Duplicate question ID: {qid}', path + '.id', **context)
            seen.add(qid)
        if not isinstance(qid, str) or qid not in EXPECTED_IDS:
            self.error('ID', 'Expected an ID from the agreed set of 23', path + '.id', **context)
        for key in ('question', 'reference_answer'):
            self.text(question.get(key), f'{path}.{key}', context)
        answerable = question.get('answerable')
        if type(answerable) is not bool:
            self.error('BOOLEAN', 'Expected a YAML boolean', path + '.answerable', **context)
        else:
            self.counts['answerable' if answerable else 'insufficient'] += 1
            if (
                isinstance(qid, str)
                and qid in EXPECTED_IDS
                and (answerable != (not qid.startswith('insufficient_')))
            ):
                self.error('ANSWERABLE_ID', 'answerable contradicts the ID group', path, **context)
        evidence = question.get('evidence')
        if not isinstance(evidence, list):
            self.error('EVIDENCE', 'Expected a list', path + '.evidence', **context)
            return None
        if type(answerable) is bool and bool(evidence) != answerable:
            self.error(
                'EVIDENCE',
                'evidence must be nonempty iff answerable is true',
                path + '.evidence',
                **context,
            )
        self.counts['facts'] += len(evidence)
        group = qid.split('_')[0] if isinstance(qid, str) else None
        own_book = OWN_BOOKS.get(group)
        facts, file_sets, own_paths = [], [], set()
        for fi, fact in enumerate(evidence):
            location = {**context, 'fact_number': fi + 1}
            checked = self.fact(fact, f'{path}.evidence[{fi}]', location)
            if checked is None:
                continue
            facts.append(checked)
            files = {alt['file'] for alt in checked['alternatives']}
            file_sets.append(files)
            if files and own_book and own_book not in files:
                self.error(
                    'OWN_BOOK',
                    f'Each fact needs an alternative in {own_book}',
                    f'{path}.evidence[{fi}]',
                    **location,
                )
            own_paths.update(
                tuple(alt['heading_path'])
                for alt in checked['alternatives']
                if alt['file'] == own_book
            )
        if group == 'multi' and file_sets and all(file_sets) and set.intersection(*file_sets):
            self.error(
                'MULTI_BOOK', 'One book supplies alternatives for every fact', path, **context
            )
        self.questions.append(
            {
                'id': qid if isinstance(qid, str) else None,
                'own_book_paths': [list(p) for p in sorted(own_paths)],
            }
        )
        if own_book and len(own_paths) > 1:
            self.cross_section[group].append(qid)
        return {**question, 'evidence': facts}

    def validate(self, document):
        result = None
        if self.mapping(document, ('schema_version', 'questions'), '$', {}):
            if type(document.get('schema_version')) is not int or document['schema_version'] != 1:
                self.error(
                    'SCHEMA_VERSION', 'Expected integer schema_version: 1', '$.schema_version'
                )
            questions = document.get('questions')
            if not isinstance(questions, list):
                self.error('QUESTIONS', 'Expected a list', '$.questions')
            else:
                self.counts['questions'] = len(questions)
                seen = set()
                checked = [
                    self.question(q, f'$.questions[{i}]', i, seen) for i, q in enumerate(questions)
                ]
                missing = sorted(EXPECTED_IDS - seen)
                if len(questions) != 23 or missing:
                    self.error(
                        'QUESTION_SET', f'Expected 23 unique IDs; missing: {missing}', '$.questions'
                    )
                for group, candidates in self.cross_section.items():
                    if not candidates:
                        self.error(
                            'CROSS_SECTION',
                            f'{group} needs a question with two own-book heading paths',
                            '$.questions',
                            group=group,
                        )
                result = {**document, 'questions': checked}
        report = {
            'status': 'FAIL' if self.errors else 'PASS',
            'counts': self.counts,
            'errors': self.errors,
            'sources': self.sources,
            'sections': [
                {'file': file, 'heading_path': list(heading), 'alternatives': count}
                for (file, heading), count in sorted(self.sections.items())
            ],
            'questions': self.questions,
            'cross_section_candidates': self.cross_section,
            'manual_review_required': MANUAL_REVIEW,
        }
        return result, report


def validate_document(document, corpus: Corpus, errors: list[dict]):
    return _Validator(corpus, errors).validate(document)
