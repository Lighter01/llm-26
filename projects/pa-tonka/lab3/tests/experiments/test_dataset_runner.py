import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from dnd_rag.agent.contracts import AgentReply
from dnd_rag.contracts import RagError
from dnd_rag.indexing.corpus import load_corpus
from tests.rag.fixtures import make_corpus


def fixture_dataset():
    from dnd_rag.experiments.contracts import AgentDataset, TaskCase, TurnCase

    return AgentDataset(
        version=1,
        items=[
            TaskCase(
                id=f'item{i}',
                metadata={
                    'type': 'single' if i < 8 else 'short_dialogue' if i < 12 else 'long_dialogue',
                    'difficulty': 'medium',
                    'history_dependent': i >= 8,
                },
                turns=[
                    TurnCase(input=f'fixed user {i}/{t}', rubric=['Keep facts'], expected_tools=[])
                ]
                * (1 if i < 8 else 3 if i < 12 else 9),
            )
            for i in range(15)
            for t in [0]
        ],
        fingerprint='fixture',
    )


class FakeAdapter:
    def __init__(self):
        self.calls = []
        self.closed = []
        self.last_records = {}

    async def ainvoke(self, sid, text, *, turn_id, on_event=None):
        self.calls.append((sid, text, turn_id))
        self.last_records[sid] = {'tools': []}
        return AgentReply(
            text='Unreviewed answer',
            status='completed',
            trace_id=f'{len(self.calls):032x}',
            usage={'input_tokens': None, 'output_tokens': None, 'api_cost': 0.0},
        )

    async def close_session(self, sid):
        self.closed.append(sid)


def test_adapter_failure_does_not_reuse_previous_turn_records(tmp_path):
    from dnd_rag.experiments.runner import run_dataset

    dataset = fixture_dataset()
    item = dataset.items[8].model_copy(update={'turns': dataset.items[8].turns[:2]})
    dataset = dataset.model_copy(update={'items': [item]})

    class FailingSecondTurn(FakeAdapter):
        async def ainvoke(self, sid, text, **kwargs):
            if self.calls:
                raise RuntimeError('Spawn failed before any observation was published')
            reply = await super().ainvoke(sid, text, **kwargs)
            self.last_records[sid] = {
                'tools': [{'tool': 'roll_loot', 'arguments': {}, 'result': {'gp': 19}}],
                'events': [{'kind': 'first-turn'}],
                'wire': [{'kind': 'request', 'id': 'first-turn'}],
            }
            return reply

    asyncio.run(
        run_dataset(
            dataset,
            FailingSecondTurn(),
            run_id='failure',
            mode='off',
            agent='own',
            artifacts_dir=tmp_path,
        )
    )
    records = [
        json.loads(line) for line in (tmp_path / 'failure/turns.jsonl').read_text().splitlines()
    ]
    assert len(records[0]['tools']) == 1
    assert records[1]['reply']['error']['code'] == 'adapter_error'
    assert records[1]['raw_records'] == {}
    assert records[1]['tools'] == records[1]['events'] == []


def test_recompute_recovers_timeout_tools_without_modifying_original_records():
    from copy import deepcopy

    from dnd_rag.experiments.artifacts import score_records
    from dnd_rag.experiments.contracts import TurnCase

    dataset = fixture_dataset()
    first = dataset.items[0].model_copy(
        update={
            'turns': [
                TurnCase(
                    input='Check Troll',
                    rubric=['Answer the query'],
                    expected_tools=['lookup_monsters'],
                )
            ]
        }
    )
    dataset = dataset.model_copy(update={'items': [first, *dataset.items[1:]]})
    call = {
        'type': 'function_call',
        'call_id': 'actual-call',
        'name': 'mcp__dnd__lookup_monsters',
        'arguments': '{"query":"Troll"}',
    }
    output = {
        'type': 'function_call_output',
        'call_id': 'actual-call',
        'output': '{"status":"matched","monsters":[]}',
    }
    raw = {
        'case_id': 'item0',
        'turn': 1,
        'tools': [],
        'events': [],
        'reply': AgentReply(text='', status='timeout', usage={'tool_calls': 0}).model_dump(),
        'raw_records': {
            'tools': [],
            'wire': [
                {'kind': 'request', 'effective': {'input': []}},
                {'kind': 'request', 'effective': {'input': [call, output]}},
            ],
        },
    }
    before = deepcopy(raw)
    scored = score_records(dataset, [raw], [])[0]
    assert raw == before
    assert len(scored['tools']) == scored['reply']['usage']['tool_calls'] == 1
    assert scored['scores']['values']['tool_lookup_monsters'] == 1
    assert scored['scores']['values']['completed'] == 0


def test_sequential_turns_sessions_four_modes_60_executions_and_recompute(tmp_path):
    from dnd_rag.experiments.artifacts import recompute
    from dnd_rag.experiments.runner import run_dataset

    dataset = fixture_dataset()
    all_sessions = []
    for agent in ('own', 'codex'):
        for mode in ('off', 'budgeted'):
            adapter = FakeAdapter()
            run_id = f'{agent}-{mode}'
            summary = asyncio.run(
                run_dataset(
                    dataset, adapter, run_id=run_id, mode=mode, agent=agent, artifacts_dir=tmp_path
                )
            )
            assert summary.executions == 15
            sessions = [x[0] for x in adapter.calls]
            all_sessions += list(set(sessions))
            assert sorted(Counter(sessions).values()) == [1] * 8 + [3] * 4 + [9] * 3
            assert len(adapter.calls) == 47 and len(set(x[2] for x in adapter.calls)) == 47
            assert len(adapter.closed) == 15  # close never invokes an extra export
            assert all('fixed user' in x[1] and 'Keep facts' not in x[1] for x in adapter.calls)
            directory = tmp_path / run_id
            metrics = json.loads((directory / 'metrics.json').read_text())
            assert metrics == recompute(directory)
            assert metrics['input_tokens'] is None and metrics['task_success_rate'] is None
            assert metrics['pending_executions'] == 15
            assert metrics['completion_rate'] == 0  # missing usage remains incomplete
    assert len(set(all_sessions)) == 60


def test_exact_evidence_resolver_rejects_hash_ambiguity_and_changed_coordinates(tmp_path):
    from dnd_rag.experiments.dataset import resolve_evidence

    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    book = corpus.books['xphb.md']
    result = resolve_evidence(
        {'file': 'xphb.md', 'quote': 'Welcome 😀.', 'body_sha256': book.body_sha256}, corpus
    )
    assert book.body[result.start_char : result.end_char] == result.quote
    with pytest.raises(RagError):
        resolve_evidence(
            {
                'file': 'xphb.md',
                'quote': 'Repeated paragraph with Unicode café.',
                'body_sha256': book.body_sha256,
            },
            corpus,
        )
    with pytest.raises(RagError):
        resolve_evidence({'file': 'xphb.md', 'quote': 'Welcome 😀.', 'body_sha256': 'old'}, corpus)
    with pytest.raises(RagError):
        resolve_evidence({**result.model_dump(), 'start_char': 1}, corpus)


@pytest.mark.integration
def test_actual_dataset_validates_all_independent_spans():
    from dnd_rag.config import load_rag_config
    from dnd_rag.experiments.dataset import load_dataset

    root = Path(__file__).resolve().parents[2]
    corpus = load_corpus(load_rag_config(None, project_root=root).corpus.directory)
    dataset = load_dataset(root / 'data/tasks/lab3.yaml', corpus, require_shape=True)
    assert len(dataset.items) == 15 and sum(len(i.turns) for i in dataset.items) == 47
    assert sum(len(t.evidence) for i in dataset.items for t in i.turns) == 10
    assert dataset.fingerprint and dataset.corpus_hashes


def test_changed_dataset_is_not_accepted_as_original(tmp_path):
    from dnd_rag.experiments.dataset import load_dataset

    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    path = tmp_path / 'bad.yaml'
    path.write_text(
        yaml.safe_dump(
            {
                'version': 1,
                'items': [
                    {
                        'id': 'one',
                        'metadata': {
                            'type': 'single',
                            'difficulty': 'easy',
                            'history_dependent': False,
                        },
                        'turns': [
                            {
                                'input': 'x',
                                'rubric': ['a'],
                                'evidence': [
                                    {'file': 'xphb.md', 'quote': 'absent', 'body_sha256': 'wrong'}
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    )
    with pytest.raises(RagError):
        load_dataset(path, corpus)


def test_duplicate_turn_or_foreign_review_is_rejected(tmp_path):
    from dnd_rag.experiments.artifacts import score_records

    dataset = fixture_dataset()
    row = {
        'case_id': 'item0',
        'turn': 1,
        'session_id': 'one',
        'input': 'fixed user',
        'reply': AgentReply(text='x', status='completed').model_dump(),
        'tools': [],
        'events': [],
    }
    with pytest.raises(RagError):
        score_records(dataset, [row, row], [])
    with pytest.raises(RagError):
        score_records(
            dataset,
            [row],
            [],
            {('foreign', 1): {'rubric_0': {'value': 1, 'method': 'human', 'evidence': 'x'}}},
        )
