import pytest

from dnd_rag.config import ChunkingConfig
from dnd_rag.indexing.chunking import primary_spans, split_corpus
from dnd_rag.indexing.corpus import load_corpus
from tests.rag.fixtures import make_corpus


@pytest.mark.parametrize('strategy', ['markdown', 'recursive', 'source_map_recursive'])
def test_all_splitters_exact_slices(tmp_path, strategy):
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    cfg = ChunkingConfig(strategy=strategy, chunk_size=100, chunk_overlap=20)
    chunks = split_corpus(corpus, cfg, len)
    for name, book in corpus.books.items():
        selected = [c for c in chunks if c.metadata.source_file == name]
        covered = set()
        for c in selected:
            m = c.metadata
            assert c.page_content == book.body[m.start_char : m.end_char]
            assert len(c.page_content) <= 100
            assert c.metadata.book_title == name[:-3] + ' title'
            covered.update(range(m.start_char, m.end_char))
        assert covered == set(range(len(book.body)))
        assert len({(c.metadata.start_char, c.metadata.end_char) for c in selected}) == len(
            selected
        )


def test_custom_h4_no_duplication(tmp_path):
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    book = corpus.books['xphb.md']
    spans = primary_spans(book, 4)
    assert ''.join(book.body[start:end] for start, end in spans) == book.body
    assert all('##### Detail' not in book.body[start:end].splitlines()[0] for start, end in spans)
    assert spans[0] == (0, 1)


def test_sections_use_own_content_and_keep_repeated_paths(tmp_path):
    corpus = load_corpus(make_corpus(tmp_path / 'corpus'))
    book = corpus.books['xphb.md']
    parent = book.body.index('## Parent')
    child = book.body.index('### Child')
    sections = book.attributions(parent, child + 20)
    assert [s.heading_path for s in sections] == [['Intro', 'Parent'], ['Intro', 'Parent', 'Child']]
    assert [s.heading_path for s in book.attributions(child, child + 20)] == [
        ['Intro', 'Parent', 'Child']
    ]
    repeated = [
        s for s in book.attributions(0, len(book.body)) if s.heading_path == ['Intro', 'Parent']
    ]
    assert len(repeated) == 2
    assert repeated[0].section_start_char != repeated[1].section_start_char
    assert repeated[0].printed_pages is None
