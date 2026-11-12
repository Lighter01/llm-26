"""Explicit live clients of an already running, matching shared stack."""

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest

from dnd_rag.agent.observability import ObservationRecorder
from dnd_rag.agent.service import AgentService
from dnd_rag.config import load_llm_profile, load_settings
from dnd_rag.experiments.codex import CodexRunner
from dnd_rag.runtime.llm import NativeLLM

pytestmark = [
    pytest.mark.rag_llama,
    pytest.mark.skipif(
        os.getenv('DM_LIVE_STACK') != '1',
        reason='Requires explicitly started MCP/LLM/proxy/Langfuse',
    ),
]
ROOT = Path(__file__).resolve().parents[3]


def test_two_agents_search_resume_and_export_last_turn_once(tmp_path):
    async def run():
        own = AgentService(
            native_llm=NativeLLM(
                load_settings(ROOT), load_llm_profile(ROOT / 'configs/llm/off.yaml')
            ),
            recorder=ObservationRecorder(tmp_path / 'own', project_root=ROOT),
        )
        codex = CodexRunner(ROOT, artifacts_dir=tmp_path / 'codex')
        try:
            for name, adapter in [('own', own), ('codex', codex)]:
                sid = 'live-' + name + '-' + uuid.uuid4().hex
                first = await adapter.ainvoke(
                    sid,
                    'Remember: party four, level 6. Use search_rules to find the 2024 moderate XP budget at level6. Answer briefly.',
                    turn_id='one',
                )
                assert first.status == 'completed', first.error
                assert first.trace_id and first.usage['input_tokens'] is not None
                records = adapter.last_records[sid]['tools']
                assert any(r.get('name', r.get('tool')) == 'search_rules' for r in records)
                second = await adapter.ainvoke(
                    sid, 'What party size and level did I specify?', turn_id='two'
                )
                assert second.status == 'completed', second.error
                assert second.trace_id != first.trace_id
                assert 'four' in second.text.lower() or '4' in second.text
                assert '6' in second.text or 'six' in second.text.lower()
                if name == 'codex':
                    before = json.loads(
                        (tmp_path / 'codex' / sid / '2.observations.json').read_text()
                    )
                    trace_id, _, _ = await codex.export(
                        sid, codex._rollout(codex.sessions[sid]['id']), 2
                    )
                    after = await codex.verify_trace(trace_id, second.text, [])
                    assert len(after) == len(before)
        finally:
            await own.aclose()

    asyncio.run(run())
