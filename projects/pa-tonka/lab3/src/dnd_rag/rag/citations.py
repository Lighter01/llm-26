"""A small Markdown inline rule finds numeric markers outside code and actual links."""

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

from dnd_rag.contracts import Source, Warning

MARKER = re.compile(r'\[([0-9]+)\]')


def _numeric_marker(state, silent):
    # Link-label lookahead must still see ordinary brackets. Consuming a marker in
    # silent mode would make a valid nested label look like a forbidden nested link.
    if silent or state.linkLevel > 0:
        return False
    match = MARKER.match(state.src, state.pos, state.posMax)
    if match is None:
        return False
    token = state.push('numeric_citation', '', 0)
    token.content = match.group(0)
    token.meta['citation_id'] = int(match.group(1))
    state.pos = match.end()
    return True


PARSER = MarkdownIt('commonmark')
# Let a real inline/reference link resolve first. Unresolved [1][2] remains two markers.
PARSER.inline.ruler.after('link', 'numeric_citation', _numeric_marker)


@dataclass(frozen=True)
class CitationCheck:
    used_ids: list[int]
    unknown_ids: list[int]
    sources: list[Source]
    warnings: list[Warning]


def _source(id, chunk):
    derived = {'citation_id', 'snippet', 'snippet_truncated', 'page_content'}
    metadata = chunk.metadata.model_dump()
    values = {key: metadata[key] for key in Source.model_fields if key not in derived}
    return Source(
        **values,
        citation_id=id,
        snippet=chunk.page_content[:400],
        snippet_truncated=len(chunk.page_content) > 400,
        page_content=chunk.page_content,
    )


def extract_citations(answer, registry) -> CitationCheck:
    ids = set()
    for block in PARSER.parse(answer, {}):
        if block.type != 'inline':
            continue
        for token in block.children or []:
            if token.type == 'numeric_citation':
                ids.add(token.meta['citation_id'])
    used = sorted(ids & registry.keys())
    unknown = sorted(ids - registry.keys())
    warnings = []
    if unknown:
        warnings.append(
            Warning(
                code='unknown_citation',
                citation_ids=unknown,
                message='The answer refers to unavailable source IDs: '
                + ', '.join(map(str, unknown))
                + '.',
            )
        )
    return CitationCheck(used, unknown, [_source(id, registry[id]) for id in used], warnings)
