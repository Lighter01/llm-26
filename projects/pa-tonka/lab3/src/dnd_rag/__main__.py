"""Administrative CLI with lazy model imports and project-relative configuration."""

import argparse
import json
import sys
from pathlib import Path

from dnd_rag.config import load_rag_config, load_settings
from dnd_rag.contracts import RagError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parser():
    root = argparse.ArgumentParser(prog='python -m dnd_rag', description='Local D&D DM assistant')
    commands = root.add_subparsers(dest='command', required=True)
    for command in ('build-index', 'inspect-index'):
        sub = commands.add_parser(
            command,
            help='Prepare index'
            if command == 'build-index'
            else 'Inspect selected index without loading models',
        )
        sub.add_argument(
            '--config', type=Path, help='RAG YAML; environment/.env/default R3 otherwise'
        )
        if command == 'build-index':
            sub.add_argument('--rebuild', action='store_true', help='Repeat all build stages')
    prepare = commands.add_parser('prepare-game-data', help='Compile local pinned game catalogs')
    prepare.add_argument(
        '--source',
        type=Path,
        default=None,
        help='Local pinned 5etools root',
    )
    prepare.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Output root; revision directory is appended',
    )
    reset = commands.add_parser('reset-index', help='Delete one owned collection')
    selector = reset.add_mutually_exclusive_group(required=True)
    selector.add_argument('--config', type=Path)
    selector.add_argument('--index-id', help='Full lowercase SHA256 index ID')
    return root


def main(argv=None):
    try:
        args = parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code
    try:
        import re

        if (
            args.command == 'reset-index'
            and args.index_id
            and not re.fullmatch('[a-f0-9]{64}', args.index_id)
        ):
            raise RagError('invalid_index_id', 'Expected a full lowercase SHA256 index_id')
        if args.command == 'prepare-game-data':
            from dnd_rag.config import resolve_path
            from dnd_rag.game.prepare import prepare_game_catalog
            from dnd_rag.runtime.processes import RuntimeSession

            with RuntimeSession(PROJECT_ROOT):
                from dnd_rag.config import read_yaml

                game = read_yaml(PROJECT_ROOT / 'configs/game.yaml')
                path = prepare_game_catalog(
                    resolve_path(args.source or game['source_root'], PROJECT_ROOT),
                    resolve_path(args.output or game['output_root'], PROJECT_ROOT),
                )
            print(json.dumps({'catalog': str(path)}))
            return 0
        settings = load_settings(PROJECT_ROOT)
        config = (
            load_rag_config(args.config, project_root=PROJECT_ROOT)
            if args.command != 'reset-index' or args.config
            else None
        )
        from dnd_rag.runtime.index import ensure_index, reset_index
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
            elif args.command == 'inspect-index':
                from dnd_rag.indexing.corpus import load_corpus
                from dnd_rag.indexing.identity import library_versions, make_identity
                from dnd_rag.runtime.index import ensure_qdrant

                store = ensure_qdrant(settings, session)
                identity = make_identity(
                    config,
                    load_corpus(config.corpus.directory),
                    library_versions(store.server_version()),
                )
                from dataclasses import asdict

                inspection = store.inspect(identity)
                print(
                    json.dumps(
                        asdict(inspection), default=lambda v: v.model_dump(mode='json'), indent=2
                    )
                )
            else:
                print(
                    json.dumps(
                        {
                            'deleted': reset_index(
                                settings, session, config=config, index_id=args.index_id
                            )
                        }
                    )
                )
        return 0
    except RagError as exc:
        print(json.dumps({'error': exc.as_dict()}, ensure_ascii=False), file=sys.stderr)
        return 2 if exc.code.startswith('invalid_') else 1
    except KeyboardInterrupt:
        print('Runtime interrupted; owned children stopped.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
