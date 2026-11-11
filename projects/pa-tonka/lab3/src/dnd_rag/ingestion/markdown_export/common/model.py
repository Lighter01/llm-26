"""Small public values shared by the standalone Markdown renderer."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BOOK_IDS = ('XPHB', 'XDMG', 'XMM')
ARTIFACTS = frozenset((*[book.lower() + '.md' for book in BOOK_IDS], 'source_map.jsonl'))


class ExportError(ValueError):
    """Unsupported or inconsistent input, with the location that needs review."""

    def __init__(self, code: str, message: str, **context: Any):
        self.code = code
        self.context = context
        location = ', '.join(
            f'{key}={value}' for key, value in context.items() if value is not None
        )
        super().__init__(f'{code}: {message}' + (f' ({location})' if location else ''))


@dataclass
class Diagnostics:
    book_id: str
    messages: list[dict] = field(default_factory=list)
    components: dict[str, dict] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def note(self, code: str, **details: Any) -> None:
        self.messages.append({'code': code, 'book_id': self.book_id, **details})

    def count(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1


@dataclass(frozen=True)
class RenderedBook:
    book_id: str
    markdown: str
    body: str
    source_map: list[dict]
    diagnostics: Diagnostics


@dataclass(frozen=True)
class RenderedCorpus:
    """Four UTF-8 artifacts in manifest order; diagnostics are kept separately."""

    files: dict[str, bytes]
    books: tuple[RenderedBook, ...]


@dataclass(frozen=True)
class PublishedCorpus:
    output_dir: Path
    status: str
    corpus: RenderedCorpus
    warnings: tuple[str, ...] = ()


def require(condition: Any, code: str, message: str, **context: Any) -> None:
    if not condition:
        raise ExportError(code, message, **context)


def at_pointer(root: Any, pointer: str) -> Any:
    if not pointer:
        return root
    for token in pointer.removeprefix('/').split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        root = root[int(token)] if isinstance(root, list) else root[token]
    return root


def pointer_token(value: Any) -> str:
    return str(value).replace('~', '~0').replace('/', '~1')
