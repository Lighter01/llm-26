"""Spell numeric rules and book membership, checked independently of formatters."""

import re

import pytest

from helpers import section, visible, walk, wrappers

pytestmark = pytest.mark.integration


def spell_sections(source, book):
    for wrapper in wrappers(source, 'spell'):
        chapter = source['chapters'][wrapper['placement']['chapter_index']]['title']
        data = wrapper['data']
        yield data, section(book, data['name'], ancestor=chapter)


@pytest.mark.parametrize(
    ('book_id', 'heading', 'spell'),
    [
        ('XPHB', 'Using a Higher-Level Spell Slot', 'Magic Missile'),
        ('XPHB', 'Combining Spell Effects', 'Bless'),
        ('XDMG', 'Abilities, Strengths, and Weaknesses', 'Fire Bolt'),
        ('XDMG', 'Bestow Curse', 'Bestow Curse'),
        ('XDMG', 'Cursed Creatures', 'Remove Curse'),
        ('XDMG', 'Divine Knowledge', 'Commune'),
        ('XDMG', 'Feywild Magic', 'Wish'),
    ],
)
def test_source_spell_references_preserve_italics_in_complete_paragraphs(
    book_id, heading, spell, source_books, rendered
):
    nodes = [
        node
        for node in walk(source_books[book_id]['chapters'])
        if isinstance(node, dict)
        and node.get('type') in ('entries', 'section')
        and node.get('name') == heading
    ]
    assert len(nodes) == 1
    reference = re.compile(r'\{@(?:spell|i) ' + re.escape(spell) + r'(?:[|}])')
    paragraphs = [
        node for node in walk(nodes[0]) if isinstance(node, str) and reference.search(node)
    ]
    assert paragraphs
    text = section(rendered[book_id], heading)
    for paragraph in paragraphs:

        def display(match):
            tag, arguments = match.groups()
            parts = arguments.split('|')
            name = parts[2] if len(parts) > 2 and parts[2] else parts[0]
            return '*' + name + '*' if tag in ('spell', 'i') else name

        # These source paragraphs use simple spell/style tags and creature names.
        expected = re.sub(r'\{@(spell|i|creature) ([^{}]+)\}', display, paragraph)
        assert '{@' not in expected, 'Source grammar needs review'
        assert expected in text


def test_all_source_scaled_sentences_keep_their_display_values(
    source_books, rendered, record_property
):
    # Current corpus sentences use non-nested scaled tags and otherwise literal prose.
    # New source grammar must be reviewed rather than silently escaping this oracle.
    pattern = re.compile(r'\{@(?:scaledice|scaledamage) ([^{}]+)\}')
    checked = 0
    for book_id, source in source_books.items():
        for data, fragment in spell_sections(source, rendered[book_id]):
            text = visible(fragment)
            for node in walk([data['entries'], data.get('entriesHigherLevel', [])]):
                if not isinstance(node, str):
                    continue
                matches = list(pattern.finditer(node))
                assert len(matches) == node.count('{@scaledice ') + node.count('{@scaledamage ')
                if not matches:
                    continue

                def display(match):
                    parts = match[1].split('|')
                    assert 3 <= len(parts) <= 5
                    return parts[4] if len(parts) == 5 and parts[4] else parts[2]

                expected = pattern.sub(display, node)
                assert '{@' not in expected, (data['name'], 'source grammar needs review')
                assert expected in text, (book_id, data['name'], expected)
                checked += len(matches)
    assert checked
    record_property('scaled_occurrences', checked)


@pytest.mark.parametrize(
    ('name', 'rule'),
    [
        ('Fireball', 'The damage increases by 1d6 for each spell slot level above 3.'),
        ('Burning Hands', 'The damage increases by 1d6 for each spell slot level above 1.'),
        ('Lightning Bolt', 'The damage increases by 1d6 for each spell slot level above 3.'),
        ('Thunderwave', 'The damage increases by 1d8 for each spell slot level above 1.'),
        ('Heal', 'The healing increases by 10 for each spell slot level above 6.'),
        ('Cure Wounds', 'The healing increases by 2d8 for each spell slot level above 1.'),
        ('Healing Word', 'The healing increases by 2d4 for each spell slot level above 1.'),
    ],
)
def test_representative_spell_increments(name, rule, source_books, rendered):
    text = next(
        text
        for data, text in spell_sections(source_books['XPHB'], rendered['XPHB'])
        if data['name'] == name
    )
    assert rule in visible(text)
    if name == 'Fireball':
        assert '**Classes:** Sorcerer, Wizard\n' in text
        assert 'taking 8d6 Fire damage' in visible(text)


def test_spell_classes_match_book_identities_without_access_dumps(
    source_books, rendered, record_property
):
    checked = 0
    for book_id, source in source_books.items():
        book_classes = {
            (wrapper['data']['name'].casefold(), wrapper['data']['source'].casefold())
            for wrapper in wrappers(source, 'class')
        }
        for data, text in spell_sections(source, rendered[book_id]):
            main = data.get('classes', {}).get('fromClassList', [])
            expected = sorted(
                {
                    reference['name']
                    for reference in main
                    if (reference['name'].casefold(), reference['source'].casefold())
                    in book_classes
                    and reference.get('definedInSource', book_id).casefold() == book_id.casefold()
                },
                key=str.casefold,
            )
            lines = re.findall(r'^\*\*Classes:\*\* (.+)$', text, re.M)
            assert lines == ([', '.join(expected)] if expected else []), data['name']
            assert not re.search(
                r'^\*\*(?:Spell Lists and Subclass Access|Species Access|Background Access|'
                r'Feat Access|Feature Access|Reward Access):',
                text,
                re.M,
            ), data['name']
            checked += 1
    assert checked
    record_property('spell_class_lists', checked)
