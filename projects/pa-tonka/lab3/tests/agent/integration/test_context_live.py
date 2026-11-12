"""Meaningful long-dialogue evidence, run only against an explicitly owned live stack."""

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
import yaml

from dnd_rag.agent.config import AgentConfig
from dnd_rag.agent.observability import ObservationRecorder
from dnd_rag.agent.service import AgentService
from dnd_rag.config import load_llm_profile, load_settings
from dnd_rag.experiments.codex import CodexRunner
from dnd_rag.runtime.llm import NativeLLM

ROOT = Path(__file__).resolve().parents[3]
pytestmark = [
    pytest.mark.rag_llama,
    pytest.mark.skipif(os.getenv('DM_CONTEXT_LIVE') != '1', reason='Explicit owned stack required'),
]


@pytest.mark.parametrize('agent', ['own', 'codex'])
def test_long_dialogue_preserves_actual_loot_after_compaction(agent):
    directory = ROOT / '.superpowers/sdd/2026-11-12-lab3-dm-agent/context-live'
    directory.mkdir(exist_ok=True)
    item = next(
        i
        for i in yaml.safe_load((ROOT / 'data/tasks/lab3.yaml').read_text())['items']
        if i['id'] == 'long_01_mothbridge_ledger'
    )

    async def run():
        sid = 'memory-' + agent + '-' + uuid.uuid4().hex[:12]
        adapter = (
            AgentService(
                native_llm=NativeLLM(
                    load_settings(ROOT), load_llm_profile(ROOT / 'configs/llm/off.yaml')
                ),
                config=AgentConfig(context_limit=7500),
                recorder=ObservationRecorder(directory / 'own', project_root=ROOT),
            )
            if agent == 'own'
            else CodexRunner(ROOT, artifacts_dir=directory / 'codex')
        )
        replies = []
        records = []
        try:
            for n, turn in enumerate(item['turns'], 1):
                reply = await adapter.ainvoke(sid, turn['input'], turn_id=f'turn-{n}')
                replies.append(reply.model_dump(mode='json'))
                records.append(adapter.last_records.get(sid, {}))
                (directory / f'{sid}.json').write_text(
                    json.dumps({'replies': replies, 'records': records}, indent=2)
                )
                print(agent, n, reply.status, reply.context.input_tokens, flush=True)
                assert reply.status == 'completed', reply.error
            if agent == 'own':
                rows = [
                    json.loads(line)
                    for line in (directory / 'own' / sid / 'turns.jsonl').read_text().splitlines()
                ]
                compacted = [r for r in rows if r['kind'] == 'compaction_completed']
                assert len(compacted) >= 2
                assert all(r['after'] < r['before'] for r in compacted)
                loot = next(
                    t['result'] for t in records[0]['tools'] if t['name'] == 'generate_loot'
                )
                assert str(int(loot['total_gp'])) in replies[-1]['text']
                # Real readback, including the summary span and full generation I/O.
                checker = CodexRunner(ROOT, artifacts_dir=directory / 'checks')
                summary_turn = next(r for r in replies if r['context']['compacted'])
                observations = await checker.verify_trace(
                    summary_turn['trace_id'], summary_turn['text'], []
                )
                assert any(r.get('name') == 'compaction' for r in observations)
                assert any(
                    r.get('type') == 'GENERATION' and 'context_summary' in r.get('name', '')
                    for r in observations
                )
                (directory / f'{sid}.observations.json').write_text(
                    json.dumps(observations, indent=2)
                )
            else:
                rows = [
                    json.loads(line)
                    for line in Path(records[-1]['rollout']).read_text().splitlines()
                ]
                assert any(
                    r.get('type') == 'compacted'
                    or r.get('payload', {}).get('type') == 'context_compacted'
                    for r in rows
                ), 'No native Codex compaction observed'
            final = replies[-1]['text'].lower()
            assert ('5' in final or 'five' in final) and ('4' in final or 'four' in final)
            assert 'mira' in final and 'lantern' in final
        finally:
            await adapter.aclose()

    asyncio.run(run())
