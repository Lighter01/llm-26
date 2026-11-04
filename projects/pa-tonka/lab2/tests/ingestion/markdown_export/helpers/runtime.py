"""Subprocess helpers shared by CLI and standalone corpus tests."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]


def run_cli(cwd, *arguments, seed='1'):
    return subprocess.run(
        [sys.executable, '-m', 'dnd_rag.ingestion.markdown_export', *map(str, arguments)],
        cwd=cwd,
        env=dict(
            os.environ,
            PYTHONPATH=str(PROJECT / 'src'),
            PYTHONDONTWRITEBYTECODE='1',
            PYTHONHASHSEED=seed,
        ),
        capture_output=True,
        text=True,
        timeout=120,
    )


def snapshot(directory):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}


def file_bytes(directory):
    return {p.name: p.read_bytes() for p in directory.iterdir()}


def assert_no_temporary_paths(output):
    assert not list(output.parent.glob('.' + output.name + '.*'))


def copy_build(source, destination):
    """Copy only the manifest and its books, preserving relative paths."""
    manifest = json.loads((source / 'manifest.json').read_bytes())
    names = ['manifest.json', *[metadata['path'] for metadata in manifest['books'].values()]]
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    return names
