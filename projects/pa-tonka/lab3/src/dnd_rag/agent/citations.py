"""Stable dialog-scoped source numbers; validity never claims semantic support."""

import json
import re
import threading
from pathlib import Path

from dnd_rag.contracts import Contract, RagError
from dnd_rag.game.contracts import SourceRef


class CitationRef(Contract):
    number: int
    source_id: str
    source: SourceRef


class CitationValidation(Contract):
    valid_numbers: list[int]
    unknown_numbers: list[int]
    sources: list[SourceRef]


class CitationRegistry:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.lock = threading.RLock()

    def _path(self, scope):
        if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,180}', scope):
            raise RagError('invalid_citation_scope', 'Invalid transport session ID')
        return self.directory / (scope + '.json')

    def export(self, scope):
        with self.lock:
            path = self._path(scope)
            try:
                return (
                    [CitationRef.model_validate(r) for r in json.loads(path.read_text())]
                    if path.exists()
                    else []
                )
            except (ValueError, OSError) as exc:
                raise RagError(
                    'citation_registry', 'Cannot read preserved source registry'
                ) from exc

    def register(self, scope, hits):
        with self.lock:
            refs = self.export(scope)
            by_id = {r.source_id: r for r in refs}
            selected = []
            for hit in hits:
                meta = hit.chunk.metadata
                identity = f'rag:{meta.index_id}:{meta.chunk_id}'
                if identity not in by_id:
                    source = SourceRef(
                        source_id=identity,
                        book_id=meta.book_id,
                        source_file=meta.source_file,
                        provenance={
                            'index_id': meta.index_id,
                            'chunk_id': meta.chunk_id,
                            'body_sha256': meta.body_sha256,
                            'start_char': meta.start_char,
                            'end_char': meta.end_char,
                            'line_start': meta.line_start,
                            'line_end': meta.line_end,
                            'sections': [s.model_dump(mode='json') for s in meta.sections],
                            'text': hit.chunk.page_content,
                        },
                    )
                    ref = CitationRef(number=len(refs) + 1, source_id=identity, source=source)
                    refs.append(ref)
                    by_id[identity] = ref
                selected.append(by_id[identity])
            path = self._path(scope)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(
                json.dumps([r.model_dump(mode='json') for r in refs], ensure_ascii=False, indent=2)
            )
            temporary.replace(path)
            return selected

    def resolve(self, scope, number):
        return next((r.source for r in self.export(scope) if r.number == number), None)


def validate_citations(text, registry, scope):
    numbers = sorted({int(n) for n in re.findall(r'\[(\d{1,6})\]', text)})
    allowed = {r.number: r.source for r in registry.export(scope)}
    valid = [n for n in numbers if n in allowed]
    return CitationValidation(
        valid_numbers=valid,
        unknown_numbers=[n for n in numbers if n not in allowed],
        sources=[allowed[n] for n in valid],
    )
