"""Shared stateless retrieval, independent of the answering LLM and transports."""

from time import perf_counter

from dnd_rag.contracts import RagError, RetrievalResult


class Retriever:
    def __init__(self, index, config, encoder, store):
        self.index = index
        self.config = config
        self.encoder = encoder
        self.store = store

    def readiness(self):
        return {
            'index_ready': self.store.is_ready(self.index),
            'query_encoder_ready': self.encoder is not None,
        }

    def retrieve(self, question: str, limit: int | None = None) -> RetrievalResult:
        if not isinstance(question, str) or not question.strip():
            raise RagError('invalid_question', 'Question must be nonempty text')
        if limit is None:
            limit = self.config.retrieval.limit
        if type(limit) is not int or not 1 <= limit <= self.config.retrieval.limit:
            raise RagError('invalid_limit', f'Limit must be 1..{self.config.retrieval.limit}')
        started = perf_counter()
        vector = self.encoder.encode(question)
        encoded = perf_counter()
        hits = self.store.search(self.index, vector, question, self.config, limit)
        searched = perf_counter()
        return RetrievalResult(
            question=question,
            index_id=self.index.index_id,
            build_id=self.index.build_id,
            mode=self.config.retrieval.mode,
            hits=hits,
            timings_ms={
                'query_embedding': (encoded - started) * 1000,
                'search': (searched - encoded) * 1000,
                'total': (searched - started) * 1000,
            },
        )
