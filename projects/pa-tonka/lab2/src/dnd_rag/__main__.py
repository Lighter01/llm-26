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
    experiment = commands.add_parser(
        'experiment', help='Run a full retrieval experiment without LLM'
    )
    experiment.add_argument('--config', type=Path, required=True)
    experiment.add_argument(
        '--experiment-name', required=True, help='Unique safe results directory name'
    )
    experiment.add_argument('--rebuild', action='store_true')
    experiment.add_argument('--study', type=Path, help='Optional study map; requires --group')
    experiment.add_argument('--group', help='Group in the study; requires --study')
    serve = commands.add_parser('serve-retrieval', help='Run a retrieval-only API without LLM/UI')
    serve.add_argument('--config', type=Path, required=True)
    serve.add_argument('--rebuild', action='store_true')
    demo = commands.add_parser('demo', help='Run the local Q&A API and Streamlit interface')
    demo.add_argument('--config', type=Path, required=True)
    demo.add_argument('--llm-profile', type=Path, required=True)
    demo.add_argument('--rebuild', action='store_true')
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
        if args.command in ('serve-retrieval', 'demo'):
            from dnd_rag.runtime.application import run_demo, serve_retrieval

            if args.command == 'demo':
                run_demo(args.config, args.llm_profile, settings, rebuild=args.rebuild)
            else:
                serve_retrieval(args.config, settings, rebuild=args.rebuild)
            return 0
        if args.command == 'experiment':
            from dnd_rag.evaluation.retrieval_run import run_retrieval_experiment
            from dnd_rag.evaluation.study import read_study_entry

            if bool(args.study) != bool(args.group):
                raise RagError('invalid_study', '--study and --group must be supplied together')
            selection = (
                read_study_entry(args.study, args.group, args.config, PROJECT_ROOT)
                if args.study
                else None
            )
            path = run_retrieval_experiment(
                args.config,
                args.experiment_name,
                settings,
                rebuild=args.rebuild,
                selection=selection,
            )
            print(json.dumps({'results': str(path)}))
            return 0
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
    except Exception as exc:
        import traceback

        log_directory = PROJECT_ROOT / '.runtime'
        log_directory.mkdir(exist_ok=True)
        with (log_directory / 'errors.log').open('a') as stream:
            traceback.print_exc(file=stream)
        print(
            json.dumps({'error': {'code': 'runtime_error', 'message': str(exc)}}), file=sys.stderr
        )
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
