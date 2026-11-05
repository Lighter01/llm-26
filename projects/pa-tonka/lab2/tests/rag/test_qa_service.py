from types import SimpleNamespace as NS

import pytest

from dnd_rag.config import LLMProfile
from dnd_rag.contracts import RagError, RetrievalResult
from dnd_rag.rag.llm import LLMOutput
from dnd_rag.rag.service import RagService
from tests.rag.fixtures import make_hits


def service(hits=None, *, finish_reason='stop', count=100, usage=100):
    calls = []

    def retrieve(question):
        return RetrievalResult(
            question=question,
            index_id='a' * 64,
            build_id='build1',
            mode='dense',
            hits=make_hits() if hits is None else hits,
            timings_ms={'query_embedding': 1.0, 'search': 2.0, 'total': 3.0},
        )

    def generate(messages, *, max_tokens):
        calls.append((messages, max_tokens))
        return LLMOutput('The supported rule [1]. Unknown [99].', finish_reason, usage, 20)

    llm = NS(count_input_tokens=lambda m: count, generate=generate, is_ready=lambda: True)
    return RagService(NS(retrieve=retrieve), llm, LLMProfile()), calls


def test_empty_retrieval_skips_llm():
    rag, calls = service(hits=[])
    rag.llm.count_input_tokens = lambda m: pytest.fail('No LLM operation on empty retrieval')
    trace = rag.ask('Q?')
    assert trace.result.status == 'no_context' and trace.result.sources == []
    assert trace.result.context.input_tokens is None
    assert trace.result.timings_ms['generation'] is None and trace.result.finish_reason is None
    assert calls == [] and not trace.registry


def test_budget_error_prevents_generation():
    rag, calls = service(count=6401)
    with pytest.raises(RagError) as error:
        rag.ask('Q?')
    assert error.value.code == 'context_budget_exceeded'
    assert calls == []


def test_length_finish_kept_with_real_trace():
    rag, calls = service(finish_reason='length')
    trace = rag.ask('Q?')
    assert len(calls) == 1 and calls[0][1] == 1536
    assert trace.result.answer == trace.raw_answer == 'The supported rule [1]. Unknown [99].'
    assert [s.citation_id for s in trace.result.sources] == [1]
    assert {w.code for w in trace.result.warnings} == {'unknown_citation', 'answer_truncated'}
    assert trace.messages == calls[0][0]
    assert len(trace.registry) == 5


def test_unexpected_token_parity_change_is_error():
    rag, calls = service(usage=101)
    with pytest.raises(RagError) as error:
        rag.ask('Q?')
    assert error.value.code == 'llm_token_mismatch'
    assert len(calls) == 1
