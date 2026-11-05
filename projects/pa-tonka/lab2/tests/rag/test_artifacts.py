import json

import pytest

from dnd_rag.contracts import RagError, StageEvent
from dnd_rag.evaluation.artifacts import RunWriter


@pytest.mark.parametrize('name', ['../escape', '.', '..', 'a/b', 'a\\b', 'space name'])
def test_unsafe_name_rejected(tmp_path, name):
    with pytest.raises(RagError):
        RunWriter.reserve(tmp_path, name, 'retrieval')


def test_existing_name_and_failed_run_kept(tmp_path):
    writer = RunWriter.reserve(tmp_path, 'run1', 'retrieval')
    assert json.loads((writer.path / 'run.json').read_text())['status'] == 'running'
    with pytest.raises(RagError):
        RunWriter.reserve(tmp_path, 'run1', 'retrieval')
    writer.record_stage(StageEvent(name='embedding', status='reused', elapsed_ms=None))
    writer.finish('failed', error=RagError('service_down', 'Unavailable'))
    data = json.loads((writer.path / 'run.json').read_text())
    assert data['status'] == 'failed'
    assert data['error']['code'] == 'service_down'
    assert data['stages']['embedding']['elapsed_ms'] is None
