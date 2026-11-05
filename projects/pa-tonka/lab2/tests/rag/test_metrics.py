import pytest

from dnd_rag.contracts import Chunk, ChunkMetadata, ChunkRef, RetrievalHit
from dnd_rag.evaluation.gold import EvidenceFact, EvidenceSpan, GoldQuestion
from dnd_rag.evaluation.metrics import aggregate_metrics, evaluate_question


def span(start, end, file='xphb.md'):
    return EvidenceSpan(
        file=file,
        heading_path=['A'],
        quote='x' * (end - start),
        start_char=start,
        end_char=end,
        line_start=1,
        line_end=1,
        body_sha256='body',
    )


def question(*alternatives):
    return GoldQuestion(
        id='q',
        question='What?',
        reference_answer='Answer',
        answerable=True,
        evidence=[
            EvidenceFact(fact=f'Fact{i}', alternatives=list(a)) for i, a in enumerate(alternatives)
        ],
    )


def ref(id, start, end, file='xphb.md', body='body'):
    return ChunkRef(
        chunk_id=id,
        source_file=file,
        body_sha256=body,
        start_char=start,
        end_char=end,
        line_start=1,
        line_end=1,
        token_count=10,
    )


def hits(refs):
    return [
        RetrievalHit(
            rank=i + 1,
            score=0.5,
            score_kind='cosine',
            chunk=Chunk(
                page_content='x' * (r.end_char - r.start_char),
                metadata=ChunkMetadata(
                    **r.model_dump(),
                    index_id='index',
                    book_id='XPHB',
                    book_title='Book',
                    source_system='fixture',
                    upstream_sha='upstream',
                    sections=[],
                ),
            ),
        )
        for i, r in enumerate(refs)
    ]


def test_partial_evidence_short_list():
    q = question([span(0, 100)], [span(200, 300)])
    manifest = [ref('a', 0, 45), ref('b', 45, 95), ref('c', 95, 100), ref('d', 200, 300)]
    metrics = evaluate_question(q, hits(manifest[:2]), manifest)
    assert metrics.precision[5] == 2 / 5
    assert metrics.recall[5] == 2 / 4
    assert metrics.rr == 1
    assert metrics.evidence_coverage[5] == pytest.approx(0.475)
    assert metrics.raw_tokens[5] == 20


def test_alternatives_do_not_pool():
    q = question([span(0, 100), span(200, 300)])
    refs = [ref('a', 0, 50), ref('b', 250, 300)]
    assert evaluate_question(q, hits(refs), refs).evidence_coverage[5] == 0.5


def test_union_no_double_count_and_facts_equal_weight():
    q = question([span(0, 100)], [span(200, 210)])
    refs = [ref('a', 0, 80), ref('b', 20, 100), ref('c', 200, 205)]
    result = evaluate_question(q, hits(refs), refs)
    assert result.evidence_coverage[5] == 0.75
    assert result.raw_tokens[5] == 30


def test_threshold_empty_and_version():
    q = question([span(0, 100)])
    manifest = [
        ref('half', 50, 150),
        ref('less', 51, 151),
        ref('wrong_version', 0, 100, body='old'),
    ]
    result = evaluate_question(q, hits([manifest[1], manifest[0]]), manifest)
    assert result.relevant_ids == ['half']
    assert result.rr == 0.5
    empty = evaluate_question(q, [], [])
    assert empty.no_relevant_chunks is True and empty.recall[5] == 0
    assert aggregate_metrics([result, empty])['mrr@10'] == 0.25
    assert empty.evidence_coverage[10] == 0


def test_coverage_uses_all_hits_without_relevance_filter():
    q = question([span(0, 100)])
    refs = [ref('a', 51, 151)]
    result = evaluate_question(q, hits(refs), refs)
    assert result.precision[1] == 0
    assert result.evidence_coverage[1] == 0.49
