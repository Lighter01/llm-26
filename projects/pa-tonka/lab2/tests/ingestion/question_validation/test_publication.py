import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from dnd_rag.ingestion.question_validation import validate_questions

PROJECT = Path(__file__).resolve().parents[3]


def cli(case, *args, seed='1'):
    return subprocess.run(
        [sys.executable, '-m', 'dnd_rag.ingestion.question_validation', *map(str, args)],
        cwd=case.input.parent,
        env=dict(os.environ, PYTHONPATH=str(PROJECT / 'src'), PYTHONHASHSEED=seed),
        capture_output=True,
        text=True,
        timeout=30,
    )


def arguments(case, output=None):
    return ['--input', case.input, '--corpus', case.corpus, '--output-dir', output or case.output]


def test_failed_validation_preserves_previous_result_and_cli_explains_it(case):
    first = cli(case, *arguments(case))
    assert first.returncode == 0, first.stderr
    path = case.output / 'questions.yaml'
    before = path.read_bytes(), path.stat().st_mtime_ns
    case.document['questions'][0]['evidence'][0]['alternatives'][0]['quote'] = 'Not in the book.'
    case.save()
    failed = cli(case, *arguments(case))
    assert failed.returncode == 1 and 'Traceback' not in failed.stderr
    assert 'previous' in (failed.stdout + failed.stderr).lower()
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    report = json.loads((case.output / 'validation_report.json').read_bytes())
    assert report['status'] == 'FAIL' and report['output_state'] == 'previous_preserved'
    assert sorted(p.name for p in case.output.iterdir()) == [
        'questions.yaml',
        'validation_report.json',
    ]


@pytest.mark.parametrize(
    ('field', 'scalar'),
    [('answerable', '!!bool maybe'), ('reference_answer', '!!timestamp not-a-date')],
)
@pytest.mark.parametrize('previous_pass', [False, True], ids=['initial', 'after-pass'])
def test_invalid_tagged_scalars_write_fail_report_and_preserve_previous_yaml(
    case, field, scalar, previous_pass
):
    questions_path = case.output / 'questions.yaml'
    report_path = case.output / 'validation_report.json'
    if previous_pass:
        first = cli(case, *arguments(case))
        assert first.returncode == 0, first.stderr
        assert json.loads(report_path.read_bytes())['status'] == 'PASS'
        previous_yaml = questions_path.read_bytes(), questions_path.stat().st_mtime_ns

    raw = case.input.read_text(encoding='utf-8')
    original_line = next(
        line for line in raw.splitlines(True) if line.lstrip().startswith(f'{field}:')
    )
    invalid_line = original_line.split(':', 1)[0] + f': {scalar}\n'
    case.save(raw.replace(original_line, invalid_line, 1))
    protected = {path: path.read_bytes() for path in [case.input, *case.corpus.iterdir()]}

    failed = cli(case, *arguments(case))
    assert failed.returncode == 1
    assert 'Traceback' not in failed.stdout + failed.stderr
    assert 'INPUT_YAML' in failed.stderr
    report = json.loads(report_path.read_bytes())
    assert report['status'] == 'FAIL'
    assert any(error['code'] == 'INPUT_YAML' for error in report['errors'])
    assert report['raw_input_sha256'] == hashlib.sha256(case.input.read_bytes()).hexdigest()
    if previous_pass:
        assert report['output_state'] == 'previous_preserved'
        assert (questions_path.read_bytes(), questions_path.stat().st_mtime_ns) == previous_yaml
        assert 'earlier successful run' in failed.stderr
    else:
        assert report['output_state'] == 'not_written'
        assert not questions_path.exists()
    assert {path: path.read_bytes() for path in protected} == protected


def test_replace_failure_keeps_previous_yaml_and_removes_temporary_files(case, monkeypatch):
    first = validate_questions(case.input, case.corpus, case.output)
    assert first.report['status'] == 'PASS'
    before = first.questions_path.read_bytes(), first.questions_path.stat().st_mtime_ns
    original_replace = os.replace

    def fail_yaml(source, destination):
        if Path(destination).name == 'questions.yaml':
            raise OSError('simulated replace failure')
        return original_replace(source, destination)

    monkeypatch.setattr(os, 'replace', fail_yaml)
    result = validate_questions(case.input, case.corpus, case.output)
    assert result.report['status'] == 'FAIL' and result.questions_path is None
    assert result.report['output_state'] == 'previous_preserved'
    assert (first.questions_path.read_bytes(), first.questions_path.stat().st_mtime_ns) == before
    assert sorted(p.name for p in case.output.iterdir()) == [
        'questions.yaml',
        'validation_report.json',
    ]


def test_report_io_failure_does_not_publish_yaml(case, monkeypatch):
    original_replace = os.replace

    def fail_report(source, destination):
        if Path(destination).name == 'validation_report.json':
            raise OSError('simulated report failure')
        return original_replace(source, destination)

    monkeypatch.setattr(os, 'replace', fail_report)
    with pytest.raises(OSError, match='simulated report failure'):
        validate_questions(case.input, case.corpus, case.output)
    assert not list(case.output.iterdir())


def test_output_collision_cannot_overwrite_raw_input(case):
    case.input = case.input.rename(case.input.parent / 'questions.yaml')
    before = case.input.read_bytes()
    result = validate_questions(case.input, case.corpus, case.input.parent)
    assert result.report['status'] == 'FAIL'
    assert result.questions_path is None and case.input.read_bytes() == before


def test_cli_help_required_paths_and_initial_failure(case):
    before = sorted(case.input.parent.iterdir())
    help_result = cli(case, '--help')
    assert help_result.returncode == 0
    assert all(flag in help_result.stdout for flag in ('--input', '--corpus', '--output-dir'))
    missing = cli(case)
    assert missing.returncode == 2 and '--input' in missing.stderr
    assert sorted(case.input.parent.iterdir()) == before
    case.document['questions'][0]['question'] = ''
    case.save()
    failed = cli(case, *arguments(case))
    assert failed.returncode == 1 and 'Traceback' not in failed.stderr
    assert not (case.output / 'questions.yaml').exists()


def test_reproducibility_in_fresh_processes_and_changed_successful_input(case):
    before = {path: path.read_bytes() for path in [case.input, *case.corpus.iterdir()]}
    first_dir, second_dir = case.output / 'first', case.output / 'second'
    for seed, directory in (('1', first_dir), ('97', second_dir)):
        result = cli(case, *arguments(case, directory), seed=seed)
        assert result.returncode == 0, result.stderr
    assert (first_dir / 'questions.yaml').read_bytes() == (
        second_dir / 'questions.yaml'
    ).read_bytes()
    assert {path: path.read_bytes() for path in before} == before
    case.document['questions'][0]['reference_answer'] = 'An updated reference answer.'
    case.save()
    updated = cli(case, *arguments(case, first_dir))
    assert updated.returncode == 0, updated.stderr
    assert (first_dir / 'questions.yaml').read_bytes() != (
        second_dir / 'questions.yaml'
    ).read_bytes()
    output = yaml.safe_load((first_dir / 'questions.yaml').read_bytes())
    assert output['questions'][0]['reference_answer'] == 'An updated reference answer.'
