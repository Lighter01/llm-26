"""Standalone managed server using the same profile, runtime lock and launcher."""

import argparse
from pathlib import Path
from time import sleep

from dnd_rag.config import load_llm_profile, load_settings, resolve_path
from dnd_rag.runtime.llama import start_llama
from dnd_rag.runtime.processes import RuntimeSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--llm-profile', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = load_settings(root)
    profile = load_llm_profile(resolve_path(args.llm_profile, root))
    with RuntimeSession(root) as session:
        client = start_llama(settings, profile, session)
        try:
            print('llama.cpp ready', flush=True)
            while client.is_ready():
                sleep(0.5)
        finally:
            client.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
