"""Run the public API in fresh processes with only four copied inputs available."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

from helpers import PROJECT, copy_build, file_bytes

pytestmark = pytest.mark.integration


WORKER = r"""
import json, os
from pathlib import Path
import sys

source, output, project = map(Path, sys.argv[1:])
opened = set()
def audit(event, args):
    if event.startswith('socket.'):
        raise AssertionError('Unexpected network access: ' + event)
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0])).resolve()
        if path.is_relative_to(project / 'external') or path.is_relative_to(project / 'src/dnd_rag/ingestion/book_assembly'):
            raise AssertionError('Unexpected upstream/assembler access: ' + str(path))
        if path.is_relative_to(source):
            assert not (args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)), 'Input write attempted'
            opened.add(str(path.relative_to(source)))
sys.addaudithook(audit)
from dnd_rag.ingestion.markdown_export import render_build
corpus = render_build(source)
for name, raw in corpus.files.items():
    (output / name).write_bytes(raw)
print(json.dumps(sorted(opened)))
"""


def fingerprint(paths):
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
        if p.is_file() and '__pycache__' not in p.parts
    }


def git_state():
    path = PROJECT / 'external/5etools-src'
    # Reading Git state is test evidence, not a dependency of the renderer.
    return tuple(
        subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True).stdout
        for args in (['rev-parse', 'HEAD'], ['status', '--porcelain', '--untracked-files=no'])
    )


def test_separate_processes_paths_read_only_inputs_and_byte_identity(input_build, corpus, tmp_path):
    source = tmp_path / 'input'
    protected = list(input_build.rglob('*')) + list(
        (PROJECT / 'src/dnd_rag/ingestion/book_assembly').rglob('*')
    )
    before, before_git = fingerprint(protected), git_state()
    names = copy_build(input_build, source)
    original_copy = fingerprint(source.rglob('*'))
    reports = []
    for seed, directory in (('1', input_build), ('73', source)):
        output = tmp_path / ('output-' + seed)
        output.mkdir()
        env = dict(
            os.environ,
            PYTHONPATH=str(PROJECT / 'src'),
            PYTHONHASHSEED=seed,
            PYTHONDONTWRITEBYTECODE='1',
        )
        result = subprocess.run(
            [sys.executable, '-c', WORKER, str(directory), str(output), str(PROJECT)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == sorted(names)
        actual = file_bytes(output)
        assert actual == corpus.files
        assert all(
            str(directory).encode() not in raw and str(PROJECT).encode() not in raw
            for raw in actual.values()
        )
        reports.append(actual)
    assert reports[0] == reports[1]
    assert fingerprint(source.rglob('*')) == original_copy
    assert fingerprint(protected) == before
    assert git_state() == before_git
