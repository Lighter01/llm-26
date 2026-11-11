"""Emit Markdown and its body-relative heading map in the same pass."""

import bisect
import json
import re

from ..common.model import require


class Document:
    def __init__(self, book_id, title, upstream_sha, inline, *, evidence_sink=None):
        self.book_id, self.title, self.upstream_sha = book_id, title, upstream_sha
        self.inline = inline
        self.parts = []
        self.position = 0
        self.headings = []
        self.stack = []
        self.evidence_sink = evidence_sink

    @property
    def path(self):
        return [heading['title'] for heading in self.stack]

    def add(self, value):
        if not value or not value.strip():
            return
        text = value.rstrip('\n') + '\n\n'
        self.parts.append(text)
        self.position += len(text)

    def heading(self, title, level, *, page=None, fallback=None, partial=False):
        title = self.inline(title, plain=True).strip()
        require(
            bool(title) and 1 <= level <= 6,
            'HEADING',
            'Invalid heading',
            book=self.book_id,
            title=title,
            level=level,
        )
        while self.stack and self.stack[-1]['level'] >= level:
            self.stack.pop()['end'] = self.position
        require(
            level == len(self.stack) + 1,
            'HEADING_DEPTH',
            'Skipped heading level',
            book=self.book_id,
            title=title,
        )
        if fallback is None and self.stack:
            parent = self.stack[-1]
            fallback = parent['section_start']
        record = {
            'title': title,
            'level': level,
            'start': self.position,
            'pages': set(),
            'partial': partial or page is None,
            'fallback': fallback,
            'section_start': page if page is not None else fallback,
            'path': self.path + [title],
            'parent': self.stack[-1] if self.stack else None,
        }
        if page is not None:
            record['pages'].add(page)
        self.headings.append(record)
        self.stack.append(record)
        self.add('#' * level + ' ' + self.inline(title))

    def evidence(self, page=None, *, unknown=False, fallback=None):
        if not self.stack:
            if self.evidence_sink is not None:
                self.evidence_sink(page, unknown=unknown, fallback=fallback)
            return
        record = self.stack[-1]
        if page is not None:
            record['pages'].add(page)
        record['partial'] |= unknown
        if record['fallback'] is None:
            record['fallback'] = fallback

    def finish(self):
        body = ''.join(self.parts).rstrip('\n') + '\n'
        for heading in self.stack:
            heading['end'] = len(body)
        for heading in reversed(self.headings):
            parent = heading['parent']
            if parent:
                parent['pages'].update(heading['pages'])
                parent['partial'] |= heading['partial'] or not heading['pages']
        line_starts = [0] + [match.end() for match in re.finditer('\n', body)]
        records = []
        for heading in self.headings:
            pages = sorted(heading['pages'])
            if pages:
                printed = [pages[0]] if pages[0] == pages[-1] else [pages[0], pages[-1]]
                attribution = 'partial' if heading['partial'] else 'explicit'
            else:
                printed = [heading['fallback']] if heading['fallback'] is not None else None
                attribution = 'inherited_section_start' if printed else 'unknown'
            start, end = heading['start'], heading['end']
            require(
                0 <= start < end <= len(body),
                'MAP_RANGE',
                'Invalid section range',
                book=self.book_id,
            )
            records.append(
                {
                    'book_id': self.book_id,
                    'file': self.book_id.lower() + '.md',
                    'heading_path': heading['path'],
                    'line_start': bisect.bisect_right(line_starts, start),
                    'line_end': bisect.bisect_left(line_starts, end),
                    'start_char': start,
                    'end_char': end,
                    'printed_pages': printed,
                    'page_attribution': attribution,
                }
            )
        prefix = '\n'.join(
            (
                '---',
                f'book_id: {self.book_id}',
                'title: ' + json.dumps(self.title, ensure_ascii=False).replace('\x85', '\\u0085'),
                'source: "5etools"',
                'upstream_sha: ' + json.dumps(self.upstream_sha),
                '---',
                '',
                '',
            )
        )
        return prefix + body, body, records
