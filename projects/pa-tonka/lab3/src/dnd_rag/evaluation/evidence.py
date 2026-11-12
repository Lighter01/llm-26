"""Exact corpus evidence independent of any dataset size or agent output."""

from typing import Literal

from pydantic import Field, model_validator

from dnd_rag.contracts import Contract, RagError


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


class EvidenceCase(Contract):
    id: str
    answerable: bool = True
    evidence: list[EvidenceFact]


def validate_span(span: EvidenceSpan, corpus) -> EvidenceSpan:
    book = corpus.books[span.file]
    actual = book.coordinates(span.start_char, span.end_char)
    if (
        span.body_sha256 != book.body_sha256
        or book.body[span.start_char : span.end_char] != span.quote
        or any(getattr(span, k) != v for k, v in actual.items())
        or not any(
            s.attribution.heading_path == span.heading_path
            and s.start <= span.start_char < span.end_char <= s.end
            for s in book.sections
        )
    ):
        raise RagError(
            'invalid_evidence', 'Evidence must match the exact mapped corpus body and hash'
        )
    return span
