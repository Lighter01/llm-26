"""Shared data contracts; importing this module never loads a model."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class RagError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict:
        result = {'code': self.code, 'message': self.message}
        if self.details is not None:
            result['details'] = self.details
        return result


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)


class SectionAttribution(Contract):
    heading_path: list[str]
    section_start_char: int
    section_end_char: int
    printed_pages: list[int] | None
    page_attribution: Literal['explicit', 'partial', 'inherited_section_start', 'unknown']


class DraftMetadata(Contract):
    schema_version: Literal[1] = 1
    source_file: str
    body_sha256: str
    book_id: str
    book_title: str
    source_system: str
    upstream_sha: str
    start_char: int
    end_char: int
    line_start: int
    line_end: int
    token_count: int
    sections: list[SectionAttribution]


class ChunkDraft(Contract):
    page_content: str
    metadata: DraftMetadata


class ChunkMetadata(DraftMetadata):
    chunk_id: str
    index_id: str


class Chunk(Contract):
    page_content: str
    metadata: ChunkMetadata

    def to_document(self):
        from langchain_core.documents import Document

        return Document(page_content=self.page_content, metadata=self.metadata.model_dump())


class ChunkRef(Contract):
    chunk_id: str
    source_file: str
    body_sha256: str
    start_char: int
    end_char: int
    line_start: int
    line_end: int
    token_count: int


class IndexIdentity(Contract):
    index_id: str
    collection: str
    build_spec: dict


class ReadyIndex(IndexIdentity):
    build_id: str
    expected_points: int
    build_provenance: dict


class StageEvent(Contract):
    name: str
    status: Literal['executed', 'reused', 'skipped', 'failed']
    elapsed_ms: float | None
    details: dict = {}


class EnsureResult(Contract):
    index: ReadyIndex
    action: Literal['built', 'reused', 'rebuilt']
    reason: str
    stages: list[StageEvent]


class RetrievalHit(Contract):
    rank: int
    score: float
    score_kind: Literal['cosine', 'rrf']
    chunk: Chunk


class RetrievalResult(Contract):
    question: str
    index_id: str
    build_id: str
    mode: Literal['dense', 'hybrid']
    hits: list[RetrievalHit]
    timings_ms: dict[str, float]
