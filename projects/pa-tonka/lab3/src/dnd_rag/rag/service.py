"""Stateless grounded QA; one retrieval and at most one LLM generation per request."""

from dataclasses import dataclass
from time import perf_counter
from types import MappingProxyType
from typing import Mapping

from langchain_core.messages import BaseMessage

from dnd_rag.contracts import AskContext, AskResult, Chunk, RagError, RetrievalResult, Warning
from dnd_rag.rag.citations import extract_citations
from dnd_rag.rag.context import pack_context


@dataclass(frozen=True)
class AskTrace:
    result: AskResult
    retrieval: RetrievalResult
    messages: tuple[BaseMessage, ...]
    registry: Mapping[int, Chunk]
    raw_answer: str | None
    used_citation_ids: list[int]
    unknown_citation_ids: list[int]
    usage: dict | None
    llm_timings: dict
    llm_response: dict


class RagService:
    def __init__(self, retriever, llm, profile):
        self.retriever = retriever
        self.llm = llm
        self.profile = profile

    def is_ready(self):
        return self.llm.is_ready()

    def _context_info(self, chunk_ids, dropped_ids, input_tokens):
        return AskContext(
            chunk_ids=chunk_ids,
            dropped_chunk_ids=dropped_ids,
            input_tokens=input_tokens,
            context_size=self.profile.context_size,
            max_output_tokens=self.profile.max_output_tokens,
            safety_margin=self.profile.safety_margin,
        )

    def ask(self, question) -> AskTrace:
        started = perf_counter()
        retrieval = self.retriever.retrieve(question)
        timings = {
            'query_embedding': retrieval.timings_ms['query_embedding'],
            'search': retrieval.timings_ms['search'],
            'context': 0.0,
            'generation': None,
            'postprocess': 0.0,
            'total': 0.0,
        }
        if not retrieval.hits:
            timings['total'] = (perf_counter() - started) * 1000
            result = AskResult(
                status='no_context',
                question=question,
                answer='No passages were retrieved for this question.',
                sources=[],
                warnings=[],
                index_id=retrieval.index_id,
                build_id=retrieval.build_id,
                context=self._context_info([], [], None),
                finish_reason=None,
                timings_ms=timings,
            )
            return AskTrace(result, retrieval, (), MappingProxyType({}), None, [], [], None, {}, {})
        before = perf_counter()
        packed = pack_context(question, retrieval.hits, self.profile, self.llm.count_input_tokens)
        timings['context'] = (perf_counter() - before) * 1000
        before = perf_counter()
        output = self.llm.generate(packed.messages, max_tokens=self.profile.max_output_tokens)
        timings['generation'] = (perf_counter() - before) * 1000
        if output.input_tokens is not None and output.input_tokens != packed.input_tokens:
            raise RagError(
                'llm_token_mismatch',
                'LLM usage differs from the counted chat prompt',
                {
                    'counted_input_tokens': packed.input_tokens,
                    'actual_input_tokens': output.input_tokens,
                },
            )
        before = perf_counter()
        citations = extract_citations(output.text, packed.registry)
        warnings = list(citations.warnings)
        if output.finish_reason == 'length':
            warnings.append(
                Warning(
                    code='answer_truncated',
                    message='The model reached the output limit; the answer may be incomplete.',
                )
            )
        timings['postprocess'] = (perf_counter() - before) * 1000
        timings['total'] = (perf_counter() - started) * 1000
        result = AskResult(
            status='answered',
            question=question,
            answer=output.text,
            sources=citations.sources,
            warnings=warnings,
            index_id=retrieval.index_id,
            build_id=retrieval.build_id,
            context=self._context_info(
                [c.metadata.chunk_id for c in packed.registry.values()],
                packed.dropped_chunk_ids,
                packed.input_tokens,
            ),
            finish_reason=output.finish_reason,
            timings_ms=timings,
        )
        return AskTrace(
            result,
            retrieval,
            packed.messages,
            packed.registry,
            output.text,
            citations.used_ids,
            citations.unknown_ids,
            {'input_tokens': output.input_tokens, 'output_tokens': output.output_tokens},
            output.server_timings,
            output.raw_response,
        )
