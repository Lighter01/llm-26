"""Source-aligned relevance, union evidence coverage, and macro aggregation."""

from statistics import mean

from dnd_rag.contracts import Contract, RagError


class QuestionMetrics(Contract):
    question_id: str
    relevant_ids: list[str]
    no_relevant_chunks: bool
    rr: float
    precision: dict[int, float]
    recall: dict[int, float]
    evidence_coverage: dict[int, float]
    returned_count: dict[int, int]
    raw_tokens: dict[int, int]
    coverage_details: dict[int, list[dict]]


def _intersection(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def _relevant(ref, span):
    if ref.source_file != span.file or ref.body_sha256 != span.body_sha256:
        return False
    shortest = min(ref.end_char - ref.start_char, span.end_char - span.start_char)
    return (
        shortest > 0
        and _intersection((ref.start_char, ref.end_char), (span.start_char, span.end_char))
        / shortest
        >= 0.5
    )


def _unique_top(hits, k):
    seen = set()
    selected = []
    for hit in hits[:k]:
        id = hit.chunk.metadata.chunk_id
        if id not in seen:
            seen.add(id)
            selected.append(hit)
    return selected


def _unions(hits):
    groups = {}
    for hit in hits:
        meta = hit.chunk.metadata
        groups.setdefault((meta.source_file, meta.body_sha256), []).append(
            (meta.start_char, meta.end_char)
        )
    result = {}
    for key, spans in groups.items():
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        result[key] = merged
    return result


def _coverage(question, selected):
    unions = _unions(selected)
    details = []
    for fact in question.evidence:
        alternatives = []
        for span in fact.alternatives:
            covered = sum(
                _intersection((span.start_char, span.end_char), u)
                for u in unions.get((span.file, span.body_sha256), [])
            )
            alternatives.append(
                {
                    'file': span.file,
                    'start_char': span.start_char,
                    'end_char': span.end_char,
                    'coverage': covered / (span.end_char - span.start_char),
                }
            )
        details.append(
            {
                'fact': fact.fact,
                'coverage': max(a['coverage'] for a in alternatives),
                'alternatives': alternatives,
            }
        )
    return mean(f['coverage'] for f in details), details


def evaluate_question(question, hits, manifest, *, ks=(1, 5, 10), mrr_k=10) -> QuestionMetrics:
    if not question.answerable or not question.evidence:
        raise RagError(
            'invalid_evaluation', 'Insufficient questions are separate from retrieval metrics'
        )
    alternatives = [a for fact in question.evidence for a in fact.alternatives]
    relevant = {r.chunk_id for r in manifest if any(_relevant(r, a) for a in alternatives)}
    rr = next(
        (
            1 / rank
            for rank, hit in enumerate(hits[:mrr_k], 1)
            if hit.chunk.metadata.chunk_id in relevant
        ),
        0.0,
    )
    precision, recall, coverage, counts, tokens, details = {}, {}, {}, {}, {}, {}
    for k in ks:
        selected = _unique_top(hits, k)
        found = {h.chunk.metadata.chunk_id for h in selected} & relevant
        precision[k] = len(found) / k
        recall[k] = len(found) / len(relevant) if relevant else 0.0
        coverage[k], details[k] = _coverage(question, selected)
        counts[k] = len(selected)
        tokens[k] = sum(h.chunk.metadata.token_count for h in selected)
    return QuestionMetrics(
        question_id=question.id,
        relevant_ids=sorted(relevant),
        no_relevant_chunks=not relevant,
        rr=rr,
        precision=precision,
        recall=recall,
        evidence_coverage=coverage,
        returned_count=counts,
        raw_tokens=tokens,
        coverage_details=details,
    )


def aggregate_metrics(rows):
    if not rows:
        raise RagError('invalid_evaluation', 'Cannot aggregate an empty evaluation')
    result = {'mrr@10': mean(r.rr for r in rows)}
    for field in ('precision', 'recall', 'evidence_coverage'):
        for k in rows[0].precision:
            result[f'{field}@{k}'] = mean(getattr(r, field)[k] for r in rows)
    return result
