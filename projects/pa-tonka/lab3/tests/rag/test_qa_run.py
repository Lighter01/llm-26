import csv
import json
from types import SimpleNamespace as NS

import pytest
from langchain_core.messages import convert_to_openai_messages

from dnd_rag.config import load_settings
from dnd_rag.contracts import EnsureResult, RagError, ReadyIndex, StageEvent
from dnd_rag.evaluation import qa_run
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.rag.llm import LLMOutput
from dnd_rag.rag.service import RagService
from tests.rag.fixtures import baseline_data, make_corpus, make_gold, make_hits, write_yaml


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    gold = make_gold(tmp_path / 'gold', corpus)
    data = baseline_data()
    data['corpus']['directory'] = str(tmp_path / 'corpus')
    data['evaluation'] = {'questions': str(gold)}
    config = write_yaml(tmp_path / 'config.yaml', data)
    profile = write_yaml(tmp_path / 'llm.yaml', {})
    state = NS(
        retrieval_calls=0, generation_calls=0, ensure_calls=0, fail_at=None, traces=[], closed=False
    )
    index = ReadyIndex(
        index_id='a' * 64,
        collection='rag_fixture',
        build_spec={},
        build_id='fixture-build',
        expected_points=6,
        build_provenance={},
    )

    def ensure(*args, **kwargs):
        state.ensure_calls += 1
        stage = StageEvent(name='embedding', status='reused', elapsed_ms=None)
        kwargs['on_stage'](stage)
        return EnsureResult(index=index, action='reused', reason='Fixture ready', stages=[stage])

    def search(*args):
        state.retrieval_calls += 1
        if state.retrieval_calls == state.fail_at:
            raise RagError('qdrant_unavailable', 'Fixture dependency failure')
        return make_hits(6)

    def generate(messages, *, max_tokens):
        state.generation_calls += 1
        assert max_tokens == 1536
        return LLMOutput(
            'Supported claims [2][4]; unavailable citation [99].',
            'stop',
            100,
            12,
            {'prompt_ms': 1.0},
            {'fixture': True},
        )

    def close():
        state.closed = True

    llm = NS(
        count_input_tokens=lambda m: 6500 if m[1].content.count('SOURCE [') == 5 else 100,
        generate=generate,
        close=close,
        server_provenance={'template_sha256': 'f' * 64},
    )

    class RecordingService(RagService):
        def ask(self, question):
            trace = super().ask(question)
            state.traces.append(trace)
            return trace

    monkeypatch.setattr(qa_run, 'ensure_index', ensure)
    monkeypatch.setattr(qa_run, 'QueryEncoder', lambda *a: NS(encode=lambda q: [1.0] * 768))
    monkeypatch.setattr(qa_run, 'QdrantStore', lambda *a: NS(search=search))
    monkeypatch.setattr(qa_run, 'start_llama', lambda *a: llm)
    monkeypatch.setattr(qa_run, 'RagService', RecordingService)
    return config, profile, load_settings(tmp_path), state


def run(inputs, name='qa', **kwargs):
    config, profile, settings, _ = inputs
    return qa_run.run_qa_evaluation(config, profile, name, settings, **kwargs)


def test_saved_trace_is_actual_generation_context(inputs):
    output = run(inputs)
    state = inputs[-1]
    rows = [json.loads(line) for line in (output / 'qa_answers.jsonl').read_text().splitlines()]
    assert len(rows) == state.retrieval_calls == state.generation_calls == 20
    row, trace = rows[0], state.traces[0]
    assert row['messages'] == convert_to_openai_messages(list(trace.messages))
    assert row['citation_registry'] == {
        str(i): c.model_dump(mode='json') for i, c in trace.registry.items()
    }
    assert row['context'] == trace.result.context.model_dump(mode='json')
    assert row['retrieval'] == trace.retrieval.model_dump(mode='json')
    assert len(row['citation_registry']) == 4 and len(row['context']['dropped_chunk_ids']) == 1
    assert row['used_citation_ids'] == [2, 4] and row['unknown_citation_ids'] == [99]
    assert row['raw_answer'] == trace.raw_answer and row['usage']['output_tokens'] == 12
    assert row['structural_diagnostics']['budget_valid'] is True
    assert (output / 'llm_profile.yaml').read_bytes() == inputs[1].read_bytes()
    assert (output / 'prompts/system.txt').read_text() in row['messages'][0]['content']
    metadata = json.loads((output / 'run.json').read_text())
    assert metadata['run_type'] == 'qa' and metadata['status'] == 'completed'
    assert metadata['stages']['embedding']['elapsed_ms'] is None
    assert state.closed


def test_review_initially_unjudged(inputs):
    output = run(inputs)
    with (output / 'qa_review.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 20
    semantic = [
        'correctness',
        'correctness_reason',
        'completeness',
        'completeness_reason',
        'citation_support',
        'citation_support_reason',
        'missing_facts',
        'uncited_claims',
        'reviewer',
        'review_method',
        'reviewed_at',
        'review_version',
    ]
    assert all(row['review_status'] == 'not_reviewed' for row in rows)
    assert all(row[field] == '' for row in rows for field in semantic)
    assert rows[0]['used_citation_ids'] == '[2,4]'  # observations do not become semantic grades


@pytest.mark.parametrize('include_insufficient,count', [(False, 20), (True, 23)])
def test_insufficient_separate(inputs, include_insufficient, count):
    output = run(inputs, include_insufficient=include_insufficient)
    state = inputs[-1]
    summary = json.loads((output / 'qa_summary.json').read_text())
    assert state.retrieval_calls == count
    assert summary['primary']['expected'] == summary['primary']['completed'] == 20
    assert summary['insufficient']['expected'] == summary['insufficient']['completed'] == count - 20
    assert summary['primary']['semantic_review_status'] == 'not_reviewed'
    assert 'correctness' not in summary['primary']


def test_qa_failure_retains_run(inputs):
    config, profile, settings, state = inputs
    state.fail_at = 2
    with pytest.raises(RagError, match='Fixture dependency failure'):
        run(inputs)
    output = settings.project_root / 'results/qa'
    metadata = json.loads((output / 'run.json').read_text())
    summary = json.loads((output / 'qa_summary.json').read_text())
    rows = [json.loads(line) for line in (output / 'qa_answers.jsonl').read_text().splitlines()]
    assert metadata['status'] == summary['status'] == 'failed'
    assert summary['primary']['completed'] == 1 and summary['primary']['failed'] == 1
    assert len(rows) == 2 and rows[1]['error']['code'] == 'qdrant_unavailable'
    assert state.retrieval_calls == 2 and state.generation_calls == 1 and state.closed


def test_existing_run_preserves_reviewer_edits(inputs):
    output = run(inputs)
    review = output / 'qa_review.csv'
    review.write_text(review.read_text().replace('not_reviewed', 'needs_review', 1))
    before = review.read_bytes()
    with pytest.raises(RagError, match='already exists'):
        run(inputs)
    assert review.read_bytes() == before and inputs[-1].ensure_calls == 1
