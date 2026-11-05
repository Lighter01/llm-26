"""Offline comparison rows; different datasets remain visibly separate cohorts."""

import csv
import json

from dnd_rag.contracts import RagError
from dnd_rag.evaluation.artifacts import validate_run_name
from dnd_rag.indexing.identity import digest

BUILD_STAGES = (
    'tokenizer_load',
    'splitting',
    'document_model_load',
    'embedding',
    'upload',
    'index_wait',
    'bm25_index',
)
STAGES = (
    *BUILD_STAGES,
    'gold_validation',
    'corpus_validation',
    'qdrant_readiness',
    'index_inspection',
    'manifest_export',
    'query_model_load',
    'evaluation_export',
)
METRICS = [
    f'{metric}@{k}' for metric in ('precision', 'recall', 'evidence_coverage') for k in (1, 5, 10)
] + ['mrr@10']
FIELDS = [
    'group',
    'role',
    'run',
    'reference_run',
    'recorded_group',
    'recorded_reference_run',
    'config_path',
    'config_id',
    'index_id',
    'build_id',
    'status',
    'index_action',
    'changed_parameters',
    'selection_reason',
    'comparison_cohort',
    'comparison_eligible',
    'comparison_error',
    'gold_sha256',
    'metrics_definition_version',
    'model_revision',
    'question_count',
    'error_count',
    'no_relevant_chunks',
    'expected_points',
    'storage_vectors_bytes',
    *METRICS,
    *[f'{kind}@{k}_mean' for k in (1, 5, 10) for kind in ('raw_tokens', 'returned_count')],
    'preparation_ms',
    'original_preparation_ms',
    'wall_time_ms',
    *[f'stage_{name}_ms' for name in STAGES],
    *[
        f'{name}_{temperature}_{stat}_ms'
        for name in ('query_embedding', 'search', 'retrieval')
        for temperature in ('all', 'warm')
        for stat in ('mean', 'median', 'max', 'min')
    ],
    'first_retrieval_ms',
    'run_path',
    'config_snapshot_path',
]


def _read_run(root, name):
    validate_run_name(name)
    folder = root / 'results' / name
    try:
        metadata = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'status': 'missing'}, {}, None, 'Run has not been saved'
    except (ValueError, OSError) as exc:
        return {'status': 'invalid'}, {}, None, f'Cannot read run passport: {exc}'
    cohort = digest(
        {key: metadata.get(key) for key in ('corpus', 'gold_sha256', 'metrics_definition_version')}
    )
    if metadata.get('status') != 'completed':
        return metadata, {}, cohort, f'Run status is {metadata.get("status")}'
    if metadata.get('run_type') != 'retrieval':
        return metadata, {}, cohort, 'Only retrieval runs can be compared'
    try:
        metrics = json.loads((folder / 'metrics.json').read_text(encoding='utf-8'))
        if metrics['question_count'] != 20 or metrics['error_count'] != 0:
            raise ValueError('Expected twenty successful primary questions')
        if not metadata.get('gold_sha256') or not metadata.get('corpus'):
            raise ValueError('Dataset passport is incomplete')
        if any(name not in metrics['metrics'] for name in METRICS):
            raise ValueError('Required metrics are missing')
        return metadata, metrics, cohort, None
    except (ValueError, KeyError, OSError, TypeError) as exc:
        return metadata, {}, cohort, f'Cannot compare metrics: {exc}'


def _elapsed(stages, name):
    event = stages.get(name, {})
    return event.get('elapsed_ms') if event.get('status') == 'executed' else None


def _preparation(stages):
    values = [_elapsed(stages, name) for name in BUILD_STAGES]
    measured = [value for value in values if value is not None]
    return sum(measured) if measured else None


def _original_stages(metadata):
    stages = metadata.get('build_provenance', {}).get('stages', [])
    if isinstance(stages, dict):
        return stages
    return {event['name']: event for event in stages}


def _comparison_row(group, role, name, reference, config, changes, reason, data, anchor):
    metadata, metrics, cohort, error = data[name]
    for control in dict.fromkeys(name for name in (anchor, reference) if name is not None):
        _, _, control_cohort, control_error = data[control]
        if control_error:
            error = error or f'Reference/base {control} is unavailable: {control_error}'
        elif cohort != control_cohort:
            error = (
                error or f'Corpus, gold or metric definitions differ from reference/base {control}'
            )
    stages = metadata.get('stages', {})
    original = metadata.get('build_provenance', {})
    row = {
        'group': group,
        'role': role,
        'run': name,
        'reference_run': reference,
        'recorded_group': metadata.get('group'),
        'recorded_reference_run': metadata.get('reference_run'),
        'config_path': config,
        'config_id': metadata.get('config_id'),
        'index_id': metadata.get('index_id'),
        'build_id': metadata.get('build_id'),
        'status': metadata.get('status'),
        'index_action': metadata.get('index_action'),
        'changed_parameters': json.dumps(changes, separators=(',', ':')),
        'selection_reason': reason,
        'comparison_cohort': cohort,
        'comparison_eligible': error is None,
        'comparison_error': error,
        'gold_sha256': metadata.get('gold_sha256'),
        'metrics_definition_version': metadata.get('metrics_definition_version'),
        'model_revision': metadata.get('build_spec', {}).get('embedding', {}).get('revision'),
        'question_count': metrics.get('question_count'),
        'error_count': metrics.get('error_count'),
        'no_relevant_chunks': metrics.get('no_relevant_chunks'),
        'expected_points': metadata.get('expected_points'),
        'storage_vectors_bytes': original.get('storage_vectors_bytes'),
        **metrics.get('metrics', {}),
        'preparation_ms': _preparation(stages)
        if metadata.get('index_action') in ('built', 'rebuilt')
        else None,
        'original_preparation_ms': _preparation(_original_stages(metadata)),
        'wall_time_ms': metadata.get('wall_time_ms'),
        **{f'stage_{name}_ms': _elapsed(stages, name) for name in STAGES},
        'first_retrieval_ms': metrics.get('timings_ms', {}).get('retrieval', {}).get('first_query'),
        'run_path': f'results/{name}',
        'config_snapshot_path': f'results/{name}/config.yaml',
    }
    for k in (1, 5, 10):
        volume = metrics.get('volume', {}).get(f'@{k}', {})
        for kind in ('raw_tokens', 'returned_count'):
            row[f'{kind}@{k}_mean'] = volume.get(kind, {}).get('mean')
    for name in ('query_embedding', 'search', 'retrieval'):
        timings = metrics.get('timings_ms', {}).get(name, {})
        for temperature in ('all', 'warm'):
            for stat in ('mean', 'median', 'max', 'min'):
                row[f'{name}_{temperature}_{stat}_ms'] = (timings.get(temperature) or {}).get(stat)
    return row


def _rows(study, data):
    rows = []
    for group_name, group in study.groups.items():
        names = {item.run for item in group.comparisons if item.run is not None}
        anchor = group.selected_base_run or next((c.run for c in group.comparisons if c.run), None)
        references = dict.fromkeys(
            name
            for name in [
                group.selected_base_run,
                *(item.reference_run for item in group.comparisons),
            ]
            if name and name not in names
        )
        for name in references:
            rows.append(
                _comparison_row(
                    group_name,
                    'reference',
                    name,
                    None,
                    f'results/{name}/config.yaml',
                    [],
                    group.selection_reason,
                    data,
                    anchor,
                )
            )
        for item in group.comparisons:
            if item.run is None:
                rows.append(
                    {
                        'group': group_name,
                        'role': 'comparison',
                        'config_path': item.config,
                        'status': 'not_run',
                        'comparison_eligible': False,
                        'comparison_error': 'No run recorded for this configuration',
                    }
                )
                continue
            reference = item.reference_run or group.selected_base_run
            if reference == item.run:
                reference = None
            row = _comparison_row(
                group_name,
                'comparison',
                item.run,
                reference,
                item.config,
                item.changed_parameters,
                group.selection_reason,
                data,
                anchor,
            )
            if group.requires_base and not group.selected_base_run:
                row.update(comparison_eligible=False, comparison_error='Group base is not selected')
            elif (
                group.requires_base
                and item.reference_run is not None
                and item.reference_run != group.selected_base_run
            ):
                row.update(
                    comparison_eligible=False,
                    comparison_error='A dependent comparison must use its group selected base',
                )
            rows.append(row)
    return rows


def write_summary(study, study_path, output, root):
    if output == study_path or (output.parent / 'run.json').is_file():
        raise RagError(
            'invalid_summary', 'Write the summary outside immutable run folders and input files'
        )
    names = dict.fromkeys(
        name
        for group in study.groups.values()
        for name in [
            group.selected_base_run,
            *(c.run for c in group.comparisons),
            *(c.reference_run for c in group.comparisons),
        ]
        if name
    )
    data = {name: _read_run(root, name) for name in names}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name('.' + output.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(_rows(study, data))
    temporary.replace(output)
    return output
