"""Auditable QA runs and unjudged review worksheets from the actual AskTrace."""

import json
import resource
import shutil
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from time import perf_counter

import yaml
from langchain_core.messages import convert_to_openai_messages

from dnd_rag.config import load_experiment, load_llm_profile, resolve_path
from dnd_rag.contracts import RagError, StageEvent
from dnd_rag.evaluation.artifacts import (
    RunWriter,
    code_provenance,
    index_metadata,
    record_elapsed,
    resolved_config,
    summary_statistics,
)
from dnd_rag.evaluation.gold import load_gold
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.embedding import QueryEncoder
from dnd_rag.indexing.identity import digest
from dnd_rag.indexing.store import QdrantStore
from dnd_rag.rag.service import RagService
from dnd_rag.retrieval import Retriever
from dnd_rag.runtime.application import ensure_index
from dnd_rag.runtime.llama import start_llama
from dnd_rag.runtime.processes import RuntimeSession

SEMANTIC_FIELDS = [
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
REVIEW_FIELDS = [
    'question_id',
    'question',
    'category',
    'reference_answer',
    'answer',
    'status',
    'used_citation_ids',
    'unknown_citation_ids',
    'input_tokens',
    'output_tokens',
    'finish_reason',
    'warnings',
    'total_ms',
    'error',
    *SEMANTIC_FIELDS,
    'review_status',
]


def _structural(trace):
    context, result = trace.result.context, trace.result
    count = context.input_tokens
    actual = (trace.usage or {}).get('input_tokens')
    return {
        'budget_valid': count is None
        or count + context.max_output_tokens + context.safety_margin <= context.context_size,
        'usage_matches_count': actual == count if actual is not None else None,
        'registry_matches_context': [c.metadata.chunk_id for c in trace.registry.values()]
        == context.chunk_ids,
        'source_ids_match_used_ids': [s.citation_id for s in result.sources]
        == trace.used_citation_ids,
        'unknown_citation_ids': trace.unknown_citation_ids,
        'has_valid_citations': bool(trace.used_citation_ids),
        'output_limit_reached': result.finish_reason == 'length',
    }


def _answer_row(question, trace, cold):
    return {
        'question_id': question.id,
        'question': question.question,
        'category': 'primary' if question.answerable else 'insufficient',
        'answerable': question.answerable,
        'reference_answer': question.reference_answer,
        'cold_first_query': cold,
        'raw_answer': trace.raw_answer,
        'result': trace.result.model_dump(mode='json'),
        'retrieval': trace.retrieval.model_dump(mode='json'),
        'context': trace.result.context.model_dump(mode='json'),
        'messages': convert_to_openai_messages(list(trace.messages)),
        'citation_registry': {str(i): c.model_dump(mode='json') for i, c in trace.registry.items()},
        'used_citation_ids': trace.used_citation_ids,
        'unknown_citation_ids': trace.unknown_citation_ids,
        'usage': trace.usage,
        'finish_reason': trace.result.finish_reason,
        'warnings': [w.model_dump(mode='json') for w in trace.result.warnings],
        'timings_ms': trace.result.timings_ms,
        'llm_timings': trace.llm_timings,
        'llm_response': trace.llm_response,
        'structural_diagnostics': _structural(trace),
        'error': None,
    }


def _review_row(row):
    result = row.get('result', {})
    usage = row.get('usage') or {}

    def compact(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

    return {
        'question_id': row['question_id'],
        'question': row['question'],
        'category': row['category'],
        'reference_answer': row['reference_answer'],
        'answer': result.get('answer', ''),
        'status': result.get('status', 'error'),
        'used_citation_ids': compact(row.get('used_citation_ids', [])),
        'unknown_citation_ids': compact(row.get('unknown_citation_ids', [])),
        'input_tokens': usage.get('input_tokens'),
        'output_tokens': usage.get('output_tokens'),
        'finish_reason': row.get('finish_reason'),
        'warnings': compact(row.get('warnings', [])),
        'total_ms': row.get('timings_ms', {}).get('total'),
        'error': compact(row['error']) if row['error'] else '',
        **dict.fromkeys(SEMANTIC_FIELDS, ''),
        'review_status': 'not_reviewed',
    }


def _category_summary(rows, category, expected):
    selected = [r for r in rows if r['category'] == category]
    successful = [r for r in selected if not r['error']]
    stages = ('query_embedding', 'search', 'context', 'generation', 'postprocess', 'total')
    return {
        'expected': expected,
        'completed': len(successful),
        'failed': len(selected) - len(successful),
        'unattempted': expected - len(selected),
        'semantic_review_status': 'not_reviewed',
        'no_context': sum(r['result']['status'] == 'no_context' for r in successful),
        'structural_diagnostics': {
            'unknown_citation_answers': sum(bool(r['unknown_citation_ids']) for r in successful),
            'without_valid_citations': sum(not r['used_citation_ids'] for r in successful),
            'output_limit_reached': sum(r['finish_reason'] == 'length' for r in successful),
            'budget_violations': sum(
                not r['structural_diagnostics']['budget_valid'] for r in successful
            ),
        },
        'timings_ms': {
            stage: {
                'all': summary_statistics(
                    [
                        r['timings_ms'][stage]
                        for r in successful
                        if r['timings_ms'][stage] is not None
                    ]
                ),
                'warm': summary_statistics(
                    [
                        r['timings_ms'][stage]
                        for r in successful
                        if not r['cold_first_query'] and r['timings_ms'][stage] is not None
                    ]
                ),
            }
            for stage in stages
        },
    }


def _write_summary(writer, rows, include_insufficient, status):
    writer.write_json(
        'qa_summary.json',
        {
            'schema_version': 1,
            'status': status,
            'primary': _category_summary(rows, 'primary', 20),
            'insufficient': _category_summary(
                rows, 'insufficient', 3 if include_insufficient else 0
            ),
            'semantic_review_status': 'not_reviewed',
            'structural_diagnostics_are_not_semantic_grades': True,
        },
    )


def _evaluate_questions(writer, questions, rag, rows, include_insufficient):
    export_ms = 0.0
    for position, question in enumerate(questions):
        writer.update_metadata({'current_stage': 'qa', 'current_question': question.id})
        try:
            trace = rag.ask(question.question)
        except Exception as exc:
            error = exc if isinstance(exc, RagError) else RagError('qa_failed', str(exc))
            row = {
                'question_id': question.id,
                'question': question.question,
                'category': 'primary' if question.answerable else 'insufficient',
                'reference_answer': question.reference_answer,
                'error': error.as_dict(),
            }
            rows.append(row)
            writer.append_jsonl('qa_answers.jsonl', row)
            writer.append_csv('qa_review.csv', REVIEW_FIELDS, _review_row(row))
            raise error from exc
        before = perf_counter()
        row = _answer_row(question, trace, position == 0)
        rows.append(row)
        writer.append_jsonl('qa_answers.jsonl', row)
        writer.append_csv('qa_review.csv', REVIEW_FIELDS, _review_row(row))
        _write_summary(writer, rows, include_insufficient, 'running')
        export_ms += (perf_counter() - before) * 1000
    writer.record_stage(StageEvent(name='qa_export', status='executed', elapsed_ms=export_ms))
    for name in ('query_embedding', 'search', 'context', 'generation', 'postprocess'):
        values = [r['timings_ms'][name] for r in rows if r['timings_ms'][name] is not None]
        writer.record_stage(
            StageEvent(
                name=name,
                status='executed' if values else 'skipped',
                elapsed_ms=sum(values) if values else None,
            )
        )


def _execute(writer, config, profile, settings, session, rows, include_insufficient):
    writer.update_metadata({'current_stage': 'gold_validation'})
    before = perf_counter()
    corpus = load_corpus(config.corpus.directory)
    gold = load_gold(
        config.evaluation.questions,
        corpus,
        config.evaluation.questions.parent / 'validation_report.json',
    )
    record_elapsed(writer, 'gold_validation', before)
    writer.update_metadata(
        {
            'corpus': corpus.passport(),
            'gold_sha256': gold.file_sha256,
            'raw_input_sha256': gold.raw_input_sha256,
            'provenance': code_provenance(settings.project_root),
            'conditions': {
                'query_device': 'cpu',
                'query_dtype': 'float32',
                'cache_policy': 'normal HF cache; first QA marked separately; no prompt cache',
            },
            'current_stage': 'index_preparation',
        }
    )
    ensured = ensure_index(config, settings, session, on_stage=writer.record_stage)
    writer.update_metadata(index_metadata(ensured))
    writer.update_metadata({'current_stage': 'query_model_load'})
    before = perf_counter()
    encoder = QueryEncoder(config.embedding, settings)
    record_elapsed(writer, 'query_model_load', before)
    retriever = Retriever(ensured.index, config, encoder, QdrantStore(settings))
    writer.update_metadata({'current_stage': 'llm_startup'})
    before = perf_counter()
    llm = start_llama(settings, profile, session)
    try:
        record_elapsed(writer, 'llm_startup', before)
        writer.update_metadata({'llm_server': llm.server_provenance})
        questions = gold.answerable + (gold.insufficient if include_insufficient else [])
        _evaluate_questions(
            writer, questions, RagService(retriever, llm, profile), rows, include_insufficient
        )
    finally:
        llm.close()
    writer.update_metadata(
        {
            'current_stage': 'completed',
            'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        }
    )


def _snapshots(writer, path, profile_path, config, profile):
    writer.snapshot(path, resolved_config(config), config.evaluation.questions)
    shutil.copyfile(profile_path, writer.path / 'llm_profile.yaml')
    (writer.path / 'resolved_llm_profile.yaml').write_text(
        yaml.safe_dump(profile.model_dump(mode='json'), sort_keys=False), encoding='utf-8'
    )
    prompts = writer.path / 'prompts'
    prompts.mkdir()
    resources = files('dnd_rag.rag')
    system = resources.joinpath('prompts/system.txt').read_bytes()
    builder = resources.joinpath('context.py').read_bytes()
    (prompts / 'system.txt').write_bytes(system)
    # The source snapshot fixes the dynamic wrappers too; each row saves the exact messages.
    (prompts / 'context_builder.py').write_bytes(builder)
    writer.update_metadata(
        {
            'prompt_snapshots': {
                'system_sha256': sha256(system).hexdigest(),
                'context_builder_sha256': sha256(builder).hexdigest(),
            }
        }
    )


def run_qa_evaluation(
    config_path: Path,
    profile_path: Path,
    name: str,
    settings,
    *,
    include_insufficient: bool = False,
) -> Path:
    path = resolve_path(config_path, settings.project_root)
    profile_path = resolve_path(profile_path, settings.project_root)
    config = load_experiment(path, project_root=settings.project_root)
    profile = load_llm_profile(profile_path)
    with RuntimeSession(settings.project_root) as session:
        writer = RunWriter.reserve(settings.project_root, name, 'qa')
        rows = []
        try:
            _snapshots(writer, path, profile_path, config, profile)
            writer.update_metadata(
                {
                    'cli': {'command': 'evaluate-qa', 'include_insufficient': include_insufficient},
                    'config_id': digest(resolved_config(config)),
                    'config_sha256': sha256(path.read_bytes()).hexdigest(),
                    'llm_profile_id': digest(profile.model_dump(mode='json')),
                    'llm_profile_sha256': sha256(profile_path.read_bytes()).hexdigest(),
                }
            )
            (writer.path / 'qa_answers.jsonl').touch()
            writer.append_csv('qa_review.csv', REVIEW_FIELDS, None)
            _write_summary(writer, rows, include_insufficient, 'running')
            _execute(writer, config, profile, settings, session, rows, include_insufficient)
            _write_summary(writer, rows, include_insufficient, 'completed')
            writer.finish('completed')
        except BaseException as exc:
            error = (
                exc
                if isinstance(exc, RagError)
                else RagError(
                    'interrupted' if isinstance(exc, KeyboardInterrupt) else 'qa_failed', str(exc)
                )
            )
            _write_summary(writer, rows, include_insufficient, 'failed')
            writer.finish('failed', error=error)
            if isinstance(exc, KeyboardInterrupt):
                raise
            raise error from exc
    return writer.path
