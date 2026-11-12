"""Frozen independent evidence validation; no agent output or retrieval input."""

from collections import Counter
from hashlib import sha256
from pathlib import Path

import yaml

from dnd_rag.config import UniqueKeyLoader
from dnd_rag.contracts import RagError
from dnd_rag.evaluation.evidence import EvidenceSpan, validate_span
from dnd_rag.experiments.contracts import AgentDataset


def resolve_evidence(raw, corpus):
    try:
        book = corpus.books[raw['file']]
        digest = raw.get('body_sha256', raw.get('body_hash'))
        if digest != book.body_sha256 or raw.get('body_hash', digest) != digest:
            raise ValueError('Wrong corpus body hash')
        quote = raw['quote']
        if not quote:
            raise ValueError('Empty quote')
        data = {k: v for k, v in raw.items() if k in EvidenceSpan.model_fields}
        data['body_sha256'] = digest
        if 'start_char' not in data or 'end_char' not in data:
            occurrences = []
            start = 0
            while (start := book.body.find(quote, start)) >= 0:
                end = start + len(quote)
                if not raw.get('heading_path') or any(
                    s.attribution.heading_path == raw['heading_path']
                    and s.start <= start < end <= s.end
                    for s in book.sections
                ):
                    occurrences.append((start, end))
                start += 1
            if len(occurrences) != 1:
                raise ValueError('Quote is absent or ambiguous in the selected section')
            start, end = occurrences[0]
            data.update(book.coordinates(start, end))
            sections = book.attributions(start, end)
            if not data.get('heading_path'):
                data['heading_path'] = max(sections, key=lambda s: len(s.heading_path)).heading_path
        if raw.get('book_id', book.metadata['book_id']) != book.metadata['book_id']:
            raise ValueError('Wrong book ID')
        return validate_span(EvidenceSpan.model_validate(data), corpus)
    except (KeyError, ValueError, TypeError) as exc:
        raise RagError('invalid_evidence', f'Cannot resolve exact evidence: {exc}') from exc


def load_dataset(path, corpus, *, require_shape=False):
    path = Path(path)
    try:
        content = path.read_bytes()
        data = yaml.load(content, Loader=UniqueKeyLoader)
        for item in data['items']:
            for turn in item['turns']:
                turn['evidence'] = [
                    resolve_evidence(raw, corpus).model_dump() for raw in turn.get('evidence', [])
                ]
        data.update(
            fingerprint=sha256(content).hexdigest(),
            source_path=str(path.resolve()),
            corpus_hashes=corpus.passport(),
        )
        dataset = AgentDataset.model_validate(data)
        if dataset.version != 1:
            raise ValueError('Unsupported dataset version')
        ids = [i.id for i in dataset.items]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate task IDs')
        for item in dataset.items:
            if (
                item.metadata.get('type') not in ('single', 'short_dialogue', 'long_dialogue')
                or item.metadata.get('difficulty') not in ('easy', 'medium', 'hard')
                or type(item.metadata.get('history_dependent')) is not bool
            ):
                raise ValueError('Missing task type/difficulty/history metadata')
        counts = Counter(i.metadata['type'] for i in dataset.items)
        if require_shape and (
            not 15 <= len(ids) <= 30
            or counts['single'] < 8
            or counts['short_dialogue'] < 4
            or counts['long_dialogue'] < 3
        ):
            raise ValueError('Expected15..30 tasks with at least8/4/3 task types')
        return dataset
    except RagError:
        raise
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise RagError('invalid_dataset', f'Cannot load dataset {path}: {exc}') from exc
