"""CLI: python -m dnd_rag.ingestion.question_validation."""

import argparse
import sys
from pathlib import Path

from .api import validate_questions


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Validate one raw question YAML against an explicit Markdown corpus.',
        allow_abbrev=False,
    )
    parser.add_argument('--input', required=True, type=Path, help='One raw question YAML')
    parser.add_argument(
        '--corpus',
        required=True,
        type=Path,
        help='Directory containing three Markdown books and source_map.jsonl',
    )
    parser.add_argument(
        '--output-dir',
        required=True,
        type=Path,
        help='Destination for questions.yaml and validation_report.json',
    )
    args = parser.parse_args(argv)
    try:
        result = validate_questions(args.input, args.corpus, args.output_dir)
    except (OSError, ValueError) as error:
        print(f'Validation failed: {error}', file=sys.stderr)
        return 1
    report = result.report
    counts = report['counts']
    print(
        f'Question validation {report["status"]}: {counts["questions"]} questions, '
        f'{counts["facts"]} facts, {counts["alternatives"]} alternatives; '
        f'{counts["matched_alternatives"]} exact unique matches.'
    )
    for error in report['errors']:
        location = error.get('path', error.get('file', '$'))
        details = ' '.join(
            f'{key}={error[key]}'
            for key in (
                'id',
                'fact_number',
                'alternative_number',
                'file',
                'line',
                'column',
                'source_map_line',
            )
            if key in error
        )
        print(f'{error["code"]} {location} {details}: {error["message"]}', file=sys.stderr)
        if 'candidates' in error:
            print(f'  candidates: {error["candidates"]}', file=sys.stderr)
    if report['output_state'] == 'previous_preserved':
        print(
            'Previous questions.yaml preserved; it belongs to an earlier successful run.',
            file=sys.stderr,
        )
    print(f'Report: {args.output_dir / "validation_report.json"}')
    print(report['manual_review_required'])
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
