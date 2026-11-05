"""ChatOpenAI transport plus exact token counting on the same native chat template."""

from dataclasses import dataclass, field

import httpx
import openai
from langchain_core.messages import convert_to_openai_messages
from langchain_openai import ChatOpenAI

from dnd_rag.contracts import RagError


@dataclass(frozen=True)
class LLMOutput:
    text: str
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    server_timings: dict = field(default_factory=dict)
    raw_response: dict = field(default_factory=dict)


class LLMClient:
    def __init__(self, settings, profile, *, http_client=None):
        self.settings = settings
        self.profile = profile
        self.native_url = settings.llm_base_url.rstrip('/').removesuffix('/v1')
        self.http = http_client or httpx.Client(timeout=profile.http_timeout_seconds)
        self.owns_http = http_client is None
        self.last_chat_response = {}
        self.server_provenance = {}
        self.http.event_hooks.setdefault('response', []).append(self._capture_chat_response)
        self.chat = ChatOpenAI(
            model=profile.model_alias,
            base_url=settings.llm_base_url,
            api_key='local-only',
            http_client=self.http,
            max_retries=0,
            timeout=profile.http_timeout_seconds,
            temperature=profile.temperature,
            top_p=profile.top_p,
            seed=profile.seed,
            use_responses_api=False,
            streaming=False,
            extra_body={
                **self.template_options(),
                'top_k': profile.top_k,
                'min_p': profile.min_p,
                'cache_prompt': False,
            },
        )

    def template_options(self):
        return {'chat_template_kwargs': {'enable_thinking': False}, 'reasoning_effort': 'none'}

    def _capture_chat_response(self, response):
        if response.request.url.path.endswith('/chat/completions') and response.status_code == 200:
            response.read()
            self.last_chat_response = response.json()

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

    def count_input_tokens(self, messages):
        body = {
            'model': self.profile.model_alias,
            'messages': convert_to_openai_messages(list(messages)),
            'add_generation_prompt': True,
            **self.template_options(),
        }
        formatted = self._request('POST', '/apply-template', json=body)
        prompt = formatted.get('prompt')
        if not isinstance(prompt, str):
            raise RagError('llm_protocol', 'Native apply-template did not return a prompt')
        tokenized = self._request(
            'POST',
            '/tokenize',
            json={'content': prompt, 'add_special': True, 'parse_special': True},
        )
        tokens = tokenized.get('tokens')
        if not isinstance(tokens, list) or any(type(t) is not int for t in tokens):
            raise RagError('llm_protocol', 'Native tokenize did not return token IDs')
        return len(tokens)

    def generate(self, messages, *, max_tokens):
        if type(max_tokens) is not int or not 1 <= max_tokens <= self.profile.max_output_tokens:
            raise RagError(
                'invalid_output_limit', f'Output limit must be 1..{self.profile.max_output_tokens}'
            )
        self.last_chat_response = {}
        try:
            message = self.chat.invoke(list(messages), max_tokens=max_tokens)
        except (openai.APITimeoutError, httpx.TimeoutException) as exc:
            raise RagError('llm_timeout', 'LLM generation timed out') from exc
        except (openai.APIError, httpx.HTTPError, ValueError, KeyError) as exc:
            raise RagError('llm_unavailable', f'LLM generation failed: {exc}') from exc
        raw = self.last_chat_response
        usage = raw.get('usage', {})
        response_message = raw.get('choices', [{}])[0].get('message', {})
        if response_message.get('reasoning_content'):
            raise RagError('thinking_enabled', 'LLM returned reasoning despite thinking=false')
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

    def close(self):
        self.http.event_hooks['response'].remove(self._capture_chat_response)
        if self.owns_http:
            self.http.close()
