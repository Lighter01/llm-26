import pytest

from dnd_rag.ingestion.markdown_export import ExportError, render_book
from helpers import MARKDOWN, add_entity, check_document, empty_book, tables, visible


def test_lists_quotes_insets_images_and_options(fixture_data):
    result = render_book(empty_book(entries=fixture_data('entries')))
    tokens = MARKDOWN.parse(result.body)
    ordered = next(t for t in tokens if t.type == 'ordered_list_open')
    assert ordered.attrGet('start') == 3
    assert sum(t.type == 'bullet_list_open' for t in tokens) == 2
    assert sum(t.type == 'blockquote_open' for t in tokens) == 2
    assert 'Choose 2 of the following options:' in visible(result.body)
    assert '**Prerequisite:** Level 3' in result.body
    assert '— A Reader, *Old Tome*' in result.body
    assert 'Text after images.' in result.body
    assert not any(
        value in result.body
        for value in ('unavailable.webp', 'example.invalid', 'No invented caption', '![')
    )
    assert [r['heading_path'][-1] for r in result.source_map] == ['First Part', 'Options']


def test_grouped_table_keeps_spans_cells_footnotes_and_dice(fixture_data):
    result = render_book(empty_book(entries=fixture_data('entries')))
    parsed = tables(result.body)
    assert parsed == [
        [
            ['Roll', 'Result', 'Notes'],
            ['01–09', 'a | b', 'Line 1.<br><br>Line 2.'],
            ['10', '', 'Wide note'],
        ],
        [['Bonus', 'Speed', 'Dice'], ['+2', '+10 ft.', '2d6 +3']],
    ]
    assert 'Column groups: Checks (2 columns); Notes.' in result.body
    assert result.body.index('Before the table.') < result.body.index('| Roll |')
    assert (
        result.body.index('| 10 |')
        < result.body.index('Footnote retained.')
        < result.body.index('After the table.')
    )
    assert result.body.count(r'a \| b') == 1
    assert [m['code'] for m in result.diagnostics.messages] == ['GROUPED_TABLE_HEADER']


def test_heading_syntax_in_literal_paragraph_does_not_create_phantom_map():
    result = render_book(empty_book(entries=['# Literal heading syntax']))
    assert len(result.source_map) == 1
    assert sum(t.type == 'heading_open' for t in MARKDOWN.parse(result.body)) == 1
    assert '# Literal heading syntax' in visible(result.body)


@pytest.mark.parametrize(
    'text', ['Literal title\n---', 'Literal title\n===', 'Literal title\n  ---', '---']
)
def test_literal_underlines_do_not_create_setext_headings_or_thematic_breaks(text):
    result = render_book(empty_book(entries=[text]))
    tokens = MARKDOWN.parse(result.body)
    assert sum(t.type == 'heading_open' for t in tokens) == len(result.source_map) == 1
    assert not any(t.type == 'hr' for t in tokens)
    assert text.splitlines()[-1].strip() in visible(result.body)


def test_navigation_group_flattens_only_verified_alphabetical_shape():
    entries = [
        {
            'type': 'section',
            'name': 'Catalog (S)',
            'entries': [{'type': 'section', 'name': 'Sentinels', 'entries': ['Lore.']}],
        }
    ]
    result = render_book(empty_book(entries=entries))
    assert result.source_map[-1]['heading_path'] == ['First Part', 'Sentinels']
    entries[0]['entries'][0]['name'] = 'Watchers'
    result = render_book(empty_book(entries=entries))
    assert result.source_map[-1]['heading_path'] == ['First Part', 'Catalog (S)', 'Watchers']


def test_anonymous_overview_containers_use_inline_titles_and_keep_lists():
    overview = {
        'type': 'entries',
        'entries': [
            {
                'type': 'entries',
                'entries': [
                    {
                        'type': 'entries',
                        'name': '{@class Sentinel|XPHB}',
                        'entries': ['A short overview.', {'type': 'list', 'items': ['A path.']}],
                    }
                ],
            }
        ],
    }
    book = empty_book(entries=[overview])
    add_entity(
        book, {'name': 'Sentinel', 'source': 'XPHB', '__prop': 'class'}, 'class', insertion=True
    )
    result = render_book(book)
    assert '***Sentinel.*** A short overview.' in result.body
    assert '- A path.' in result.body
    assert [r['heading_path'] for r in result.source_map] == [
        ['First Part'],
        ['First Part', 'Sentinel'],
    ]


@pytest.mark.parametrize('prop', ['classFeature', 'facility', 'spell'])
def test_named_rules_inside_typed_payload_are_inline_but_sections_are_headings(prop):
    data = {
        'name': 'Owner',
        'source': 'XPHB',
        '__prop': prop,
        'entries': [
            {'type': 'entries', 'name': 'Resistance', 'entries': ['Keep this rule.']},
            {
                'type': 'entries',
                'entries': [
                    {
                        'type': 'entries',
                        'name': 'Options',
                        'entries': [
                            'Choose carefully.',
                            {'type': 'list', 'items': ['First choice.', 'Second choice.']},
                        ],
                    },
                    {
                        'type': 'section',
                        'name': 'Independent Section',
                        'entries': [
                            {'type': 'entries', 'name': 'Details', 'entries': ['Real subsection.']}
                        ],
                    },
                ],
            },
        ],
    }
    if prop == 'classFeature':
        data.update(level=1, className='Sentinel', classSource='XPHB')
    if prop == 'spell':
        data.update(
            level=1,
            school='A',
            time=[{'number': 1, 'unit': 'action'}],
            range={'type': 'point', 'distance': {'type': 'self'}},
            components={'v': True},
            duration=[{'type': 'instant'}],
        )
    book = empty_book()
    add_entity(book, data, prop, insertion=True)
    result = render_book(book)
    assert '***Resistance.*** Keep this rule.' in result.body
    assert '***Options.*** Choose carefully.' in result.body
    assert '- First choice.' in result.body and '- Second choice.' in result.body
    titles = [r['heading_path'][-1] for r in result.source_map]
    assert titles == [
        'First Part',
        'Level 1: Owner' if prop == 'classFeature' else 'Owner',
        'Independent Section',
        'Details',
    ]
    check_document(
        result.markdown,
        result.body,
        result.source_map,
        'XPHB',
        book['book']['title'],
        book['upstream']['checkout_sha'],
    )


def test_true_deep_sections_and_sibling_context_keep_their_hierarchy():
    node = {'type': 'section', 'name': 'Deep', 'entries': ['A real deep section.']}
    for name in reversed(['Outer', 'Inner', 'Further']):
        node = {'type': 'section', 'name': name, 'entries': [node]}
    book = empty_book(
        entries=[node, {'type': 'entries', 'name': 'Sibling', 'entries': ['Still a heading.']}]
    )
    result = render_book(book)
    assert result.source_map[-2]['heading_path'] == [
        'First Part',
        'Outer',
        'Inner',
        'Further',
        'Deep',
    ]
    assert result.source_map[-1]['heading_path'] == ['First Part', 'Sibling']


def test_inline_rule_keeps_prerequisites_tables_and_following_text():
    book = empty_book()
    add_entity(
        book,
        {
            'name': 'Workshop',
            'source': 'XPHB',
            '__prop': 'facility',
            'entries': [
                {
                    'type': 'entries',
                    'name': 'Rule',
                    'prerequisite': [{'level': 3}],
                    'cost': {'amount': 10},
                    'entries': [
                        {
                            'type': 'table',
                            'colLabels': ['Choice', 'Cost'],
                            'rows': [['A', '10 GP']],
                        },
                        'Text after the table.',
                    ],
                },
                {'type': 'entries', 'name': 'Empty Rule', 'entries': []},
                'A final paragraph.',
            ],
        },
        'facility',
        insertion=True,
    )
    result = render_book(book)
    assert '***Rule.***' in result.body and '***Empty Rule.***' in result.body
    assert '**Prerequisite:** Level 3' in result.body
    assert '**Cost:**' in result.body
    assert tables(result.body) == [[['Choice', 'Cost'], ['A', '10 GP']]]
    assert 'Text after the table.' in result.body and 'A final paragraph.' in result.body
    assert [r['heading_path'][-1] for r in result.source_map] == ['First Part', 'Workshop']
    assert result.source_map[-1]['page_attribution'] == 'partial'


def test_inline_title_precedes_canonical_content_at_its_source_anchor():
    rule = {'type': 'entries', 'name': 'Rule', 'entries': ['Source prose.']}
    book = empty_book(
        entries=[{'type': 'entries', 'entries': [{'type': 'entries', 'entries': [rule]}]}]
    )
    add_entity(
        book,
        {'name': 'Rule', 'source': 'XPHB', '__prop': 'action', 'entries': ['Canonical detail.']},
        'action',
        anchor='/source/0/entries/0/entries/0/entries/0',
    )
    result = render_book(book)
    assert result.body.index('***Rule.***') < result.body.index('Canonical detail.')
    assert result.body.index('Canonical detail.') < result.body.index('Source prose.')
    assert result.diagnostics.components['entity:0']['decision'] == 'rendered'


@pytest.mark.parametrize('kind', ['inline', 'inlineBlock'])
def test_explicit_inline_titles_are_labels_at_any_markdown_level(kind):
    result = render_book(
        empty_book(entries=[{'type': kind, 'name': ' A label: ', 'entries': ['Its text.']}])
    )
    assert '***A label:*** Its text.' in result.body
    assert len(result.source_map) == 1


@pytest.mark.parametrize(
    ('entry', 'code'),
    [
        ({'type': 'future', 'entries': ['Do not lose this']}, 'UNKNOWN_ENTRY_TYPE'),
        ({'type': 'entries', 'newRules': ['Do not lose this']}, 'UNKNOWN_ENTRY_FIELD'),
        ({'type': 'inline', 'name': ' \n', 'entries': ['Keep diagnostics.']}, 'HEADING'),
        ({'type': 'table', 'rows': [{'unknown': 'row'}]}, 'TABLE_ROW'),
        ({'type': 'table', 'rows': [[{'type': 'cell'}]]}, 'EMPTY_CELL'),
        ({'type': 'statblockInline', 'name': 'Unresolved'}, 'UNRESOLVED_STATBLOCK'),
        (None, 'NULL_ENTRY'),
    ],
)
def test_unsupported_entry_is_an_error(entry, code):
    with pytest.raises(ExportError) as error:
        render_book(empty_book(entries=[entry]))
    assert error.value.code == code
    assert error.value.context['book'] == 'XPHB'


@pytest.mark.parametrize('field', ['colLabels', 'colLabelRows'])
def test_leaf_header_spans_keep_later_columns_aligned(field):
    labels = [{'type': 'cellHeader', 'entry': 'Checks', 'width': 2}, 'Notes']
    table = {
        'type': 'table',
        field: labels if field == 'colLabels' else [labels],
        'rows': [['A', 'B', 'C']],
    }
    result = render_book(empty_book(entries=[table]))
    assert tables(result.body) == [[['Checks', '', 'Notes'], ['A', 'B', 'C']]]
