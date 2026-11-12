"""Local model transport with native counting of the exact serialized request body."""

import json
from dataclasses import dataclass, field

import httpx
import openai
from langchain_openai import ChatOpenAI

from dnd_rag.contracts import RagError
from dnd_rag.runtime.preflight import native_llm_url


@dataclass(frozen=True)
class LLMOutput:
    text: str
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    server_timings: dict = field(default_factory=dict)
    raw_response: dict = field(default_factory=dict)


class NativeLLM:
    """One reusable model. Every real chat request is counted before network dispatch.

    The HTTP hook sees OpenAI's final flattened body, including tools, reasoning and
    template options. The counter call does not recursively invoke the generation hook.
    """

    def __init__(self, settings, profile, *, http_client=None):
        self.settings, self.profile = settings, profile
        self.native_url = native_llm_url(settings.llm_base_url)
        self.http = http_client or httpx.Client(timeout=profile.http_timeout_seconds)
        self.owns_http = http_client is None
        self.last_chat_response, self.server_provenance = {}, {}
        self.last_input_tokens = None
        self.on_payload = None
        self.counter_backend = None
        self.http.event_hooks.setdefault('request', []).append(self._before_request)
        self.http.event_hooks.setdefault('response', []).append(self._capture_chat_response)
        self.async_http = httpx.AsyncClient(
            timeout=profile.http_timeout_seconds,
            event_hooks={
                'request': [self._before_async_request],
                'response': [self._capture_async_response],
            },
        )
        self.chat_model = ChatOpenAI(
            model=profile.model_alias,
            base_url=settings.llm_base_url,
            api_key='local-only',
            http_client=self.http,
            http_async_client=self.async_http,
            max_retries=0,
            timeout=profile.http_timeout_seconds,
            temperature=profile.temperature,
            top_p=profile.top_p,
            seed=profile.seed,
            max_tokens=profile.max_output_tokens,
            use_responses_api=False,
            streaming=False,
            extra_body={
                **self.template_options(),
                'top_k': profile.top_k,
                'min_p': profile.min_p,
                'cache_prompt': False,
            },
        )
        self.chat = self.chat_model

    def template_options(self):
        return self.profile.template_options()

    def payload(self, messages, **kwargs):
        body = self.chat_model._get_request_payload(list(messages), **kwargs)
        extra = body.pop('extra_body', {})
        body.update(extra)
        return body

    def _before_request(self, request):
        if request.url.path.endswith('/chat/completions'):
            body = json.loads(request.content)
            count = self.count_input(body)
            request.extensions['native_input_tokens'] = count
            self.last_input_tokens = count
            self.ensure_safe(body, count)
            if self.on_payload:
                self.on_payload(body, count)

    async def _before_async_request(self, request):
        self._before_request(request)

    def ensure_safe(self, payload, count):
        reserve = payload.get(
            'max_completion_tokens', payload.get('max_tokens', self.profile.max_output_tokens)
        )
        if count + reserve + self.profile.safety_margin > self.profile.context_size:
            raise RagError(
                'context_overflow',
                'Full input plus output reserve exceeds the server window',
                {'input_tokens': count, 'reserve': reserve, 'window': self.profile.context_size},
            )

    def _capture_chat_response(self, response):
        if response.request.url.path.endswith('/chat/completions') and response.status_code == 200:
            response.read()
            self.last_chat_response = response.json()
            expected = response.request.extensions.get('native_input_tokens')
            actual = self.last_chat_response.get('usage', {}).get('prompt_tokens')
            if expected is not None and actual is not None and expected != actual:
                raise RagError(
                    'token_parity', f'Native count/usage parity mismatch: {expected} != {actual}'
                )

    async def _capture_async_response(self, response):
        if response.request.url.path.endswith('/chat/completions') and response.status_code == 200:
            await response.aread()
            self._capture_chat_response(response)

    def _request(self, method, path, **kwargs):
        try:
            response = self.http.request(method, self.native_url + path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise RagError('llm_timeout', f'LLM {path} timed out') from exc
        except httpx.HTTPError as exc:
            raise RagError('llm_unavailable', f'LLM {path} unavailable: {exc}') from exc
        except ValueError as exc:
            raise RagError('llm_protocol', f'LLM {path} returned invalid JSON') from exc

    def count_input(self, payload: dict, *, api='chat') -> int:
        if api not in ('chat', 'responses'):
            raise ValueError('api must be chat or responses')
        path = (
            '/v1/chat/completions/input_tokens' if api == 'chat' else '/v1/responses/input_tokens'
        )
        try:
            result = self._request('POST', path, json=payload)
        except RagError as exc:
            # Only a confirmed unsupported route permits fallback; no timeout recovery by guessing.
            cause = exc.__cause__
            if (
                not isinstance(cause, httpx.HTTPStatusError)
                or cause.response.status_code not in (404, 405, 501)
                or api != 'chat'
            ):
                raise
            formatted = self._request(
                'POST', '/apply-template', json={**payload, 'add_generation_prompt': True}
            )
            if not isinstance(formatted.get('prompt'), str):
                raise RagError('llm_protocol', 'Native apply-template did not return a prompt')
            tokens = self._request(
                'POST',
                '/tokenize',
                json={'content': formatted['prompt'], 'add_special': True, 'parse_special': True},
            ).get('tokens')
            if not isinstance(tokens, list) or any(type(t) is not int for t in tokens):
                raise RagError('llm_protocol', 'Native tokenize did not return token IDs')
            self.counter_backend = 'apply-template/tokenize (parity checked on generation)'
            return len(tokens)
        count = result.get('input_tokens')
        if type(count) is not int or count < 0:
            raise RagError('llm_protocol', 'Native input_tokens must be a nonnegative integer')
        self.counter_backend = path
        return count

    def count_input_tokens(self, messages):
        return self.count_input(self.payload(messages))

    def generate(self, messages, *, max_tokens):
        if type(max_tokens) is not int or not 1 <= max_tokens <= self.profile.max_output_tokens:
            raise RagError(
                'invalid_output_limit', f'Output limit must be 1..{self.profile.max_output_tokens}'
            )
        self.last_chat_response = {}
        try:
            message = self.chat_model.invoke(list(messages), max_tokens=max_tokens)
        except (openai.APITimeoutError, httpx.TimeoutException) as exc:
            raise RagError('llm_timeout', 'LLM generation timed out') from exc
        except (openai.APIError, httpx.HTTPError, ValueError, KeyError) as exc:
            # openai preserves a hook exception as the cause of its connection error.
            cause = exc.__cause__
            if isinstance(cause, RagError):
                raise cause
            raise RagError('llm_unavailable', f'LLM generation failed: {exc}') from exc
        raw = self.last_chat_response
        usage = raw.get('usage', {})
        return LLMOutput(
            text=message.content,
            finish_reason=message.response_metadata.get('finish_reason'),
            input_tokens=usage.get('prompt_tokens'),
            output_tokens=usage.get('completion_tokens'),
            server_timings=raw.get('timings', {}),
            raw_response=raw,
        )

    def is_ready(self):
        try:
            return self.http.get(self.native_url + '/health', timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self):
        await self.async_http.aclose()
        self.close()

    def close(self):
        for key, hook in [
            ('request', self._before_request),
            ('response', self._capture_chat_response),
        ]:
            if hook in self.http.event_hooks[key]:
                self.http.event_hooks[key].remove(hook)
        if self.owns_http:
            self.http.close()


LLMClient = NativeLLM
