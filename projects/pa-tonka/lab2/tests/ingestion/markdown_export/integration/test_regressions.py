"""Representative snapshot regressions, expectations read from resolved payloads."""

import re
from collections import Counter
from fractions import Fraction

import pytest

from helpers import (
    literal_fragments,
    literal_paragraphs,
    payloads,
    section,
    tables,
    visible,
    walk,
    wrappers,
)

pytestmark = pytest.mark.integration


def named(source, prop, name):
    return next(data for data in payloads(source, prop) if data['name'] == name)


@pytest.mark.parametrize('group', ['Blue Dragons', 'Kobolds'])
def test_group_lore_and_source_defined_variants(group, source_books, rendered):
    source, book = source_books['XMM'], rendered['XMM']
    source_group = next(
        node
        for node in walk(source['chapters'])
        if isinstance(node, dict) and node.get('name') == group
    )
    variants = Counter(
        wrapper['data']['name'] for wrapper in wrappers({'chapters': [source_group]}, 'monster')
    )
    assert variants
    group_text = section(book, group)
    group_visible = visible(group_text)
    group_fluff = named(source, 'monsterFluff', group)
    for paragraph in literal_paragraphs(group_fluff['entries']):
        assert group_visible.count(paragraph) == 1
    for variant, count in variants.items():
        records = [r for r in book.source_map if r['heading_path'][-2:] == [group, variant]]
        assert len(records) == count
        assert group_text.count('> **' + variant + '**') == count
    if group == 'Blue Dragons':
        habitat = next(
            node
            for node in walk(group_fluff['entries'])
            if isinstance(node, dict) and node.get('name') == 'Habitat:'
        )
        expected_habitats = re.findall(r'\{@filter ([^|}]+)', habitat['entry']) or [
            habitat['entry']
        ]
        habitat_line = next(
            line for line in group_visible.split('\n') if line.startswith('Habitat:')
        )
        assert all(value in habitat_line for value in expected_habitats)
        lairs = [
            node['name']
            for node in walk(group_fluff['entries'])
            if isinstance(node, dict)
            and node.get('type') in ('entries', 'section')
            and node.get('name')
            and node['name'] != group
        ]
        assert lairs
        assert '#### Regional Effects\n' in group_text
        for lair in lairs:
            assert group_text.index('### ' + lair) > max(
                group_text.index('> **' + name + '**') for name in variants
            )


def test_goristro_complete_mechanics(source_books, rendered):
    data = named(source_books['XMM'], 'monster', 'Goristro')
    text = section(rendered['XMM'], 'Goristro')
    initiative = data.get('initiative', {})
    bonus = (data['dex'] - 10) // 2
    mode = None
    if isinstance(initiative, int):
        bonus = initiative
    else:
        mode = initiative.get('advantageMode')
        if 'initiative' in initiative:
            bonus = initiative['initiative']
        elif initiative.get('proficiency'):
            cr = data['cr']['cr'] if isinstance(data['cr'], dict) else data['cr']
            proficiency = max(2, 2 + (Fraction(cr) - 1) // 4)
            bonus += initiative['proficiency'] * proficiency
    score = 10 + bonus + {'adv': 5, 'dis': -5}.get(mode, 0)
    assert f'**Initiative:** {bonus:+d} ({score})' in text
    shown = visible(text)
    for skill, value in data.get('skill', {}).items():
        assert f'{skill.capitalize()} {value}' in shown
    assert not any(
        r['heading_path'][-1] in {'Actions', 'Traits', 'Bonus Actions', 'HP', 'STR'}
        for r in rendered['XMM'].source_map
        if 'Goristro' in r['heading_path']
    )


def test_aeromancer_spellcasting_reactions_and_shared_lore(source_books, rendered):
    source, book = source_books['XMM'], rendered['XMM']
    group_text = section(book, 'Aarakocra')
    group_visible = visible(group_text)
    text = section(book, 'Aarakocra Aeromancer')
    common = list(literal_paragraphs(named(source, 'monsterFluff', 'Aarakocra')['entries']))
    assert common
    for paragraph in common:
        assert group_visible.count(paragraph) == 1
    assert '### Aarakocra Aeromancer' in group_text
    data = named(source, 'monster', 'Aarakocra Aeromancer')
    for reaction in data.get('reaction', []):
        assert reaction['name'] in text
    reaction_spells = [
        spell for spell in data['spellcasting'] if spell.get('displayAs') == 'reaction'
    ]
    assert reaction_spells and '> **Reactions**' in text
    for spell in data['spellcasting']:
        assert spell['name'] in text
        for refs in spell.get('daily', {}).values():
            for ref in refs:
                assert re.search(r'\{@spell ([^|}]+)', ref).group(1) in text


def test_gray_oozes_preserve_source_duplicates_and_domain_addition(source_books, rendered):
    source = source_books['XMM']
    text = section(rendered['XMM'], 'Gray Oozes')
    count = sum(w['data']['name'] == 'Gray Ooze' for w in wrappers(source, 'monster'))
    assert count > 1 and text.count('> **Gray Ooze**') == count
    additions = [
        e
        for e in source['domain']['entities']
        if e['representation'] == 'domain_component'
        and e['prop'] == 'monster'
        and e['data']['name'] == 'Psychic Gray Ooze'
    ]
    assert additions and text.count('> **Psychic Gray Ooze**') == len(additions)


@pytest.mark.parametrize('name', ['Aboleth', 'Adult Black Dragon'])
def test_legendary_actions_and_regional_effects_follow_available_fields(
    name, source_books, rendered
):
    source, book = source_books['XMM'], rendered['XMM']
    data = named(source, 'monster', name)
    text = section(book, name)
    assert '> **Legendary Actions**' in text
    for action in data['legendary']:
        assert action['name'].split(' (')[0] in text
    assert ('**Bonus Actions**' in text) == bool(data.get('bonus'))
    group = data['legendaryGroup']['name']
    effects = named(source, 'legendaryGroup', group)
    containing = section(book, 'Black Dragons') if name == 'Adult Black Dragon' else text
    for field, title in (('regionalEffects', 'Regional Effects'), ('lairActions', 'Lair Actions')):
        if effects.get(field):
            assert title in containing
            for paragraph in literal_paragraphs(effects[field]):
                assert paragraph in visible(containing)


def test_class_progression_all_subclasses_and_frenzy_once(source_books, rendered):
    source, book = source_books['XPHB'], rendered['XPHB']
    barbarian = section(book, 'Barbarian')
    barbarian_visible = visible(barbarian)
    data = named(source, 'class', 'Barbarian')
    progression = next(t for t in tables(barbarian) if t[0][:2] == ['Level', 'Proficiency Bonus'])
    rows = data['classTableGroups'][0]['rows']
    assert len(progression) == len(rows) + 1
    for i, row in enumerate(rows, 1):
        assert progression[i][0] == str(i)
        assert progression[i][-len(row) :] == [
            f'{v["value"]:+d}' if isinstance(v, dict) and v['type'] == 'bonus' else str(v)
            for v in row
        ]
    subclasses = payloads(source, 'subclass')
    assert subclasses
    for subclass in subclasses:
        assert any(
            r['heading_path'][-1] == subclass['name']
            and subclass['className'] in r['heading_path'][:-1]
            for r in book.source_map
        ), subclass['name']
    frenzy = named(source, 'subclassFeature', 'Frenzy')
    prefix = frenzy['entries'][0].split('{@', 1)[0]
    assert prefix and barbarian_visible.count(prefix) == 1
    assert (
        len(
            [
                r
                for r in book.source_map
                if 'Barbarian' in r['heading_path'] and r['heading_path'][-1] == 'Level 3: Frenzy'
            ]
        )
        == 1
    )


def test_agonizing_blast_structured_prerequisite_and_repeatable(source_books, rendered):
    data = named(source_books['XPHB'], 'optionalfeature', 'Agonizing Blast')
    text = section(rendered['XPHB'], 'Agonizing Blast')
    shown = visible(text)
    prerequisite = data['prerequisite'][0]
    assert prerequisite['spell'][0]['entry'] in text
    assert (
        f'{prerequisite["level"]["class"]["name"]} Level {prerequisite["level"]["level"]}' in text
    )
    assert ('**Repeatable:** Yes' in text) == data.get('repeatable', False)
    assert all(fragment in shown for fragment in literal_fragments(data['entries']))


@pytest.mark.parametrize('name', ['Blessed Warrior', 'Druidic Warrior'])
def test_inline_fighting_styles_keep_canonical_prerequisites(name, source_books, rendered):
    data = named(source_books['XPHB'], 'feat', name)
    text = visible(section(rendered['XPHB'], name))
    assert data['prerequisite'][0]['otherSummary']['entry'] in text
    assert 'Category: Fighting Style' in text and 'FS:' not in text


def test_inline_metamagic_keeps_canonical_feature_type(source_books, rendered):
    options = [
        data
        for data in payloads(source_books['XPHB'], 'optionalfeature')
        if data.get('featureType') == ['MM']
    ]
    assert options
    for data in options:
        assert 'Feature Type: Metamagic' in visible(section(rendered['XPHB'], data['name']))


def test_summon_spirit_placement_and_symbolic_mechanics(source_books, rendered):
    source, book = source_books['XPHB'], rendered['XPHB']
    data = named(source, 'monster', 'Aberrant Spirit')
    text = section(book, 'Summon Aberration')
    assert text.count('> **Aberrant Spirit**') == 1
    assert data['hp']['special'] in text
    for ac in data['ac']:
        assert ac['special'] in text
    assert "the spell's level" in text and 'Using a Higher-Level Spell Slot' in text
    assert any(
        r['heading_path'][-2:] == ['Summon Aberration', 'Aberrant Spirit'] for r in book.source_map
    )


def test_plant_growth_casting_time_notes_are_preserved(source_books, rendered):
    data = named(source_books['XPHB'], 'spell', 'Plant Growth')
    text = section(rendered['XPHB'], 'Plant Growth')
    for time in data['time']:
        if time.get('note'):
            assert '(' + time['note'] + ')' in text


def test_ape_page_comes_from_phb_placement(source_books, rendered):
    source = source_books['XPHB']
    wrapper = next(w for w in wrappers(source, 'monster') if w['data']['name'] == 'Ape')
    entity = next(e for e in source['domain']['entities'] if e['entity_id'] == wrapper['entity_id'])
    record = next(r for r in rendered['XPHB'].source_map if r['heading_path'][-1] == 'Ape')
    assert record['printed_pages'] == [
        entity['canonical_placement']['anchor']['origin']['printed_page']
    ]
    assert record['printed_pages'] != [wrapper['data']['page']]
    assert record['page_attribution'] == 'inherited_section_start'


@pytest.mark.parametrize('name', ['Bag of Holding', 'Black Dragon Scale Mail'])
def test_dmg_items_full_processed_entries_and_properties(name, source_books, rendered):
    data = named(source_books['XDMG'], 'item', name)
    text = section(rendered['XDMG'], name)
    shown = visible(text)
    for fragment in literal_fragments(data.get('_fullEntries', data.get('entries', []))):
        assert fragment in shown
    assert f'**Weight:** {data["weight"]} lb.' in text
    if data.get('reqAttune'):
        assert '**Attunement:** Required' in text
    if 'ac' in data:
        assert f'**Base AC:** {data["ac"]}' in text
    if data.get('stealth'):
        assert 'Disadvantage on Dexterity (Stealth)' in shown
    if data.get('resist'):
        resistances = next(line for line in shown.split('\n') if line.startswith('Resistances:'))
        for damage in data['resist']:
            assert damage.title() in resistances
    capacity = data.get('containerCapacity', {})
    capacity_text = next((line for line in shown.split('\n') if line.startswith('Capacity:')), '')
    for field, unit in (('weight', 'lb.'), ('volume', 'cubic feet')):
        for value in capacity.get(field, []):
            assert f'{value} {unit}' in capacity_text
    if capacity.get('weightless'):
        assert 'contents add no weight' in capacity_text


def test_bastions_glossary_appendices_keep_text_and_structure(source_books, rendered):
    source, book = source_books['XDMG'], rendered['XDMG']
    for name in (
        'Chapter 8: Bastions',
        'Appendix A: Lore Glossary',
        'Appendix B: Maps',
        'Appendix C: Tracking Sheets',
    ):
        text = section(book, name)
        assert text.startswith('#')
        if name == 'Chapter 8: Bastions':
            assert tables(text)
        chapter = next(c for c in source['chapters'] if c['title'] == name)
        shown = visible(text)
        paragraphs = list(literal_paragraphs(chapter['content']))
        if name == 'Appendix A: Lore Glossary':
            assert paragraphs
        for paragraph in paragraphs:
            assert paragraph in shown
        for fragment in literal_fragments(chapter['content']):
            assert fragment in shown
    assert '![' not in book.body


def test_special_trap_duration_keeps_its_stopping_condition(source_books, rendered):
    data = named(source_books['XDMG'], 'trap', 'Rolling Stone')
    text = section(rendered['XDMG'], 'Rolling Stone')
    assert data['duration'][0]['condition'] in text
