import csv
import json
from copy import deepcopy
from pathlib import Path

import pytest

from dnd_rag.config import load_experiment, read_yaml
from dnd_rag.contracts import RagError
from dnd_rag.evaluation.study import _differences, read_study_entry, summarize_results
from tests.rag.fixtures import baseline_data, make_corpus, write_yaml


def test_dependency_selection_required(tmp_path):
    path = write_yaml(
        tmp_path / 'study.yaml',
        {
            'schema_version': 1,
            'groups': {
                'G2': {
                    'requires_base': True,
                    'selected_base_run': None,
                    'selection_reason': None,
                    'comparisons': [
                        {
                            'config': 'variant.yaml',
                            'run': None,
                            'reference_run': None,
                            'changed_parameters': ['chunking.chunk_overlap'],
                        }
                    ],
                }
            },
        },
    )
    with pytest.raises(RagError, match='[Bb]ase'):
        read_study_entry(path, 'G2', tmp_path / 'variant.yaml', tmp_path)


def test_failed_reference_rejected(tmp_path):
    folder = tmp_path / 'results/base'
    folder.mkdir(parents=True)
    (folder / 'run.json').write_text(json.dumps({'status': 'failed'}))
    path = write_yaml(
        tmp_path / 'study.yaml',
        {
            'schema_version': 1,
            'groups': {
                'G2': {
                    'requires_base': True,
                    'selected_base_run': 'base',
                    'selection_reason': 'Fixture',
                    'comparisons': [
                        {
                            'config': 'variant.yaml',
                            'run': None,
                            'reference_run': 'base',
                            'changed_parameters': ['chunking.chunk_overlap'],
                        }
                    ],
                }
            },
        },
    )
    with pytest.raises(RagError, match='completed'):
        read_study_entry(path, 'G2', tmp_path / 'variant.yaml', tmp_path)


@pytest.fixture
def saved_study(tmp_path):
    corpus = make_corpus(tmp_path / 'corpus')
    from dnd_rag.indexing.corpus import load_corpus

    passport = load_corpus(corpus).passport()
    gold = tmp_path / 'gold.yaml'
    gold.write_text('Fixture gold')
    from hashlib import sha256

    stages = {'embedding': {'name': 'embedding', 'status': 'executed', 'elapsed_ms': 42.0}}
    data = baseline_data()
    data['corpus']['directory'] = str(corpus)
    data['evaluation'] = {'questions': str(gold)}

    def saved(name, *, status='completed', reused=False, gold_hash=None, config=None):
        folder = tmp_path / 'results' / name
        folder.mkdir(parents=True)
        write_yaml(folder / 'config.yaml', config or data)
        metadata = {
            'status': status,
            'run_type': 'retrieval',
            'experiment_name': name,
            'corpus': passport,
            'gold_sha256': gold_hash or sha256(gold.read_bytes()).hexdigest(),
            'metrics_definition_version': 1,
            'config_id': name,
            'index_id': name,
            'build_id': 'b-' + name,
            'index_action': 'reused' if reused else 'built',
            'expected_points': 10,
            'stages': {'embedding': {'name': 'embedding', 'status': 'reused', 'elapsed_ms': None}}
            if reused
            else stages,
            'build_provenance': {'stages': list(stages.values())},
            'wall_time_ms': 60.0,
            'build_spec': {'embedding': {'revision': 'f' * 40, 'dimension': 768}},
        }
        (folder / 'run.json').write_text(json.dumps(metadata))
        metrics = {
            'question_count': 20,
            'error_count': 0,
            'no_relevant_chunks': 0,
            'metrics': {
                **{
                    f'{metric}@{k}': 0.5
                    for metric in ['precision', 'recall', 'evidence_coverage']
                    for k in [1, 5, 10]
                },
                'mrr@10': 0.75,
            },
            'volume': {
                f'@{k}': {'returned_count': {'mean': k}, 'raw_tokens': {'mean': k * 100.0}}
                for k in [1, 5, 10]
            },
            'timings_ms': {
                name: {
                    'all': {'mean': 2.0, 'median': 2.0, 'max': 3.0, 'min': 1.0},
                    'warm': {'mean': 1.0, 'median': 1.0, 'max': 2.0, 'min': 0.5},
                    'first_query': 3.0,
                }
                for name in ['query_embedding', 'search', 'retrieval']
            },
        }
        (folder / 'metrics.json').write_text(json.dumps(metrics))
        return folder

    return data, saved


def test_summary_is_offline_and_preserves_provenance(tmp_path, saved_study, monkeypatch):
    _, saved = saved_study
    saved('base')
    saved('reuse', reused=True)
    saved('different_gold', gold_hash='e' * 64)
    saved('failed', status='failed')
    study = write_yaml(
        tmp_path / 'study.yaml',
        {
            'schema_version': 1,
            'groups': {
                'G1': {
                    'requires_base': False,
                    'selected_base_run': 'base',
                    'comparisons': [
                        {'config': name + '.yaml', 'run': name}
                        for name in ['base', 'reuse', 'different_gold', 'failed']
                    ],
                }
            },
        },
    )
    from dnd_rag.indexing.embedding import QueryEncoder
    from dnd_rag.indexing.store import QdrantStore
    from dnd_rag.runtime.processes import RuntimeSession

    for owner in [RuntimeSession, QdrantStore, QueryEncoder]:
        monkeypatch.setattr(
            owner, '__init__', lambda *a, **k: pytest.fail('Summary must be offline')
        )
    output = summarize_results(study, tmp_path / 'comparison.csv', project_root=tmp_path)
    with output.open() as stream:
        rows = {r['run']: r for r in csv.DictReader(stream)}
    assert rows['base']['comparison_eligible'] == rows['reuse']['comparison_eligible'] == 'True'
    assert rows['base']['comparison_cohort'] != rows['different_gold']['comparison_cohort']
    assert (
        rows['different_gold']['comparison_eligible']
        == rows['failed']['comparison_eligible']
        == 'False'
    )
    assert rows['failed']['precision@5'] == ''
    assert rows['reuse']['preparation_ms'] == '' and rows['reuse']['stage_embedding_ms'] == ''
    assert float(rows['reuse']['original_preparation_ms']) == 42.0
    for field in [
        'evidence_coverage@10',
        'recall@1',
        'mrr@10',
        'raw_tokens@5_mean',
        'retrieval_warm_median_ms',
        'index_id',
        'build_id',
        'run_path',
        'index_action',
    ]:
        assert rows['base'][field] != ''


def test_declared_delta_and_selected_reference_checked(tmp_path, saved_study):
    data, saved = saved_study
    saved('base')
    saved('other')
    variant = deepcopy(data)
    variant['chunking'] = {'chunk_size': 768, 'chunk_overlap': 64}
    config = write_yaml(tmp_path / 'variant.yaml', variant)
    entry = {
        'requires_base': True,
        'selected_base_run': 'base',
        'selection_reason': 'Fixture',
        'comparisons': [
            {
                'config': 'variant.yaml',
                'reference_run': 'base',
                'changed_parameters': ['chunking.chunk_size'],
            }
        ],
    }
    path = write_yaml(tmp_path / 'study.yaml', {'schema_version': 1, 'groups': {'G2': entry}})
    assert read_study_entry(path, 'G2', config, tmp_path).reference_run == 'base'
    entry['comparisons'][0]['reference_run'] = 'other'
    write_yaml(path, {'schema_version': 1, 'groups': {'G2': entry}})
    with pytest.raises(RagError, match='selected base'):
        read_study_entry(path, 'G2', config, tmp_path)
    entry['comparisons'][0]['reference_run'] = 'base'
    entry['comparisons'][0]['changed_parameters'] = ['chunking.chunk_overlap']
    write_yaml(path, {'schema_version': 1, 'groups': {'G2': entry}})
    with pytest.raises(RagError, match='delta'):
        read_study_entry(path, 'G2', config, tmp_path)


def test_config_deltas_are_exact():
    root = Path(__file__).resolve().parents[2]
    study = read_yaml(root / 'configs/experiments/study.yaml')
    expected = {
        'G1': [[], ['chunking.strategy'], ['chunking.strategy']],
        'G2': [['chunking.chunk_overlap'], ['chunking.chunk_size']],
        'G3': [['retrieval.mode']],
        'G4': [
            ['index.hnsw.m', 'index.hnsw.ef_construction', 'retrieval.ef_search'],
            ['bm25.stemmer', 'bm25.k1', 'bm25.b'],
        ],
        'G5': [['embedding.strip_markdown_headings'], ['embedding.include_title']],
    }
    baseline = load_experiment(
        root / 'configs/experiments/g1_splitters/markdown.yaml', project_root=root
    )
    paths = set()
    for name, deltas in expected.items():
        group = study['groups'][name]
        assert len(group['comparisons']) == len(deltas)
        if group['selected_base_run']:
            base = load_experiment(
                root / 'results' / group['selected_base_run'] / 'config.yaml', project_root=root
            )
        else:
            base = baseline
            if name == 'G4':
                base = base.model_copy(
                    update={'retrieval': base.retrieval.model_copy(update={'mode': 'hybrid'})}
                )
        if name in ('G2', 'G3', 'G5'):
            assert base.retrieval.mode == 'dense'
        if name == 'G4':
            assert base.retrieval.mode == 'hybrid'
        for item, delta in zip(group['comparisons'], deltas, strict=True):
            paths.add(item['config'])
            current = load_experiment(root / item['config'], project_root=root)
            assert set(
                _differences(base.model_dump(mode='json'), current.model_dump(mode='json'))
            ) == set(delta)
            assert set(item.get('changed_parameters', [])) == set(delta)
    assert len(paths) == 10
