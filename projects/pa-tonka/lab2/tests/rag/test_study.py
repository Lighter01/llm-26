import json

import pytest

from dnd_rag.contracts import RagError
from dnd_rag.evaluation.study import read_study_entry
from tests.rag.fixtures import write_yaml


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
