"""Input-derived checks of all three books; no golden output or cached preview."""

import json
import re
from collections import Counter

import pytest

from helpers import (
    ABILITIES,
    blocks,
    check_document,
    literal_paragraphs,
    payloads,
    plain,
    tables,
    visible,
    walk,
    wrappers,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize('book_id', ['XPHB', 'XDMG', 'XMM'])
def test_complete_document_ast_and_source_map(book_id, source_books, rendered, record_property):
    source, book = source_books[book_id], rendered[book_id]
    tokens = check_document(
        book.markdown,
        book.body,
        book.source_map,
        book_id,
        source['book']['title'],
        source['upstream']['checkout_sha'],
    )
    h1 = [
        plain(tokens[i + 1])
        for i, t in enumerate(tokens)
        if t.type == 'heading_open' and t.tag == 'h1'
    ]
    assert h1 == [chapter['title'] for chapter in source['chapters']]
    assert not any(
        text in book.body
        for text in (
            '{@',
            '{#',
            '__prop',
            'json_pointer',
            '[object Object]',
            'undefined',
            '![',
            '{{',
            'summonSpellLevel',
        )
    )
    assert not re.search(r'\b(?:entity|record):[A-Za-z%]', book.body)
    for previous, current in zip(book.source_map, book.source_map[1:]):
        assert not (
            current['heading_path'] == previous['heading_path'] + [previous['heading_path'][-1]]
        )
    assert book.diagnostics.counts['source_insertions'] == len(wrappers(source))
    for name, value in (
        ('headings', len(book.source_map)),
        ('chapters', len(h1)),
        ('tables', len(tables(tokens))),
    ):
        record_property(name, value)


def test_exact_four_artifacts_jsonl_and_manifest_order(corpus, source_books):
    assert set(corpus.files) == {'xphb.md', 'xdmg.md', 'xmm.md', 'source_map.jsonl'}
    assert all(type(raw) is bytes and raw and raw.endswith(b'\n') for raw in corpus.files.values())
    assert [book.book_id for book in corpus.books] == list(source_books)
    records = [
        json.loads(line)
        for line in corpus.files['source_map.jsonl'].decode('utf-8').split('\n')[:-1]
    ]
    assert records == [record for book in corpus.books for record in book.source_map]
    for book in corpus.books:
        assert corpus.files[book.book_id.lower() + '.md'].decode('utf-8') == book.markdown


@pytest.mark.parametrize('book_id', ['XPHB', 'XDMG', 'XMM'])
def test_every_component_has_an_evidenced_decision(
    book_id, source_books, rendered, record_property
):
    source, book = source_books[book_id], rendered[book_id]
    components = {
        e['entity_id']: e
        for e in source['domain']['entities']
        if e['representation'] == 'domain_component'
    }
    assert book.diagnostics.components.keys() == components.keys()
    allowed = {
        'rendered',
        'rendered_in_parent',
        'metadata_only',
        'already_represented',
        'template_expanded',
        'native_derivation',
        'source_preferred',
    }
    for key, decision in book.diagnostics.components.items():
        assert decision['prop'] == components[key]['prop'] and decision['decision'] in allowed
        assert decision.get('reason') or decision.get('parent')
        if decision['decision'] == 'metadata_only':
            data = components[key]['data']
            assert not data.get('entries')  # Category label or image-only fluff, not prose.
            prop = components[key]['prop']
            assert prop.endswith('Fluff') or prop in {
                'itemType',
                'itemProperty',
                'itemMastery',
                'language',
            }
            if prop == 'language':
                assert set(data) <= {'name', 'source', 'page', '__prop', 'typicalSpeakers'}
                assert all(speaker.startswith('{@creature ') for speaker in data['typicalSpeakers'])
        if decision['decision'] == 'source_preferred':
            assert decision['conflict'] and decision['coverage'] and decision['source_anchor']
            assert any(
                note['code'] == 'DOMAIN_SOURCE_CONFLICT' and note['entity'] == key
                for note in book.diagnostics.messages
            )
    for note in book.diagnostics.messages:
        if note['code'] == 'DOMAIN_SOURCE_CONFLICT':
            assert book.diagnostics.components[note['entity']]['decision'] == 'source_preferred'
            assert note.get('fields') or note['catalog_clause'] != note['book_clause']
        else:
            assert note['code'] == 'GROUPED_TABLE_HEADER'
    record_property('components', len(components))


@pytest.mark.parametrize('book_id', ['XPHB', 'XDMG', 'XMM'])
def test_all_statblocks_scores_saves_passive_and_damage_formulas(
    book_id, source_books, rendered, record_property
):
    expected = payloads(source_books[book_id], 'monster')
    by_name = {}
    for data in expected:
        by_name.setdefault(data['name'], []).append(data)
    observed = Counter()
    formulas = 0
    for block in blocks(rendered[book_id].body):
        first = next((plain(token) for token in block if token.type == 'inline'), '')
        if first not in by_name:
            continue
        candidates = by_name[first]
        # A real repeated insertion need not be globally deduplicated. For distinct
        # same-name versions, use their source occurrence order.
        data = candidates[observed[first]]
        observed[first] += 1
        score_tables = [
            t for t in tables(block) if t[0] == ['', 'STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']
        ]
        assert len(score_tables) == 1, first
        mods = {a: (data[a] - 10) // 2 for a in ABILITIES}
        assert score_tables[0] == [
            ['', *[a.upper() for a in ABILITIES]],
            ['Score', *[str(data[a]) for a in ABILITIES]],
            ['Mod', *[f'{mods[a]:+d}' for a in ABILITIES]],
            ['Save', *[data.get('save', {}).get(a, f'{mods[a]:+d}') for a in ABILITIES]],
        ], first
        text = ' '.join(plain(token) for token in block if token.type == 'inline')
        assert f'Passive Perception {data["passive"]}' in text, first
        for key in ('trait', 'action', 'bonus', 'reaction', 'legendary'):
            label = {
                'trait': 'Traits',
                'action': 'Actions',
                'bonus': 'Bonus Actions',
                'reaction': 'Reactions',
                'legendary': 'Legendary Actions',
            }[key]
            if data.get(key):
                assert label in text
            for action in data.get(key, []):
                for entry in action.get('entries', []):
                    if isinstance(entry, str):
                        for formula in re.findall(r'\{@(?:dice|damage) ([^{}|]+)\}', entry):
                            assert (
                                formula.replace('summonSpellLevel', "the spell's level").replace(
                                    ';', '/'
                                )
                                in text
                            ), (first, formula)
                            formulas += 1
    assert observed == Counter(data['name'] for data in expected)
    record_property('statblocks', sum(observed.values()))
    record_property('damage_formulas', formulas)


@pytest.mark.parametrize('book_id', ['XPHB', 'XDMG', 'XMM'])
def test_literal_source_table_rows_are_retained(book_id, source_books, rendered, record_property):
    def normalize(row):
        cells = [str(c) for c in row]
        while cells and not cells[-1]:
            cells.pop()
        return tuple(cells)

    expected = Counter()
    for node in walk(source_books[book_id]['chapters']):
        if not isinstance(node, dict) or node.get('type') != 'table':
            continue
        for row in node.get('rows', []):
            row = row.get('row') if isinstance(row, dict) else row
            if isinstance(row, list) and all(
                isinstance(c, (str, int)) and '{@' not in str(c) and '\n' not in str(c) for c in row
            ):
                expected[normalize(row)] += 1
    observed = Counter(
        normalize(row) for table in tables(rendered[book_id].body) for row in table[1:]
    )
    assert expected
    assert not expected - observed
    record_property('literal_source_rows', sum(expected.values()))


def test_individual_monster_lore_precedes_its_statblock(source_books, rendered, record_property):
    """Check literal individual prose without implementing the inline renderer."""
    sections_checked = paragraphs_checked = 0

    for book_id, source in source_books.items():
        book = rendered[book_id]
        entities = {entity['entity_id']: entity for entity in source['domain']['entities']}
        inserted = {wrapper['occurrence_id']: wrapper['data'] for wrapper in wrappers(source)}
        for entity in entities.values():
            if entity['representation'] != 'domain_component' or entity['prop'] != 'monsterFluff':
                continue
            parent = entities.get(entity['canonical_placement']['parent_entity_id'])
            if parent is None or parent['prop'] != 'monster':
                continue
            expected = list(
                literal_paragraphs(
                    entity['data'], {item['path'] for item in entity.get('shared_content', [])}
                )
            )
            if not expected:
                continue
            parent_data = (
                parent['data']
                if parent['representation'] == 'domain_component'
                else inserted[parent['occurrence_id']]
            )
            name = parent_data['name']
            chapter = source['chapters'][parent['canonical_placement']['anchor']['chapter_index']][
                'title'
            ]
            records = [
                record
                for record in book.source_map
                if record['heading_path'][0] == chapter and record['heading_path'][-1] == name
            ]
            assert records, (book_id, name, 'individual section missing')
            for record in records:
                text = book.body[record['start_char'] : record['end_char']]
                statblocks = [
                    block
                    for block in blocks(text)
                    if next((plain(token) for token in block if token.type == 'inline'), '') == name
                    and any(
                        table[0] == ['', 'STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA']
                        for table in tables(block)
                    )
                ]
                assert len(statblocks) == 1, (book_id, name, 'one complete statblock expected')
                prefix = visible('\n'.join(text.split('\n')[: statblocks[0][0].map[0]]))
                for paragraph, count in Counter(expected).items():
                    assert prefix.count(paragraph) >= count, (book_id, name, paragraph)
                sections_checked += 1
                paragraphs_checked += len(expected)
    assert sections_checked and paragraphs_checked
    record_property('individual_lore_sections', sections_checked)
    record_property('individual_literal_paragraphs', paragraphs_checked)
