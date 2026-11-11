"""Read one dataset, validate it, and atomically publish portable annotations."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from .corpus import BOOK_FILES, load_corpus
from .validation import load_questions, validate_document


@dataclass(frozen=True)
class ValidationResult:
    report: dict
    questions_path: Path | None


class _LiteralDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _represent_string(dumper, value):
    # YAML treats NEL as a line break even inside literal blocks. Escape Unicode
    # line separators so reloading the annotations retains the exact string.
    if any(char in value for char in '\x85\u2028\u2029'):
        style = '"'
    else:
        style = '|' if '\n' in value else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style=style)


_LiteralDumper.add_representer(str, _represent_string)


def _atomic_write(path: Path, data: bytes):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp', delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_report(path: Path, report: dict):
    _atomic_write(path, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def validate_questions(
    input_path: str | Path, corpus_dir: str | Path, output_dir: str | Path
) -> ValidationResult:
    """Return PASS/FAIL and write a report; output/report I/O may raise OSError.

    Validation failures preserve an existing questions.yaml. The input is never
    modified, and coordinates refer to the exact Markdown body, excluding YAML.
    """
    input_path, corpus_dir, output_dir = map(Path, (input_path, corpus_dir, output_dir))
    output_path = output_dir / 'questions.yaml'
    report_path = output_dir / 'validation_report.json'
    protected = {
        path.resolve()
        for path in (
            input_path,
            corpus_dir / 'source_map.jsonl',
            *(corpus_dir / name for name in BOOK_FILES),
        )
    }
    if report_path.resolve() in protected:
        raise OSError('validation_report.json would overwrite an input; choose another output-dir')
    errors = []
    collision = output_path.resolve() in protected
    if collision:
        errors.append(
            {
                'code': 'OUTPUT_COLLISION',
                'path': '$',
                'message': 'questions.yaml would overwrite an input; choose another output-dir',
            }
        )
    document, raw_hash = None, None
    try:
        raw = input_path.read_bytes()
    except OSError as error:
        errors.append({'code': 'INPUT_IO', 'path': '$', 'message': str(error)})
    else:
        raw_hash = hashlib.sha256(raw).hexdigest()
        document = load_questions(raw, errors)
    corpus = load_corpus(corpus_dir, errors)
    checked, report = validate_document(document, corpus, errors)
    passport = {
        'files': {name: {'body_sha256': book.body_sha256} for name, book in corpus.files.items()},
        'source_map_sha256': corpus.source_map_sha256,
    }
    report.update(raw_input_sha256=raw_hash, corpus=passport)
    previous = not collision and output_path.exists()
    preserved_state = 'previous_preserved' if previous else 'not_written'
    report['output_state'] = preserved_state
    output_dir.mkdir(parents=True, exist_ok=True)
    if errors:
        _write_report(report_path, report)
        return ValidationResult(report, None)

    checked.update(corpus=passport, raw_input_sha256=raw_hash)
    data = yaml.dump(
        checked, Dumper=_LiteralDumper, allow_unicode=True, sort_keys=False, width=100
    ).encode('utf-8')
    # A report-write failure must not replace an existing verified dataset.
    report['output_state'] = 'written'
    _write_report(report_path, report)
    try:
        _atomic_write(output_path, data)
    except OSError as error:
        errors.append({'code': 'OUTPUT_IO', 'path': '$', 'message': str(error)})
        report.update(status='FAIL', output_state=preserved_state)
        _write_report(report_path, report)
        return ValidationResult(report, None)
    return ValidationResult(report, output_path)
