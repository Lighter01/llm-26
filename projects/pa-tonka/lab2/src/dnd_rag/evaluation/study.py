"""An explicit map of comparisons, not inheritance or an automatic study runner."""

import json
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field

from dnd_rag.config import load_experiment, read_yaml, resolve_path
from dnd_rag.contracts import Contract, RagError
from dnd_rag.evaluation.artifacts import validate_run_name
from dnd_rag.indexing.corpus import load_corpus


class Comparison(Contract):
    config: str
    run: str | None = None
    reference_run: str | None = None
    changed_parameters: list[str] = Field(default_factory=list)


class StudyGroup(Contract):
    requires_base: bool
    selected_base_run: str | None = None
    selection_reason: str | None = None
    comparisons: list[Comparison]


class QASelection(Contract):
    run: str
    config: str
    reason: str = Field(min_length=1)


class Study(Contract):
    schema_version: Literal[1]
    groups: dict[str, StudyGroup]
    qa_selection: QASelection | None = None


class StudySelection(Contract):
    group: str
    reference_run: str | None
    changed_parameters: list[str]
    selection_reason: str | None


def _differences(first, second, prefix=''):
    if isinstance(first, dict) and isinstance(second, dict):
        result = []
        for key in sorted(first.keys() | second.keys()):
            path = f'{prefix}.{key}' if prefix else key
            result.extend(_differences(first.get(key), second.get(key), path))
        return result
    return [] if first == second else [prefix]


def read_study_entry(
    study_path: Path, group: str, config_path: Path, project_root: Path
) -> StudySelection:
    try:
        study = Study.model_validate(read_yaml(resolve_path(study_path, project_root)))
        entry = study.groups[group]
        if entry.requires_base and not entry.selected_base_run:
            raise ValueError(f'Base is not selected for {group}')
        if entry.requires_base and not entry.selection_reason:
            raise ValueError(f'Record the selected base reason for {group}')
        selected = [
            c
            for c in entry.comparisons
            if resolve_path(c.config, project_root) == resolve_path(config_path, project_root)
        ]
        if len(selected) != 1:
            raise ValueError('Config must identify exactly one comparison in the group')
        comparison = selected[0]
        if (
            entry.requires_base
            and comparison.reference_run is not None
            and comparison.reference_run != entry.selected_base_run
        ):
            raise ValueError('A dependent comparison must use its group selected base')
        reference = comparison.reference_run or entry.selected_base_run
        # A selected base and an explicit reference must both be completed.
        for name in dict.fromkeys(n for n in (entry.selected_base_run, reference) if n is not None):
            validate_run_name(name)
            run_path = project_root / 'results' / name
            metadata = json.loads((run_path / 'run.json').read_text())
            if metadata.get('status') != 'completed' or metadata.get('run_type') != 'retrieval':
                raise ValueError(f'Reference/base {name} must be a completed retrieval run')
        if reference:
            current = load_experiment(config_path, project_root=project_root)
            run_path = project_root / 'results' / reference
            metadata = json.loads((run_path / 'run.json').read_text())
            if (
                metadata.get('gold_sha256')
                != sha256(current.evaluation.questions.read_bytes()).hexdigest()
                or metadata.get('corpus') != load_corpus(current.corpus.directory).passport()
            ):
                raise ValueError('Reference and current corpus/gold differ')
            base = load_experiment(run_path / 'config.yaml', project_root=project_root)
            changed = _differences(base.model_dump(mode='json'), current.model_dump(mode='json'))
            if set(changed) != set(comparison.changed_parameters):
                raise ValueError(f'Actual config delta {changed} differs from declared changes')
        return StudySelection(
            group=group,
            reference_run=reference,
            changed_parameters=comparison.changed_parameters,
            selection_reason=entry.selection_reason,
        )
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise RagError('invalid_study', f'{study_path}: {exc}') from exc


def summarize_results(study_path: Path, output_path: Path, *, project_root: Path) -> Path:
    """Export explicit comparisons from saved files, without starting a runtime."""
    from dnd_rag.evaluation.summary import write_summary

    path = resolve_path(study_path, project_root)
    try:
        study = Study.model_validate(read_yaml(path))
        return write_summary(study, path, resolve_path(output_path, project_root), project_root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RagError('invalid_summary', f'{study_path}: {exc}') from exc
