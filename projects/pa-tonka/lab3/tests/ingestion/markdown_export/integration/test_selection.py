"""Source-owned rules, exact field coverage and retained domain supplements."""

import re

import pytest

from helpers import literal_fragments, section, tables, visible, walk, wrappers

pytestmark = pytest.mark.integration


def source_prose(value):
    """Independent oracle for the simple tags in these source paragraphs."""

    def replace(match):
        tag, arguments = match[1], match[2].split('|')
        if tag == 'dc':
            return 'DC ' + arguments[0]
        if tag in ('dice', 'damage'):
            return arguments[0]
        assert tag in ('variantrule', 'spell', 'book', 'reward'), tag
        index = 3 if tag == 'book' else 2
        return arguments[index] if len(arguments) > index else arguments[0]

    result = re.sub(r'\{@(\w+) ([^{}]+)\}', replace, value)
    assert '{@' not in result
    return result


def test_explosives_use_source_table_and_each_complete_rule_once(source_books, rendered):
    source, book = source_books['XDMG'], rendered['XDMG']
    original = next(
        node
        for node in walk(source['chapters'])
        if isinstance(node, dict) and node.get('name') == 'Explosives'
    )
    text = section(book, 'Explosives')
    shown = visible(text)
    source_table = next(
        node
        for node in original['entries']
        if isinstance(node, dict) and node.get('type') == 'table'
    )
    assert tables(text) == [
        [
            source_table['colLabels'],
            *[
                [
                    re.sub(
                        r'\{@item ([^{}]+)\}',
                        lambda m: (
                            m[1].split('|')[2] if len(m[1].split('|')) > 2 else m[1].split('|')[0]
                        ),
                        cell,
                    )
                    for cell in row
                ]
                for row in source_table['rows']
            ],
        ]
    ]
    for rule in original['entries']:
        if isinstance(rule, dict) and rule.get('type') == 'entries':
            for paragraph in rule['entries']:
                assert shown.count(source_prose(paragraph)) == 1, rule['name']
    assert '10 (3d6) Fire damage (for a powder horn) or 24 (7d6) Fire damage (for a keg)' in shown
    assert 'An an action' not in shown
    assert '**Price:**' not in text and '**Weight:**' not in text
    source_names = {
        rule['name']
        for rule in original['entries']
        if isinstance(rule, dict) and rule.get('type') == 'entries'
    }
    records = [
        r
        for r in book.source_map
        if 'Explosives' in r['heading_path'] and r['heading_path'][-1] != 'Explosives'
    ]
    assert {r['heading_path'][-1] for r in records} == source_names
    assert len(records) == len(source_names)


def test_facility_rewards_keep_complete_effects_and_conditions_without_catalog_copy(
    source_books, rendered
):
    source, book = source_books['XDMG'], rendered['XDMG']
    insertions = {wrapper['entity_id']: wrapper['data'] for wrapper in wrappers(source)}
    rewards = [
        entity
        for entity in source['domain']['entities']
        if entity['representation'] == 'domain_component'
        and entity['canonical_placement']['relation'] == 'facility_reward'
    ]
    assert rewards
    for entity in rewards:
        parent = insertions[entity['canonical_placement']['parent_entity_id']]
        text = section(book, parent['name'])
        shown = visible(text)
        original = next(
            rule
            for rule in parent['entries']
            if isinstance(rule, dict) and rule.get('name') == entity['data']['name']
        )
        for paragraph in original['entries']:
            assert shown.count(source_prose(paragraph)) == 1
        assert '7 days or until you use it' in shown
        assert "You can't gain this Charm again while you still have it." in shown
        assert 'Additional Spells:' not in shown and 'Related Facilities:' not in shown
        decision = book.diagnostics.components[entity['entity_id']]
        assert decision['decision'] == 'already_represented'
        assert set(decision['coverage']) == {
            'entries',
            'type',
            'seeAlsoFacility',
            'additionalSpells',
        }


@pytest.mark.parametrize('book_id', ['XPHB', 'XDMG', 'XMM'])
def test_original_chapter_prose_remains_in_each_original_part(book_id, source_books, rendered):
    for chapter in source_books[book_id]['chapters']:
        shown = ' '.join(visible(section(rendered[book_id], chapter['title'])).split())
        for fragment in literal_fragments(chapter['content']):
            assert ' '.join(fragment.split()) in shown, (book_id, chapter['title'], fragment)


def test_speaker_indexes_do_not_become_monster_book_rules(source_books, rendered):
    source, book = source_books['XMM'], rendered['XMM']
    indexes = [
        entity
        for entity in source['domain']['entities']
        if entity['representation'] == 'domain_component'
        and entity['prop'] == 'language'
        and set(entity['data']) == {'name', 'source', 'page', '__prop', 'typicalSpeakers'}
    ]
    assert indexes
    for entity in indexes:
        decision = book.diagnostics.components[entity['entity_id']]
        assert decision['decision'] == 'metadata_only'
    assert 'Typical Speakers:' not in book.body
    conversions = section(book, 'Monster Conversions')
    assert 'Bullywug' in conversions and 'Gnoll' in conversions
    assert not any(
        r['heading_path'][-1] in ('Bullywug', 'Gnoll')
        and 'Monster Conversions' in r['heading_path']
        for r in book.source_map
    )
