"""Unique run directories, immutable input copies, and atomic status updates."""

import json
import re
import shutil
import uuid
from pathlib import Path
from time import perf_counter

import yaml

from dnd_rag.contracts import RagError
from dnd_rag.indexing.store import utc_now


def validate_run_name(name):
    if (
        not isinstance(name, str)
        or not re.fullmatch(r'[A-Za-z0-9_.-]+', name)
        or name in ('.', '..')
    ):
        raise RagError(
            'invalid_run_name',
            'Experiment name must be one safe path component: letters, digits, _-.',
        )


class RunWriter:
    def __init__(self, path, name, run_type):
        self.path = path
        self.started = perf_counter()
        self.metadata = {
            'schema_version': 1,
            'run_id': str(uuid.uuid4()),
            'experiment_name': name,
            'run_type': run_type,
            'started_at': utc_now(),
            'ended_at': None,
            'status': 'running',
            'current_stage': 'reserved',
            'stages': {},
            'error': None,
        }
        self.write_json('run.json', self.metadata)

    @classmethod
    def reserve(cls, project_root: Path, name: str, run_type: str):
        validate_run_name(name)
        directory = project_root / 'results' / name
        directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            directory.mkdir()
        except FileExistsError as exc:
            raise RagError(
                'invalid_run_name', f'Run directory already exists: {directory}'
            ) from exc
        return cls(directory, name, run_type)

    def snapshot(self, config_path, resolved_config, gold_path):
        shutil.copyfile(config_path, self.path / 'config.yaml')
        shutil.copyfile(gold_path, self.path / 'gold.yaml')
        (self.path / 'resolved_config.yaml').write_text(
            yaml.safe_dump(dict(resolved_config), sort_keys=False, allow_unicode=True),
            encoding='utf-8',
        )

    def update_metadata(self, fields):
        self.metadata.update(fields)
        self.write_json('run.json', self.metadata)

    def record_stage(self, event):
        if event.status == 'failed':
            self.metadata['current_stage'] = event.name
        else:
            self.metadata['last_completed_stage'] = event.name
        self.metadata['stages'][event.name] = event.model_dump(mode='json')
        self.write_json('run.json', self.metadata)

    def write_json(self, name, data):
        target = self.path / name
        temporary = target.with_name('.' + target.name + '.tmp')
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8'
        )
        temporary.replace(target)

    def append_jsonl(self, name, row):
        with (self.path / name).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')

    def finish(self, status, *, error=None):
        self.update_metadata(
            {
                'status': status,
                'ended_at': utc_now(),
                'wall_time_ms': (perf_counter() - self.started) * 1000,
                'failed_stage': self.metadata['current_stage'] if status == 'failed' else None,
                'error': error.as_dict() if error else None,
            }
        )
