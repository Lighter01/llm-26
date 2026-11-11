"""Publish a fully validated corpus by directory renames with rollback.

All temporary paths are siblings of the destination, on the same filesystem.
No per-file replacement, upstream runtime, artifact registry or platform-specific
exchange syscall is needed. A sibling lock excludes concurrent exporter writers.
"""

import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from ..api import render_build
from ..common.model import ARTIFACTS, ExportError, PublishedCorpus, require
from .validation import validate_corpus


def _target(directory, input_build):
    candidate = Path(os.path.abspath(Path(directory).expanduser()))
    require(
        not candidate.is_symlink(),
        'OUTPUT_PATH',
        'Output directory must not be a symlink',
        output=str(candidate),
    )
    target = candidate.resolve()
    require(
        target != Path.cwd().resolve(),
        'OUTPUT_OVERLAP',
        'Output must not replace the current working directory',
        output=str(target),
    )
    package = Path(__file__).resolve().parents[3]
    protected = [input_build, package]
    if package.parent.name == 'src':
        protected.append(package.parent.parent / 'external')
    for path in protected:
        require(
            not (target.is_relative_to(path) or path.is_relative_to(target)),
            'OUTPUT_OVERLAP',
            'Output overlaps inputs, source code or an external dependency',
            output=str(target),
            protected=str(path),
        )
    return target


def _inspect(target, force):
    require(
        not target.is_symlink(),
        'OUTPUT_PATH',
        'Output directory must not be a symlink',
        output=str(target),
    )
    if not target.exists():
        return None
    require(target.is_dir(), 'OUTPUT_PATH', 'Output must be a directory', output=str(target))
    contents = set(path.name for path in target.iterdir())
    require(
        contents <= ARTIFACTS,
        'OUTPUT_CONTENT',
        'Output contains files not owned by this exporter',
        output=str(target),
        unexpected=sorted(contents - ARTIFACTS),
    )
    require(
        all((target / name).is_file() and not (target / name).is_symlink() for name in contents),
        'OUTPUT_CONTENT',
        'Existing exporter files must be regular files',
        output=str(target),
    )
    require(
        not contents or force,
        'OUTPUT_EXISTS',
        'Output already exists; use --force to regenerate exporter files',
        output=str(target),
    )
    return contents


def _write_stage(stage, corpus):
    for name, raw in corpus.files.items():
        with (stage / name).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


def _check_stage(stage, corpus):
    require(
        {p.name for p in stage.iterdir()} == ARTIFACTS,
        'INVALID_OUTPUT',
        'Staged directory has unexpected files',
    )
    actual = {name: (stage / name).read_bytes() for name in corpus.files}
    require(
        actual == corpus.files, 'INVALID_OUTPUT', 'Staged bytes differ from the rendered corpus'
    )
    validate_corpus(replace(corpus, files=actual))


def _publish(corpus, target, force):
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.parent / ('.' + target.name + '.export.lock')
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ExportError(
            'OUTPUT_LOCKED', 'Another export holds the destination lock', lock=str(lock)
        ) from error
    stage = backup = None
    old_moved, committed, warnings = False, False, []
    failure = None
    stage_identity = None

    def cleanup(path):
        if path is not None:
            try:
                shutil.rmtree(path)
            except FileNotFoundError:
                pass
            except OSError as error:
                warnings.append(f'Cleanup failed; retained {path}: {error}')

    try:
        _inspect(target, force)
        stage = Path(tempfile.mkdtemp(prefix='.' + target.name + '.stage-', dir=target.parent))
        _write_stage(stage, corpus)
        _check_stage(stage, corpus)
        stat = stage.stat()
        stage_identity = (stat.st_dev, stat.st_ino)
        existing = _inspect(target, force)
        if existing is not None:
            backup = Path(
                tempfile.mkdtemp(prefix='.' + target.name + '.backup-', dir=target.parent)
            )
            backup.rmdir()
            os.replace(target, backup)
            old_moved = True
        os.replace(stage, target)
        committed, stage = True, None
    except BaseException as error:
        failure = error
        if not committed and stage_identity is not None:
            try:
                stat = target.stat()
            except OSError:
                stat = None
            if stat is not None and (stat.st_dev, stat.st_ino) == stage_identity:
                committed, stage = True, None
                error.add_note(
                    f'Publication already committed; validated corpus remains at {target}.'
                )
        # A signal can arrive after the rename syscall but before the flag assignment.
        old_moved = old_moved or (backup is not None and backup.exists() and not target.exists())
        if not committed and old_moved:
            try:
                os.replace(backup, target)
                backup = None
            except OSError as rollback_error:
                failure = ExportError(
                    'ROLLBACK_FAILED',
                    'Original corpus remains in backup; restore it before retrying',
                    output=str(target),
                    backup=str(backup),
                    reason=str(rollback_error),
                )
                raise failure from error
        raise
    finally:
        cleanup(stage)
        if committed or not old_moved:
            cleanup(backup)
        try:
            lock.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            warnings.append(f'Cleanup failed; retained lock {lock}: {error}')
        if failure is not None:
            for warning in warnings:
                failure.add_note(warning)
    return PublishedCorpus(target, 'replaced' if existing else 'created', corpus, tuple(warnings))


def export_build(input_build, output_dir=None, *, force=False):
    """Read one explicit build, validate all four outputs, then publish them.

    Without force, only an absent or empty destination is accepted. Force may
    replace any subset of the four exporter files, including damaged outputs;
    unrelated files, directories and symlinks are always refused.
    """
    try:
        source = Path(input_build).resolve(strict=True)
        corpus = render_build(source)
        sha = validate_corpus(corpus)
        directory = output_dir if output_dir is not None else Path('data/markdown/5etools') / sha
        return _publish(corpus, _target(directory, source), force)
    except ExportError:
        raise
    except OSError as error:
        failure = ExportError('PUBLICATION_IO', str(error), output=str(output_dir))
        for note in getattr(error, '__notes__', ()):
            failure.add_note(note)
        raise failure from error
