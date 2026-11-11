"""Full retrieval experiments; saved raw hits support offline metric recomputation."""

import json
import resource
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from dnd_rag.config import load_experiment, resolve_path
from dnd_rag.contracts import ChunkRef, RagError, RetrievalHit, StageEvent
from dnd_rag.evaluation.artifacts import (
    RunWriter,
    code_provenance,
    index_metadata,
    record_elapsed,
    resolved_config,
    summary_statistics,
)
from dnd_rag.evaluation.gold import GoldDocument, load_gold
from dnd_rag.evaluation.metrics import aggregate_metrics, evaluate_question
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.embedding import QueryEncoder
from dnd_rag.indexing.identity import digest
from dnd_rag.indexing.store import QdrantStore
from dnd_rag.retrieval import Retriever
from dnd_rag.runtime.application import ensure_index
from dnd_rag.runtime.processes import RuntimeSession


def _evaluate_questions(writer, gold, manifest, retriever, config):
    rows, query_times, search_times, total_times = [], [], [], []
    evaluation_ms = 0.0
    relevance = {}
    for i, question in enumerate(gold.answerable):
        writer.update_metadata({'current_stage': 'retrieval', 'current_question': question.id})
        try:
            retrieval = retriever.retrieve(question.question)
        except Exception as exc:
            error = exc if isinstance(exc, RagError) else RagError('retrieval_failed', str(exc))
            writer.append_jsonl(
                'per_question.jsonl',
                {
                    'question_id': question.id,
                    'question': question.question,
                    'error': error.as_dict(),
                },
            )
            raise error from exc
        before = perf_counter()
        metrics = evaluate_question(
            question,
            retrieval.hits,
            manifest,
            ks=config.evaluation.k,
            mrr_k=config.evaluation.mrr_k,
        )
        rows.append(metrics)
        relevance[question.id] = {
            'relevant_ids': metrics.relevant_ids,
            'no_relevant_chunks': metrics.no_relevant_chunks,
        }
        writer.append_jsonl(
            'per_question.jsonl',
            {
                'question_id': question.id,
                'question': question.question,
                'cold_first_query': i == 0,
                'retrieval': retrieval.model_dump(mode='json'),
                'metrics': metrics.model_dump(mode='json'),
                'error': None,
            },
        )
        evaluation_ms += (perf_counter() - before) * 1000
        query_times.append(retrieval.timings_ms['query_embedding'])
        search_times.append(retrieval.timings_ms['search'])
        total_times.append(retrieval.timings_ms['total'])
    before = perf_counter()
    writer.write_json(
        'relevance.json',
        {
            'schema_version': 1,
            'threshold': 0.5,
            'formula': 'intersection/min(chunk_length,evidence_length) >= 0.5, same file/body',
            'questions': relevance,
        },
    )
    summary = {
        'schema_version': 1,
        'question_count': len(rows),
        'error_count': 0,
        'no_relevant_chunks': sum(r.no_relevant_chunks for r in rows),
        'k': config.evaluation.k,
        'mrr_k': config.evaluation.mrr_k,
        'metrics': aggregate_metrics(rows),
        'timings_ms': {
            name: {
                'all': summary_statistics(values),
                'warm': summary_statistics(values[1:]) if len(values) > 1 else None,
                'first_query': values[0],
                'individual': values,
            }
            for name, values in [
                ('query_embedding', query_times),
                ('search', search_times),
                ('retrieval', total_times),
            ]
        },
        'volume': {
            f'@{k}': {
                'returned_count': summary_statistics([r.returned_count[k] for r in rows]),
                'raw_tokens': summary_statistics([r.raw_tokens[k] for r in rows]),
            }
            for k in config.evaluation.k
        },
    }
    writer.write_json('metrics.json', summary)
    evaluation_ms += (perf_counter() - before) * 1000
    writer.record_stage(
        StageEvent(name='evaluation_export', status='executed', elapsed_ms=evaluation_ms)
    )
    for name, values in [('query_embedding', query_times), ('search', search_times)]:
        writer.record_stage(
            StageEvent(
                name=name,
                status='executed',
                elapsed_ms=sum(values),
                details={'aggregation': 'sum of sequential question timings'},
            )
        )


def _execute(writer, config, settings, session, rebuild):
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
            'metrics_definition_version': 1,
            'conditions': {
                'query_device': 'cpu',
                'query_dtype': 'float32',
                'cache_policy': 'normal HF cache; downloads included in model-load timings; first encode marked separately',
            },
        }
    )
    writer.update_metadata({'current_stage': 'index_preparation'})
    ensured = ensure_index(config, settings, session, rebuild=rebuild, on_stage=writer.record_stage)
    index = ensured.index
    writer.update_metadata(index_metadata(ensured))
    before = perf_counter()
    writer.update_metadata({'current_stage': 'manifest_export'})
    store = QdrantStore(settings)
    manifest = store.manifest(index)
    if len(manifest) != index.expected_points or len({r.chunk_id for r in manifest}) != len(
        manifest
    ):
        raise RagError('index_incomplete', 'Manifest count/unique IDs disagree with ready passport')
    for ref in manifest:
        writer.append_jsonl('chunks_manifest.jsonl', ref.model_dump(mode='json'))
    record_elapsed(writer, 'manifest_export', before)
    before = perf_counter()
    writer.update_metadata({'current_stage': 'query_model_load'})
    encoder = QueryEncoder(config.embedding, settings)
    record_elapsed(writer, 'query_model_load', before)
    retriever = Retriever(index, config, encoder, store)
    _evaluate_questions(writer, gold, manifest, retriever, config)
    writer.update_metadata(
        {
            'current_stage': 'completed',
            'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        }
    )


def run_retrieval_experiment(
    config_path: Path, name: str, settings, *, rebuild=False, selection=None
) -> Path:
    path = resolve_path(config_path, settings.project_root)
    config = load_experiment(path, project_root=settings.project_root)
    with RuntimeSession(settings.project_root) as session:
        writer = RunWriter.reserve(settings.project_root, name, 'retrieval')
        try:
            writer.snapshot(path, resolved_config(config), config.evaluation.questions)
            writer.update_metadata(
                {
                    'cli': {'command': 'experiment', 'rebuild': rebuild},
                    'config_id': digest(resolved_config(config)),
                    'config_sha256': sha256(path.read_bytes()).hexdigest(),
                    'group': selection.group if selection else None,
                    'reference_run': selection.reference_run if selection else None,
                    'changed_parameters': selection.changed_parameters if selection else [],
                    'selection_reason': selection.selection_reason if selection else None,
                }
            )
            _execute(writer, config, settings, session, rebuild)
            writer.finish('completed')
        except BaseException as exc:
            error = (
                exc
                if isinstance(exc, RagError)
                else RagError(
                    'interrupted' if isinstance(exc, KeyboardInterrupt) else 'experiment_failed',
                    str(exc),
                )
            )
            writer.finish('failed', error=error)
            if isinstance(exc, KeyboardInterrupt):
                raise
            raise error from exc
    return writer.path


def recompute_saved_metrics(run_path: Path):
    """Re-evaluate completed raw artifacts with no corpus, Qdrant or model access."""
    metadata = json.loads((run_path / 'run.json').read_text())
    if metadata['status'] != 'completed':
        raise RagError('invalid_run', 'Only completed runs can be recomputed')
    gold_path = run_path / 'gold.yaml'
    if sha256(gold_path.read_bytes()).hexdigest() != metadata['gold_sha256']:
        raise RagError('invalid_gold', 'Saved gold hash differs from run passport')
    from dnd_rag.config import read_yaml

    document = GoldDocument.model_validate(read_yaml(gold_path))
    questions = {}
    for question in document.questions:
        facts = [
            fact.model_copy(
                update={
                    'alternatives': [
                        span.model_copy(
                            update={
                                'body_sha256': document.corpus['files'][span.file]['body_sha256']
                            }
                        )
                        for span in fact.alternatives
                    ]
                }
            )
            for fact in question.evidence
        ]
        questions[question.id] = question.model_copy(update={'evidence': facts})
    manifest = [
        ChunkRef.model_validate_json(line)
        for line in (run_path / 'chunks_manifest.jsonl').read_text().splitlines()
    ]
    rows = []
    for line in (run_path / 'per_question.jsonl').read_text().splitlines():
        row = json.loads(line)
        hits = [RetrievalHit.model_validate(hit) for hit in row['retrieval']['hits']]
        rows.append(evaluate_question(questions[row['question_id']], hits, manifest))
    return aggregate_metrics(rows)
