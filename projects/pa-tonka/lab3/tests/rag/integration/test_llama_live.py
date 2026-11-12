"""Explicit Nemotron token parity and bounded inference probe, one locked runtime."""

import json
import resource
import shutil
import subprocess
from pathlib import Path
from time import perf_counter

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from dnd_rag.config import load_llm_profile, load_settings
from dnd_rag.runtime.llama import start_llama
from dnd_rag.runtime.processes import RuntimeSession

pytestmark = pytest.mark.rag_llama
ROOT = Path(__file__).resolve().parents[3]


def test_real_template_token_parity(tmp_path):
    settings = load_settings(ROOT)
    profile = load_llm_profile(ROOT / 'configs/llm/off.yaml')
    report = {'profile': profile.model_dump(), 'cases': []}

    def gpu_sample(stage):
        result = subprocess.run(
            [
                'nvidia-smi',
                '--query-gpu=memory.used,utilization.gpu',
                '--format=csv,noheader,nounits',
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        memory, utilization = (int(x.strip()) for x in result.stdout.strip().split(','))
        report.setdefault('gpu_samples', []).append(
            {'stage': stage, 'used_mib': memory, 'utilization_percent': utilization}
        )

    gpu_sample('before_server')
    before = perf_counter()
    try:
        with RuntimeSession(ROOT) as session:
            client = start_llama(settings, profile, session)
            report['startup_ms'] = (perf_counter() - before) * 1000
            report['server'] = client.server_provenance
            gpu_sample('ready')
            child_fd = (
                Path('/proc') / str(client.server_provenance['pid']) / 'fd' / str(session.lock.fd)
            )
            report['inherited_project_lock'] = (
                child_fd.resolve() == (ROOT / '.runtime/project.lock').resolve()
            )
            assert report['inherited_project_lock']
            try:
                short = [
                    SystemMessage(content='Answer in English, briefly.'),
                    HumanMessage(content='Say ready.'),
                ]
                from dnd_rag.config import load_rag_config
                from dnd_rag.indexing.corpus import load_corpus
                corpus = load_corpus(load_rag_config(None, project_root=ROOT).corpus.directory)
                fragments = [book.body[:2000] for book in corpus.books.values()]
                content = 'Explain these D&D rules:\n'
                # Fill with real source passages to approach the accepted full-input bound.
                position = 0
                while True:
                    candidate = content + '\n' + fragments[position % len(fragments)]
                    messages = [
                        SystemMessage(
                            content='Use only the supplied D&D rules. Answer briefly in English.'
                        ),
                        HumanMessage(content=candidate),
                    ]
                    count = client.count_input_tokens(messages)
                    if count > 6400:
                        break
                    content = candidate
                    position += 1
                long = [messages[0], HumanMessage(content=content)]
                for name, messages, limit in [('short', short, 16), ('near_budget', long, 32)]:
                    count = client.count_input_tokens(messages)
                    before = perf_counter()
                    output = client.generate(messages, max_tokens=limit)
                    elapsed = (perf_counter() - before) * 1000
                    report['cases'].append(
                        {
                            'case': name,
                            'counted_input_tokens': count,
                            'response_input_tokens': output.input_tokens,
                            'output_tokens': output.output_tokens,
                            'finish_reason': output.finish_reason,
                            'elapsed_ms': elapsed,
                            'server_timings': output.server_timings,
                            'raw_response': output.raw_response,
                        }
                    )
                    gpu_sample(name)
                    assert count == output.input_tokens
                    assert count <= 6400 and (name != 'near_budget' or count >= 5700)
                    assert output.output_tokens <= limit
                    assert not output.raw_response['choices'][0]['message'].get('reasoning_content')
            finally:
                client.close()
    finally:
        gpu_sample('after_server')
        report['child_peak_rss_bytes'] = (
            resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024
        )
        target = tmp_path / 'llama-probe.json'
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        log = ROOT / '.runtime/llama/server.log'
        if log.exists():
            shutil.copyfile(log, tmp_path / 'llama-probe-server.log')
