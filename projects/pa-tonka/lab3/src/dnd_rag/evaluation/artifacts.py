"""Unique run directories, immutable input copies, and atomic status updates."""

import csv
import json
import os
import platform
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from statistics import mean, median
from time import perf_counter

import yaml

from dnd_rag.contracts import RagError, StageEvent
from dnd_rag.indexing.identity import FULL_SCAN_THRESHOLD, INDEXING_THRESHOLD
from dnd_rag.indexing.store import utc_now


def summary_statistics(values):
    if not values:
        return None
    return {'mean': mean(values), 'median': median(values), 'max': max(values), 'min': min(values)}


def code_provenance(root):
    def git(args):
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None

    return {
        'git_commit': git(['rev-parse', 'HEAD']),
        'git_status': git(['status', '--short', '--', '.']),
        'python': platform.python_version(),
        'platform': platform.platform(),
        'cpu_count': os.cpu_count(),
        'ram_bytes': os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES'),
    }


def resolved_config(config):
    return {
        **config.model_dump(mode='json'),
        'fixed': {
            'text_only': True,
            'distance': 'Cosine',
            'normalize_embeddings': True,
            'stored_datatype': 'float32',
            'vector_name': 'dense',
            'shard_number': 1,
            'indexing_threshold_kb': INDEXING_THRESHOLD,
            'full_scan_threshold_kb': FULL_SCAN_THRESHOLD,
            'document_device': 'cuda',
            'query_device': 'cpu',
            'query_dtype': 'float32',
            'quantization_rescore': False,
            'quantization_ignore': False,
            'rrf_weights': [1.0, 1.0],
            'max_embedding_input_tokens': 8192,
        },
    }


def record_elapsed(writer, name, before):
    writer.record_stage(
        StageEvent(name=name, status='executed', elapsed_ms=(perf_counter() - before) * 1000)
    )


def index_metadata(ensured):
    index = ensured.index
    return {
        'index_id': index.index_id,
        'build_id': index.build_id,
        'collection': index.collection,
        'build_spec': index.build_spec,
        'index_action': ensured.action,
        'index_reason': ensured.reason,
        'build_provenance': index.build_provenance,
        'expected_points': index.expected_points,
    }


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

    def append_csv(self, name, fields, row):
        target = self.path / name
        new = not target.exists()
        with target.open('a', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
            if new:
                writer.writeheader()
            if row is not None:
                writer.writerow(row)

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
