"""Per-turn Langfuse observations plus an independent, untruncated local journal."""

import json
import os
import re
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values
from langfuse import Langfuse, propagate_attributes

_current = ContextVar('dm_turn', default=None)


class LocalObservation:
    trace_id = None

    def update(self, **kwargs):
        return self


class ObservationRecorder:
    def __init__(self, directory: Path, *, client=None, project_root=None):
        self.directory = directory
        self.client = client
        self.project_id = None
        values = {**(dotenv_values(project_root / '.env') if project_root else {}), **os.environ}
        if (
            client is None
            and values.get('LANGFUSE_PUBLIC_KEY')
            and values.get('LANGFUSE_SECRET_KEY')
        ):
            self.client = Langfuse(
                public_key=values['LANGFUSE_PUBLIC_KEY'],
                secret_key=values['LANGFUSE_SECRET_KEY'],
                base_url=values.get('LANGFUSE_BASE_URL', 'http://127.0.0.1:3000'),
                environment='lab3',
            )
            self.project_id = values.get('LANGFUSE_INIT_PROJECT_ID')
        self.base_url = values.get('LANGFUSE_BASE_URL', 'http://127.0.0.1:3000')

    def write(self, kind, payload, *, session_id=None):
        current = _current.get()
        session_id = session_id or (current[0] if current else None)
        if session_id is None:
            return
        if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,180}', session_id):
            raise ValueError('Invalid session ID')
        directory = self.directory / session_id
        directory.mkdir(parents=True, exist_ok=True)
        row = {
            'time': datetime.now(UTC).isoformat(),
            'kind': kind,
            'turn_id': current[1] if current else None,
            **payload,
        }
        with (directory / 'turns.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')

    @contextmanager
    def turn(self, session_id, turn_id, attributes):
        token = _current.set((session_id, turn_id))
        self.write('turn_started', attributes)
        propagation = (
            propagate_attributes(
                session_id=session_id, user_id='lab3-local', tags=attributes.get('tags', ['lab3'])
            )
            if self.client
            else nullcontext()
        )
        try:
            with propagation:
                manager = (
                    self.client.start_as_current_observation(
                        name=turn_id,
                        as_type='agent',
                        input=attributes.get('input'),
                        metadata=attributes,
                    )
                    if self.client
                    else nullcontext(LocalObservation())
                )
                with manager as observation:
                    try:
                        yield observation
                    except BaseException as exc:
                        observation.update(level='ERROR', status_message=str(exc))
                        self.write('error', {'error': str(exc)})
                        raise
        finally:
            self.write('turn_closed', {})
            _current.reset(token)

    @contextmanager
    def tool(self, name, arguments):
        self.write('tool_started', {'name': name, 'arguments': arguments})
        manager = (
            self.client.start_as_current_observation(name=name, as_type='tool', input=arguments)
            if self.client
            else nullcontext(LocalObservation())
        )
        with manager as span:
            yield span

    def model_response(self, payload, *, phase='agent'):
        if payload is None:
            return
        self.write('model_response', {'phase': phase, 'response': payload})
        if self.client:
            with self.client.start_as_current_observation(
                name='raw-model-response',
                output=payload,
                metadata={
                    'phase': phase,
                    'model_response_id': payload.get('id'),
                    'usage_is_recorded_on_generation': True,
                },
            ):
                pass

    def retrieval(self, result):
        data = result.model_dump(mode='json') if hasattr(result, 'model_dump') else result
        self.write('retrieval', {'result': data})
        if self.client:
            with self.client.start_as_current_observation(
                name='retrieval', as_type='retriever', input=data.get('question'), output=data
            ):
                pass

    def event(self, event):
        self.write(event.kind, event.payload)
        if self.client:
            with self.client.start_as_current_observation(
                name=event.kind,
                metadata=event.payload,
                level='WARNING' if event.kind == 'error' else 'DEFAULT',
            ):
                pass

    def flush(self):
        if self.client:
            self.client.flush()

    def trace_url(self, trace_id):
        return (
            f'{self.base_url}/project/{self.project_id}/traces/{trace_id}'
            if trace_id and self.project_id
            else None
        )
