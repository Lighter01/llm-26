"""Read validated gold and its matching PASS passport; never fuzzy-match evidence."""

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from dnd_rag.config import read_yaml
from dnd_rag.contracts import Contract, RagError
from dnd_rag.indexing.corpus import CorpusSnapshot


class EvidenceSpan(Contract):
    file: Literal['xphb.md', 'xdmg.md', 'xmm.md']
    heading_path: list[str]
    quote: str = Field(min_length=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    # Enriched from the enclosing corpus passport on load, not inferred from hits.
    body_sha256: str = ''

    @model_validator(mode='after')
    def nonempty_range(self):
        if self.end_char <= self.start_char or self.line_end < self.line_start:
            raise ValueError('Invalid evidence range')
        return self


class EvidenceFact(Contract):
    fact: str = Field(min_length=1)
    alternatives: list[EvidenceSpan] = Field(min_length=1)


class GoldQuestion(Contract):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    answerable: bool
    evidence: list[EvidenceFact]

    @model_validator(mode='after')
    def evidence_matches_answerability(self):
        if bool(self.evidence) != self.answerable:
            raise ValueError('Answerable questions require evidence; insufficient require []')
        return self


class GoldDocument(Contract):
    schema_version: Literal[1]
    questions: list[GoldQuestion]
    corpus: dict
    raw_input_sha256: str = Field(pattern='^[a-f0-9]{64}$')


@dataclass(frozen=True)
class GoldSet:
    questions: list[GoldQuestion]
    corpus: dict
    raw_input_sha256: str
    file_sha256: str

    @property
    def answerable(self):
        return [q for q in self.questions if q.answerable]

    @property
    def insufficient(self):
        return [q for q in self.questions if not q.answerable]


def _validate_report(report, document, corpus):
    if (
        report.get('status') != 'PASS'
        or report.get('output_state') != 'written'
        or report.get('errors') != []
        or report.get('corpus') != document.corpus
        or report.get('raw_input_sha256') != document.raw_input_sha256
        or document.corpus != corpus.passport()
    ):
        raise ValueError('Gold/report/corpus passports disagree or report is not a fresh PASS')
    expected = {
        'questions': len(document.questions),
        'answerable': sum(q.answerable for q in document.questions),
        'insufficient': sum(not q.answerable for q in document.questions),
        'facts': sum(len(q.evidence) for q in document.questions),
        'alternatives': sum(len(f.alternatives) for q in document.questions for f in q.evidence),
    }
    expected['matched_alternatives'] = expected['alternatives']
    if report.get('counts') != expected:
        raise ValueError('Validation report counts disagree with selected gold')


def _checked_questions(document, corpus):
    ids = [q.id for q in document.questions]
    expected = {f'{prefix}_{i:02}' for prefix in ('phb', 'dmg', 'mm', 'multi') for i in range(1, 6)}
    if (
        len(ids) != len(set(ids))
        or {q.id for q in document.questions if q.answerable} != expected
        or {q.id for q in document.questions if not q.answerable}
        != {f'insufficient_{i:02}' for i in range(1, 4)}
    ):
        raise ValueError('Expected 20 primary and 3 separate insufficient questions')
    questions = []
    for question in document.questions:
        facts = []
        for fact in question.evidence:
            spans = []
            for span in fact.alternatives:
                book = corpus.books[span.file]
                actual = book.coordinates(span.start_char, span.end_char)
                if (
                    book.body[span.start_char : span.end_char] != span.quote
                    or any(getattr(span, k) != v for k, v in actual.items())
                    or not any(
                        s.attribution.heading_path == span.heading_path
                        and s.start <= span.start_char < span.end_char <= s.end
                        for s in book.sections
                    )
                ):
                    raise ValueError(f'{question.id}: evidence is not the exact mapped body slice')
                spans.append(span.model_copy(update={'body_sha256': book.body_sha256}))
            facts.append(fact.model_copy(update={'alternatives': spans}))
        questions.append(question.model_copy(update={'evidence': facts}))
    return questions


def load_gold(path: Path, corpus: CorpusSnapshot, report_path: Path) -> GoldSet:
    try:
        document = GoldDocument.model_validate(read_yaml(path))
        report = json.loads(report_path.read_text(encoding='utf-8'))
        _validate_report(report, document, corpus)
        return GoldSet(
            _checked_questions(document, corpus),
            document.corpus,
            document.raw_input_sha256,
            sha256(path.read_bytes()).hexdigest(),
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RagError,
    ) as exc:
        raise RagError('invalid_gold', f'{path}: {exc}') from exc
