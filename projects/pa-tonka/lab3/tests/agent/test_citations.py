from tests.rag.fixtures import make_hits


def test_numbers_stable_for_repeated_search_summary_and_restart(tmp_path):
    from dnd_rag.agent.citations import CitationRegistry, validate_citations

    registry = CitationRegistry(tmp_path)
    hits = make_hits(3)
    first = registry.register('dialog', hits[:2])
    second = registry.register('dialog', [hits[1], hits[2]])
    assert [r.number for r in first] == [1, 2] and [r.number for r in second] == [2, 3]
    # Model/checkpointer summarization never owns or clears the independent registry.
    restarted = CitationRegistry(tmp_path)
    valid = validate_citations('As discussed [1], and [3]. Unknown [99].', restarted, 'dialog')
    assert valid.valid_numbers == [1, 3] and valid.unknown_numbers == [99]
    assert valid.sources[0].provenance['text'] == hits[0].chunk.page_content
    assert len(restarted.export('dialog')) == 3


def test_new_dialog_does_not_inherit_allowed_source_ids_or_fabricate_pages(tmp_path):
    from dnd_rag.agent.citations import CitationRegistry, validate_citations

    registry = CitationRegistry(tmp_path)
    hits = make_hits(1)
    registry.register('one', hits)
    assert validate_citations('[1]', registry, 'two').unknown_numbers == [1]
    other = registry.register('two', hits)
    assert other[0].number == 1
    assert other[0].source.provenance['sections'] == [
        s.model_dump(mode='json') for s in hits[0].chunk.metadata.sections
    ]
    assert 'page' not in other[0].source.provenance
