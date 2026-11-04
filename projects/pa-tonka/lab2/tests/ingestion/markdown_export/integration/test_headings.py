"""Semantic heading boundaries, with source-defined text and typed entities."""

import re
from collections import Counter

import pytest

from helpers import literal_fragments, section, visible, walk, wrappers

pytestmark = pytest.mark.integration


def test_class_overviews_are_labels_and_full_classes_keep_their_headings(source_books, rendered):
    source, book = source_books['XPHB'], rendered['XPHB']
    classes = wrappers(source, 'class')
    chapter = source['chapters'][classes[0]['placement']['chapter_index']]
    chapter_text = section(book, chapter['title'])
    intro = chapter_text.split('\n## ', 1)[0]
    overviews = [
        node
        for node in walk(chapter['content'])
        if isinstance(node, dict)
        and node.get('type') == 'entries'
        and node.get('name', '').startswith('{@class ')
    ]
    assert Counter(re.match(r'\{@class ([^|}]+)', n['name'])[1] for n in overviews) == Counter(
        w['data']['name'] for w in classes
    )
    for wrapper in classes:
        name = wrapper['data']['name']
        assert '***' + name + '.***' in intro
        assert sum(r['heading_path'] == [chapter['title'], name] for r in book.source_map) == 1
    for node in overviews:
        for fragment in literal_fragments(node):
            assert fragment in visible(intro)


def test_rage_keeps_feature_heading_and_inline_rules(source_books, rendered):
    source, book = source_books['XPHB'], rendered['XPHB']
    barbarian = next(
        w['data'] for w in wrappers(source, 'class') if w['data']['name'] == 'Barbarian'
    )
    rage = next(f for group in barbarian['classFeatures'] for f in group if f['name'] == 'Rage')
    title = f'Level {rage["level"]}: Rage'
    text = section(book, title, ancestor='Barbarian')
    assert text.startswith('### ' + title + '\n')
    names = [
        n['name']
        for n in walk(rage['entries'])
        if isinstance(n, dict) and n.get('type') == 'entries' and n.get('name')
    ]
    assert names
    for name in names:
        assert '***' + name + '.***' in text
        assert not any(r['heading_path'][-2:] == [title, name] for r in book.source_map)
    assert (
        '***Damage Resistance.*** You have Resistance to Bludgeoning, Piercing, and Slashing damage.'
        in text
    )
    for fragment in literal_fragments(rage):
        assert fragment in visible(text)


def test_facility_rule_labels_keep_effects_craft_lists_and_source_text(source_books, rendered):
    source, book = source_books['XDMG'], rendered['XDMG']
    labels_checked = 0
    for wrapper in wrappers(source, 'facility'):
        data = wrapper['data']
        chapter = source['chapters'][wrapper['placement']['chapter_index']]['title']
        text = section(book, data['name'], ancestor=chapter)
        for node in walk(data.get('entries', [])):
            if not isinstance(node, dict) or node.get('type') != 'entries' or not node.get('name'):
                continue
            assert '***' + node['name'] + '.***' in text, data['name']
            labels_checked += 1
        for fragment in literal_fragments(data):
            assert fragment in visible(text), (data['name'], fragment)
    assert labels_checked
    arcane = section(book, 'Arcane Study')
    assert '***Arcane Study Charm.*** After spending a Long Rest' in arcane
    assert '***Craft Options.*** When you issue the Craft order' in arcane
    assert 'lasts for 7 days or until you use it' in arcane
    assert 'cast *Identify* without expending a spell slot or using Material components' in arcane
    assert '- **Craft:** Arcane Focus.' in arcane


@pytest.mark.parametrize('book_id', ['XPHB', 'XDMG', 'XMM'])
def test_explicit_source_sections_keep_structural_headings(book_id, source_books, rendered):
    expected = set()
    for node in walk(source_books[book_id]['chapters']):
        if not isinstance(node, dict) or node.get('type') != 'section' or not node.get('name'):
            continue
        children = node.get('entries', [])
        match = re.fullmatch(r'.+ \(([A-Z])\)', node['name'])
        navigation = (
            match
            and children
            and all(
                isinstance(child, dict)
                and child.get('type') == 'section'
                and child.get('name', '')[:1].upper() == match[1]
                for child in children
            )
        )
        if not navigation and '{@' not in node['name']:
            expected.add(node['name'])
    assert expected
    assert expected <= {r['heading_path'][-1] for r in rendered[book_id].source_map}
