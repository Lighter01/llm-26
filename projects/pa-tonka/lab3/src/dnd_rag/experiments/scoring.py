"""Formal tool checks, independent retrieval math, explicit semantic review."""

import re
from fractions import Fraction

from dnd_rag.contracts import RetrievalHit
from dnd_rag.evaluation.evidence import EvidenceCase, EvidenceFact
from dnd_rag.evaluation.metrics import evaluate_question
from dnd_rag.experiments.contracts import Scores


def normalized_tools(records):
    result = []
    for raw in records:
        data = raw.get('result') or {}
        if isinstance(data, dict) and 'structured_content' in data:
            data = data['structured_content'] or {}
        if isinstance(data, dict) and 'content' in data and 'structured_content' not in data:
            import json

            try:
                data = json.loads(
                    '\n'.join(x.get('text', '') for x in data['content'] if x.get('type') == 'text')
                )
            except (ValueError, TypeError):
                pass
        result.append(
            {
                **raw,
                'name': raw.get('name', raw.get('tool', '')),
                'arguments': raw.get('arguments', {}),
                'result': data,
                'status': raw.get('status', 'completed'),
            }
        )
    return result


def composition(data):
    return {m['name'].casefold(): m['count'] for m in data.get('monsters', []) if 'name' in m}


def actual_from_turn(record, number, kind):
    history = record.get('history', [])
    if not 1 <= number <= len(history):
        return None
    for tool in history[number - 1]['tools']:
        if (
            tool['name'] in kind
            and not tool['result'].get('error')
            and tool['result'].get('status', 'success') == 'success'
        ):
            return tool['result']
    return None


def reported_loot(text, actual):
    if actual is None:
        return False
    compact = text.replace(',', '').lower()
    # Necessary numeric/name checks; the rubric still reviews semantics and inventions.
    return all(
        re.search(rf'(?<![\d.]){amount:g}\s*(?:`|\*|\s)*{currency}\b', compact)
        for currency, amount in actual.get('coins', {}).items()
    ) and all(item['name'].casefold() in compact for item in actual.get('items', []))


def evaluate_turn(case, record, *, annotation=None):
    tools = normalized_tools(record.get('tools', []))
    checks = case.checks
    reply = record['reply']
    text = reply.get('text', '')
    values = {'completed': float(reply.get('status') == 'completed')}

    def check(key, condition):
        values[key] = float(bool(condition))

    names = [t['name'] for t in tools]
    for name in case.expected_tools:
        check('tool_' + name, name in names)
    for name in checks.get('avoid_tools', []):
        check('avoid_' + name, name not in names)
    encounters = [t for t in tools if t['name'] in ('build_encounter', 'evaluate_encounter')]
    builds = [t for t in encounters if t['name'] == 'build_encounter']
    evaluations = [t for t in encounters if t['name'] == 'evaluate_encounter']
    # A corrected attempt may be followed by the required final calculation.
    final_encounters = [group[-1] for group in (builds, evaluations) if group]
    for field in ('party_size', 'party_level'):
        if field in checks and encounters:
            check(field, all(t['arguments'].get(field) == checks[field] for t in final_encounters))
    targets = (evaluations or builds)[-1:]
    for field in ('total_xp', 'budgets', 'exceeds_high'):
        if field in checks and targets:
            check(field, all(t['result'].get(field) == checks[field] for t in targets))
    if 'difficulty' in checks and targets:
        check(
            'difficulty',
            all(
                t['result'].get('difficulty') == checks['difficulty']
                for t in targets
                if t['result'].get('status') == 'success'
            ),
        )
    if 'monsters' in checks and evaluations:
        check(
            'exact_composition',
            all(
                composition(t['result']) == {k.casefold(): v for k, v in checks['monsters'].items()}
                for t in evaluations
            ),
        )
    if 'expected_status' in checks:
        check(
            'expected_status',
            bool(builds)
            and all(t['result'].get('status') == checks['expected_status'] for t in builds),
        )
    if 'build_expected_status' in checks:
        check(
            'build_expected_status',
            bool(builds)
            and all(t['result'].get('status') in checks['build_expected_status'] for t in builds),
        )
    if (
        builds
        and 'build_encounter' in case.expected_tools
        and 'expected_status' not in checks
        and 'build_expected_status' not in checks
    ):
        check('build_status', builds[-1]['result'].get('status') == 'success')
    if evaluations and 'evaluate_encounter' in case.expected_tools:
        check('evaluation_status', evaluations[-1]['result'].get('status') == 'success')
    for t in builds[-1:]:
        data = t['result']
        if data.get('status') != 'success':
            continue
        if 'total_count' in checks:
            check(
                'total_count',
                sum(m['count'] for m in data.get('monsters', [])) == checks['total_count'],
            )
        if 'required_monsters' in checks:
            check(
                'required_monsters',
                all(
                    composition(data).get(k.casefold()) == v
                    for k, v in checks['required_monsters'].items()
                ),
            )
        if 'habitat' in checks:
            check(
                'habitat',
                all(
                    checks['habitat'].casefold() in [h.casefold() for h in m.get('habitats', [])]
                    for m in data.get('monsters', [])
                ),
            )
        if 'creature_type' in checks:
            check(
                'creature_type',
                all(
                    checks['creature_type'].casefold()
                    in [h.casefold() for h in m.get('creature_types', [])]
                    for m in data.get('monsters', [])
                ),
            )
    if checks.get('lookup_names'):
        found = {
            m['name'].casefold()
            for t in tools
            if t['name'] == 'lookup_monsters'
            for m in t['result'].get('monsters', [])
        }
        check('lookup_names', all(n.casefold() in found for n in checks['lookup_names']))
    if 'reuse_encounter_from_turn' in checks:
        previous = actual_from_turn(
            record, checks['reuse_encounter_from_turn'], ['build_encounter', 'evaluate_encounter']
        )
        check(
            'reused_encounter',
            previous is not None
            and bool(evaluations)
            and all(composition(t['result']) == composition(previous) for t in evaluations),
        )
    if 'recall_encounter_from_turn' in checks:
        previous = actual_from_turn(
            record, checks['recall_encounter_from_turn'], ['build_encounter', 'evaluate_encounter']
        )
        check(
            'recalled_encounter_names',
            previous is not None and all(name in text.casefold() for name in composition(previous)),
        )
    loot = [t for t in tools if t['name'] == 'generate_loot' and not t['result'].get('error')]
    if 'loot' in checks:
        expected = checks['loot']
        check('loot_executed', bool(loot))
        for field in ('kind', 'count', 'party_level', 'treasure_theme', 'cr'):
            if field in expected and loot:

                def equal(t):
                    actual = t['arguments'].get(field, 1 if field == 'count' else None)
                    try:
                        return (
                            Fraction(str(actual)) == Fraction(str(expected[field]))
                            if field == 'cr'
                            else str(actual).casefold() == str(expected[field]).casefold()
                        )
                    except ValueError:
                        return False

                check('loot_' + field, all(equal(t) for t in loot))
        for t in loot:
            data = t['result']
            value = data.get('total_gp', 0)
            if 'minimum' in expected:
                check('loot_range', expected['minimum'] <= value <= expected['maximum'])
            if 'multiple_of' in expected:
                check('loot_multiple', value % expected['multiple_of'] == 0)
            if 'item_count_min' in expected:
                check(
                    'loot_item_count',
                    expected['item_count_min']
                    <= len(data.get('items', []))
                    <= expected['item_count_max'],
                )
    if checks.get('answer_matches_tool_loot'):
        check(
            'loot_amount_reported',
            bool(loot) and all(reported_loot(text, t['result']) for t in loot),
        )
    if 'recall_loot_from_turn' in checks:
        check(
            'loot_amount_recalled',
            reported_loot(
                text, actual_from_turn(record, checks['recall_loot_from_turn'], ['generate_loot'])
            ),
        )
    if checks.get('requires_observed_compaction'):
        events = record.get('events', []) + [
            e for r in record.get('history', []) for e in r.get('events', [])
        ]
        check(
            'observed_compaction',
            any(
                e.get('kind', e.get('type'))
                in ('compaction_completed', 'compacted', 'context_compacted')
                for e in events
            ),
        )
    annotation = annotation or {}
    pending = []
    method = {k: 'formal' for k in values}
    criteria = [f'rubric_{n}' for n in range(len(case.rubric))]
    if case.checks.get('history_correctness'):
        criteria.append('history_correctness')
    for key in criteria:
        review = annotation.get(key)
        if (
            review
            and review.get('value') in (0, 1)
            and review.get('method') in ('human', 'agent-assisted')
            and review.get('evidence')
        ):
            values[key] = float(review['value'])
            method[key] = review['method']
        else:
            values[key] = None
            pending.append(key)
            method[key] = 'pending'
    return Scores(values=values, pending=pending, method=method)


def evaluate_retrieval_calls(case, calls, manifest):
    if not case.evidence:
        return []
    goal = EvidenceCase(
        id='turn',
        evidence=[EvidenceFact(fact='Independent source goal', alternatives=case.evidence)],
    )
    searches = [t for t in normalized_tools(calls) if t['name'] == 'search_rules']
    return (
        [
            evaluate_question(
                goal,
                [RetrievalHit.model_validate(h) for h in t['result'].get('hits', [])],
                manifest,
            )
            for t in searches
        ]
        if searches
        else [evaluate_question(goal, [], manifest)]
    )
