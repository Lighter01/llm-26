"""Public CLI: python -m dnd_rag.ingestion.markdown_export."""

import argparse
import sys
from collections import Counter
from pathlib import Path

from .common.model import ExportError
from .publication.store import export_build


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Export one complete resolved build to three Markdown books and source_map.jsonl.',
        allow_abbrev=False,
    )
    parser.add_argument(
        '--input-build',
        required=True,
        type=Path,
        help='Explicit directory containing manifest.json and the three resolved books',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        help='Destination directory (default: data/markdown/5etools/<upstream_sha> relative to the working directory)',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Regenerate exporter files in an existing destination; never rebuild inputs',
    )
    args = parser.parse_args(argv)
    try:
        result = export_build(args.input_build, args.output_dir, force=args.force)
    except ExportError as error:
        print(str(error), file=sys.stderr)
        for note in getattr(error, '__notes__', ()):
            print(note, file=sys.stderr)
        return 1
    except KeyboardInterrupt as error:
        print('Export cancelled.', file=sys.stderr)
        for note in getattr(error, '__notes__', ()):
            print(note, file=sys.stderr)
        return 130
    for book in result.corpus.books:
        counts = book.diagnostics.counts
        print(
            f'{book.book_id}: {counts["chapters"]} parts, {counts["headings"]} headings, {counts.get("statblocks", 0)} statblocks'
        )
        for code, count in Counter(m['code'] for m in book.diagnostics.messages).items():
            print(f'{book.book_id}: {code} ({count})', file=sys.stderr)
        unknown = sum(r['page_attribution'] == 'unknown' for r in book.source_map)
        if unknown:
            print(f'{book.book_id}: unknown printed page for {unknown} sections', file=sys.stderr)
    for warning in result.warnings:
        print(warning, file=sys.stderr)
    print(f'Markdown export {result.status}: {result.output_dir} (4 files)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
