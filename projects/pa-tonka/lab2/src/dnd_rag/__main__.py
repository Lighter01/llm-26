"""Thin CLI; only the selected command loads its runtime dependencies."""

import argparse
import json
import re
import sys
from pathlib import Path

from dnd_rag.config import load_experiment, load_settings
from dnd_rag.contracts import RagError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parser():
    root = argparse.ArgumentParser(prog='python -m dnd_rag', description='Local D&D RAG')
    commands = root.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build-index', help='Ensure a complete compatible index')
    build.add_argument('--config', type=Path, required=True)
    build.add_argument('--rebuild', action='store_true', help='Repeat all preparation stages')
    reset = commands.add_parser('reset-index', help='Delete one owned index; missing is a no-op')
    selector = reset.add_mutually_exclusive_group(required=True)
    selector.add_argument('--config', type=Path)
    selector.add_argument('--index-id', help='Full SHA256 from a previous run')
    return root


def main(argv=None):
    try:
        args = parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code
    try:
        if (
            args.command == 'reset-index'
            and args.index_id
            and not re.fullmatch('[a-f0-9]{64}', args.index_id)
        ):
            raise RagError('invalid_index_id', 'Expected a full lowercase SHA256 index_id')
        settings = load_settings(PROJECT_ROOT)
        config = load_experiment(args.config, project_root=PROJECT_ROOT) if args.config else None
        from dnd_rag.runtime.application import ensure_index, reset_index
        from dnd_rag.runtime.processes import RuntimeSession

        with RuntimeSession(PROJECT_ROOT) as session:
            if args.command == 'build-index':
                result = ensure_index(
                    config,
                    settings,
                    session,
                    rebuild=args.rebuild,
                    on_stage=lambda e: print(e.model_dump_json(), file=sys.stderr, flush=True),
                )
                print(result.model_dump_json(indent=2))
            else:
                deleted = reset_index(settings, session, config=config, index_id=args.index_id)
                print(json.dumps({'deleted': deleted}))
        return 0
    except RagError as exc:
        print(json.dumps({'error': exc.as_dict()}, ensure_ascii=False), file=sys.stderr)
        return 2 if exc.code.startswith('invalid_') else 1
    except KeyboardInterrupt:
        print('Runtime interrupted; owned children stopped.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
