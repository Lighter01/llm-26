import pytest

from dnd_rag.rag.citations import extract_citations
from tests.rag.fixtures import make_hits


def test_numeric_markers_use_frozen_registry():
    hits = make_hits(2)
    answer = 'A rule [2][4]. Again [2]. Unknown [99].'
    checked = extract_citations(answer, {2: hits[0].chunk, 4: hits[1].chunk})
    assert checked.used_ids == [2, 4] and checked.unknown_ids == [99]
    assert [s.citation_id for s in checked.sources] == [2, 4]
    assert checked.warnings[0].code == 'unknown_citation'
    assert checked.warnings[0].citation_ids == [99]


@pytest.mark.parametrize(
    'text',
    [
        r'\[1]',
        r'\[1\]',
        '`[1]`',
        '```text\n[1]\n```',
        '    [1]\n',
        '[1](https://example.com)',
        '[label [1]](https://example.com)',
        '![alt [1]](image.png)',
        '[1][ref]\n\n[ref]: https://example.com',
        '[1]\n\n[1]: https://example.com',
        '[1]: https://example.com',
    ],
)
def test_markdown_non_citations(text):
    checked = extract_citations(text, {1: make_hits(1)[0].chunk})
    assert checked.used_ids == [] and checked.unknown_ids == [] and checked.sources == []


def test_adjacent_and_escaped_backslash():
    chunks = [h.chunk for h in make_hits(2)]
    assert extract_citations('Rule **[1][2]**', {1: chunks[0], 2: chunks[1]}).used_ids == [1, 2]
    assert extract_citations(r'\\[1]', {1: chunks[0]}).used_ids == [1]


def test_source_preview_and_no_automatic_bibliography():
    chunk = make_hits(1)[0].chunk
    source = extract_citations('A rule [1]', {1: chunk}).sources[0]
    assert source.snippet == chunk.page_content[:400]
    assert source.snippet_truncated is True
    assert source.page_content == chunk.page_content
    assert source.start_char == chunk.metadata.start_char
    assert source.line_end == chunk.metadata.line_end
    assert source.sections[0].page_attribution == 'inherited_section_start'
    assert extract_citations('No citation here.', {1: chunk}).sources == []
