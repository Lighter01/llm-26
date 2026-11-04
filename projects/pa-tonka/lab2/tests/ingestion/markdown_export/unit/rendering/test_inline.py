import pytest

from dnd_rag.ingestion.markdown_export import ExportError
from dnd_rag.ingestion.markdown_export.rendering.inline import InlineRenderer
from helpers import MARKDOWN, plain


@pytest.mark.parametrize(
    ('source', 'expected'),
    [
        ('{@b bold} {@i italic} {@s gone}', '**bold** *italic* ~~gone~~'),
        ('{@b Save {@dc 15} or take {@damage 2d6 + 3}}', '**Save DC 15 or take 2d6 + 3**'),
        ('{@dice 1d8|one die} / {@damage 1d4;1d6}', 'one die / 1d4/1d6'),
        ('{@damage 1d8 + summonSpellLevel}', "1d8 + the spell's level"),
        ('{@spell Fireball|XPHB|{@i flame}}', '*flame*'),
        ('{@creature Ape|XMM} / {@item Rope|XPHB}', 'Ape / Rope'),
        ('{@card Balance|Deck|XDMG|Card label}', 'Card label'),
        ('{@deity Mystra|Forgotten Realms|PHB|Lady of Magic}', 'Lady of Magic'),
        (
            '{@book Old Rules|PHB|2} {@area Room A|1} {@filter Spells|spells|level=1}',
            'Old Rules Room A Spells',
        ),
        (
            '{@hit 7}, {@hit -2}, {@dc 18}, {@recharge 5}, {@chance 25}',
            '+7, -2, DC 18, (Recharge 5–6), 25 percent',
        ),
        ('{@actSave wis} {@actSaveFail} {@h}', '*Wisdom Saving Throw:* *Failure:* *Hit:* '),
        ('{@atkr mw,rw}', '*Melee Weapon or Ranged Weapon Attack Roll:*'),
        (
            '{@link Example|https://example.org/a(b)?x=1&y=2}',
            '[Example](https://example.org/a%28b%29?x=1&y=2)',
        ),
    ],
)
def test_inline_semantics(source, expected):
    assert InlineRenderer()(source) == expected


@pytest.mark.parametrize(
    ('source', 'expected', 'emphasis', 'strong'),
    [
        ('{@spell Fireball}', '*Fireball*', 1, 0),
        ('{@spell Fireball|XPHB|flame}', '*flame*', 1, 0),
        ('{@i Cast {@spell Fireball|XPHB} now}', '*Cast Fireball now*', 1, 0),
        ('{@b Cast {@spell Fireball|XPHB} now}', '**Cast *Fireball* now**', 1, 1),
        ('{@spell Fireball|XPHB|{@b {@i flame}}}', '***flame***', 1, 1),
        (
            '{@link {@spell Fireball|XPHB}|https://example.org}',
            '[*Fireball*](https://example.org)',
            1,
            0,
        ),
        (
            '{@spell Fireball|XPHB|{@link flame|https://example.org}}',
            '*[flame](https://example.org)*',
            1,
            0,
        ),
        ('{@spell Fireball|XPHB|Bright [Flame]}', r'*Bright \[Flame\]*', 1, 0),
        ('{@spell Fireball|XPHB} and {@spell Light|XPHB}', '*Fireball* and *Light*', 2, 0),
    ],
)
def test_spell_links_keep_one_italic_style_and_plain_display_text(
    source, expected, emphasis, strong
):
    render = InlineRenderer()
    result = render(source)
    assert result == expected
    tokens = MARKDOWN.parse(result)[1]
    assert sum(t.type == 'em_open' for t in tokens.children) == emphasis
    assert sum(t.type == 'strong_open' for t in tokens.children) == strong
    assert render(source, plain=True) == plain(tokens)


@pytest.mark.parametrize(
    ('source', 'expected'),
    [
        ('{@scaledamage 8d6|3-9|1d6}', '1d6'),
        ('{@scaledice 2d8|1-9|2d8}', '2d8'),
        ('{@scaledice 70|6-9|10}', '10'),
        ('{@scaledamage 2d8;4d6|4-9|1d8}', '1d8'),
        ('{@scaledice 1d6|1,3,5,7,9|1d6|psi}', '1d6'),
        ('{@scaledice 2d6;3d6|2-8,9|1d6|psi|extra amount}', 'extra amount'),
        ('{@scaledamage 8d6|3-9|1d6||{@b {@dice 1d6|one die}}}', '**one die**'),
        ('{@scaledice 2d6| 1 - 8, 9 |{@i 1d6}||}', '*1d6*'),
    ],
)
def test_scaled_tags_display_increment_or_explicit_label(source, expected):
    render = InlineRenderer()
    assert render(source) == expected
    assert render(source, plain=True) == plain(MARKDOWN.parse(expected)[1])


@pytest.mark.parametrize(
    'arguments',
    [
        '8d6|3-9',
        '8d6|3-9|1d6|psi|label|extra',
        '|3-9|1d6',
        '8d6|3-9|',
        '8d6||1d6',
        '8d6|9-3|1d6',
        '8d6|0-9|1d6',
        '8d6|3-10|1d6',
        '8d6|3,3|1d6',
        '8d6|bad|1d6',
        '8d6|3-9|1d6|unknown',
        '8d6|3-9|1d6|{@b label}',
    ],
)
def test_invalid_scaled_grammar_fails_with_context(arguments):
    context = {'book': 'XPHB', 'heading_path': ['Spells', 'Fixture']}
    with pytest.raises(ExportError) as error:
        InlineRenderer(lambda: context)('{@scaledice ' + arguments + '}')
    assert error.value.code == 'INVALID_SCALED_TAG'
    assert error.value.context == context


def test_nested_display_label_is_one_link_with_italic_child():
    text = InlineRenderer()('{@link {@i guide}|https://example.org}')
    children = MARKDOWN.parse(text)[1].children
    assert [t.type for t in children] == ['link_open', 'em_open', 'text', 'em_close', 'link_close']
    assert children[0].attrGet('href') == 'https://example.org'
    assert plain(MARKDOWN.parse(text)[1]) == 'guide'


def test_literal_punctuation_and_plain_heading_labels():
    render = InlineRenderer()
    source = r'Literal [A] *B* _C_ <D> \ path'
    assert plain(MARKDOWN.parse(render(source))[1]) == source
    assert render('{@b Name {@spell Light|XPHB|Lumen}}', plain=True) == 'Name Lumen'


@pytest.mark.parametrize(
    ('source', 'code'),
    [
        ('Before {@future Valuable Content}', 'UNKNOWN_TAG'),
        ('{@b missing close', 'UNCLOSED_TAG'),
        ('{#spell Unresolved}', 'ACTIVE_REFERENCE'),
        ('{@link Missing}', 'INVALID_LINK'),
        ('{@link Bad|javascript:alert(1)}', 'INVALID_LINK'),
        ('{@atkr unknown}', 'UNKNOWN_ATTACK'),
        ('{@actSave luck}', 'UNKNOWN_ABILITY'),
    ],
)
def test_unknown_grammar_fails_with_context(source, code):
    with pytest.raises(ExportError) as error:
        InlineRenderer(lambda: {'book': 'XMM', 'heading_path': ['Part', 'Creature']})(source)
    assert error.value.code == code
    assert error.value.context['book'] == 'XMM'
    assert error.value.context['heading_path'] == ['Part', 'Creature']
