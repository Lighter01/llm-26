from dnd_rag.agent.contracts import AgentReply
from tests.rag.test_metrics import hits, ref, span


def case(**kwargs):
    from dnd_rag.experiments.contracts import TurnCase

    return TurnCase(input='question', rubric=['Faithful and useful'], **kwargs)


def record(text='27 gp', tools=None):
    return {
        'reply': AgentReply(text=text, status='completed', trace_id='a').model_dump(),
        'tools': tools or [],
        'events': [],
        'history': [],
    }


def test_pending_review_is_not_success_and_actual_loot_drives_score():
    from dnd_rag.experiments.scoring import evaluate_turn

    c = case(
        expected_tools=['generate_loot'],
        checks={
            'answer_matches_tool_loot': True,
            'loot': {'kind': 'individual', 'cr': '1/4', 'count': 3},
        },
    )
    tool = {
        'name': 'generate_loot',
        'arguments': {'kind': 'individual', 'cr': 0.25, 'count': 3},
        'result': {'kind': 'individual', 'coins': {'gp': 27}, 'total_gp': 27.0, 'items': []},
        'status': 'completed',
    }
    r = record(tools=[tool])
    s = evaluate_turn(c, r)
    assert s.values['loot_amount_reported'] == 1 and s.pending and s.success is None
    r['tools'][0]['result']['coins']['gp'] = 31
    assert evaluate_turn(c, r).values['loot_amount_reported'] == 0
    assert evaluate_turn(c, r).success is False
    reviewed = evaluate_turn(
        c,
        record(tools=[{**tool, 'result': {'coins': {'gp': 27}, 'items': []}}]),
        annotation={
            'rubric_0': {
                'value': 1,
                'method': 'agent-assisted',
                'evidence': 'trace a actual payout',
            }
        },
    )
    assert reviewed.success is True


def test_formal_constraints_party_exact_count_required_and_failures():
    from dnd_rag.experiments.scoring import evaluate_turn

    c = case(
        expected_tools=['build_encounter'],
        checks={
            'party_size': 4,
            'party_level': 3,
            'total_count': 4,
            'required_monsters': {'Goblin Warrior': 1},
            'habitat': 'forest',
            'creature_type': 'fey',
            'difficulty': 'moderate',
        },
    )
    t = {
        'name': 'build_encounter',
        'arguments': {'party_size': 4, 'party_level': 3, 'difficulty': 'moderate'},
        'status': 'completed',
        'result': {
            'status': 'success',
            'difficulty': 'moderate',
            'monsters': [
                {
                    'name': 'Goblin Warrior',
                    'count': 2,
                    'creature_types': ['fey'],
                    'habitats': ['forest'],
                },
                {'name': 'Other', 'count': 2, 'creature_types': ['fey'], 'habitats': ['forest']},
            ],
        },
    }
    s = evaluate_turn(c, record(tools=[t]))
    assert s.values['required_monsters'] == 0 and s.success is False
    r = record()
    r['reply']['status'] = 'timeout'
    assert evaluate_turn(c, r).values['completed'] == 0


def test_retrieval_uses_full_manifest_and_averages_calls_per_turn():
    from dnd_rag.experiments.scoring import evaluate_retrieval_calls

    c = case(evidence=[span(0, 100)])
    manifest = [ref('a', 0, 50), ref('b', 50, 100), ref('c', 100, 200)]
    calls = [
        {
            'name': 'search_rules',
            'arguments': {'limit': 1},
            'result': {'hits': [h.model_dump() for h in hits(manifest[:1])]},
        },
        {
            'name': 'search_rules',
            'arguments': {'limit': 5},
            'result': {'hits': [h.model_dump() for h in hits(manifest[:2])]},
        },
    ]
    rows = evaluate_retrieval_calls(c, calls, manifest)
    assert len(rows) == 2 and rows[0].recall[5] == 0.5 and rows[1].recall[5] == 1
    assert rows[0].precision[5] == 0.2 and rows[1].precision[5] == 0.4
    assert evaluate_retrieval_calls(case(), calls, manifest) == []


def test_corrected_tool_attempt_does_not_fail_final_result_check():
    from dnd_rag.experiments.scoring import evaluate_turn

    c = case(
        expected_tools=['evaluate_encounter'],
        checks={'party_size': 3, 'party_level': 6, 'total_xp': 4600, 'difficulty': 'above_high'},
    )
    tools = [
        {
            'name': 'evaluate_encounter',
            'arguments': {'party_size': 4, 'party_level': 6},
            'result': {'status': 'success', 'total_xp': 4600, 'difficulty': 'high'},
        },
        {
            'name': 'evaluate_encounter',
            'arguments': {'party_size': 3, 'party_level': 6},
            'result': {'status': 'success', 'total_xp': 4600, 'difficulty': 'above_high'},
        },
    ]
    scores = evaluate_turn(c, record(tools=tools))
    assert scores.values['party_size'] == 1 and scores.values['difficulty'] == 1


def test_history_score_requires_explicit_review_after_compaction():
    from dnd_rag.experiments.scoring import evaluate_turn

    c = case(checks={'history_correctness': True})
    r = record()
    r['events'] = [{'kind': 'compaction_completed', 'payload': {'before': 12000, 'after': 3000}}]
    scores = evaluate_turn(c, r)
    assert 'history_correctness' in scores.pending
    reviewed = evaluate_turn(
        c,
        r,
        annotation={
            'rubric_0': {'value': 1, 'method': 'agent-assisted', 'evidence': 'trace facts'},
            'history_correctness': {
                'value': 0,
                'method': 'agent-assisted',
                'evidence': 'trace lost actual first payout',
            },
        },
    )
    assert reviewed.values['history_correctness'] == 0 and reviewed.success is False


def test_requested_build_without_success_is_a_formal_failure():
    from dnd_rag.experiments.scoring import evaluate_turn

    c = case(expected_tools=['build_encounter'], checks={'party_size': 4, 'party_level': 3})
    t = {
        'name': 'build_encounter',
        'arguments': {'party_size': 4, 'party_level': 3},
        'result': {'status': 'search_exhausted'},
        'status': 'completed',
    }
    assert evaluate_turn(c, record(tools=[t])).success is False
