import pytest

from dnd_rag.config import LLMProfile
from dnd_rag.contracts import RagError
from dnd_rag.rag.context import pack_context
from tests.rag.fixtures import make_hits


def test_drop_whole_tail_and_recount():
    hits = make_hits(6)
    calls = []
    question = '  How does the rule work?\n'

    def counter(messages):
        n = messages[1].content.count('SOURCE [')
        calls.append(n)
        assert question in messages[1].content
        return 6500 if n == 5 else 6300

    packed = pack_context(question, hits, LLMProfile(), counter)
    assert calls == [5, 4]
    assert list(packed.registry) == [1, 2, 3, 4]
    assert [c.metadata.chunk_id for c in packed.registry.values()] == [
        h.chunk.metadata.chunk_id for h in hits[:4]
    ]
    assert packed.dropped_chunk_ids == [hits[4].chunk.metadata.chunk_id]
    assert packed.input_tokens == 6300
    for h in hits[:4]:
        assert h.chunk.page_content in packed.messages[1].content
    assert hits[5].chunk.page_content not in packed.messages[1].content
    with pytest.raises(TypeError):
        packed.registry[1] = hits[0].chunk


def test_exact_limit_and_no_partial_chunk():
    hits = make_hits()
    assert pack_context('Q?', hits, LLMProfile(), lambda m: 6400).input_tokens == 6400
    for limit in (6401, 20000):
        with pytest.raises(RagError) as error:
            pack_context('Q?', hits, LLMProfile(), lambda m: limit)
        assert error.value.code == 'context_budget_exceeded'


def test_counter_uses_full_chat_messages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hits = make_hits(1)
    seen = []

    def counter(messages):
        seen.extend(messages)
        assert messages[0].type == 'system' and 'English' in messages[0].content
        assert 'AVAILABLE SOURCES: [1]' in messages[1].content
        assert 'Book: Player' in messages[1].content
        return 600

    packed = pack_context('Q?', hits, LLMProfile(), counter)
    assert tuple(seen) == packed.messages
