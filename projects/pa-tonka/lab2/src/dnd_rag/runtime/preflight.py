"""Shared HTTP preflight rules, without importing models or the LLM client."""

import errno

import httpx


def native_llm_url(base_url):
    return base_url.rstrip('/').removesuffix('/v1')


def connection_refused(error):
    """Only an explicit ECONNREFUSED proves absence; wrappers may keep it in args."""
    pending, seen, refused = [error], set(), False
    while pending:
        current = pending.pop()
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (TimeoutError, httpx.TimeoutException)):
            return False
        refused |= isinstance(current, OSError) and current.errno == errno.ECONNREFUSED
        # qdrant-client uses .source, httpcore uses args, and our RagError uses cause.
        # Implicit __context__ may describe an earlier, unrelated request: ignore it.
        pending.extend([current.__cause__, getattr(current, 'source', None), *current.args])
    return refused
