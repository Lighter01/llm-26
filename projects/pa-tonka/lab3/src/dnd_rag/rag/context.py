"""Pack complete raw passages under an exact full-chat token budget."""

from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType
from typing import Mapping

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from dnd_rag.contracts import Chunk, RagError


@dataclass(frozen=True)
class PackedContext:
    messages: tuple[BaseMessage, ...]
    registry: Mapping[int, Chunk]
    input_tokens: int
    dropped_chunk_ids: list[str]


def _messages(question, registry):
    system = files('dnd_rag.rag').joinpath('prompts/system.txt').read_text(encoding='utf-8')
    available = ', '.join(f'[{id}]' for id in registry)
    blocks = []
    for id, chunk in registry.items():
        paths = list(
            dict.fromkeys(' > '.join(section.heading_path) for section in chunk.metadata.sections)
        )
        sections = '; '.join(paths) or '(unmapped)'
        blocks.append(
            f'SOURCE [{id}]\nBook: {chunk.metadata.book_title}\nSections: {sections}\n'
            f'Text:\n<passage>\n{chunk.page_content}\n</passage>'
        )
    content = f'QUESTION:\n{question}\n\nAVAILABLE SOURCES: {available}\n\n' + '\n\n'.join(blocks)
    return (SystemMessage(content=system), HumanMessage(content=content))


def pack_context(question, hits, profile, count_tokens) -> PackedContext:
    candidates = list(hits[: profile.max_context_chunks])
    selected = list(candidates)
    budget = profile.context_size - profile.max_output_tokens - profile.safety_margin
    while True:
        registry = {i: hit.chunk for i, hit in enumerate(selected, 1)}
        messages = _messages(question, registry)
        tokens = count_tokens(messages)
        if tokens <= budget:
            return PackedContext(
                messages,
                MappingProxyType(registry),
                tokens,
                [hit.chunk.metadata.chunk_id for hit in candidates[len(selected) :]],
            )
        if len(selected) <= 1:
            raise RagError(
                'context_budget_exceeded',
                'The question and first passage exceed the context budget; shorten your question.',
                {'input_tokens': tokens, 'max_input_tokens': budget},
            )
        selected.pop()
