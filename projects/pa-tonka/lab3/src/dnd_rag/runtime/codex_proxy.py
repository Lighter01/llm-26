"""Protocol compatibility only: Codex additional_tools/namespaces ↔ llama Responses.

No planning or history compression occurs here. Original/effective bodies are retained.
Only the configured MCP game tools are exposed to the model in this benchmark profile.
"""

import copy
import json
import re
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, StreamingResponse

from dnd_rag.contracts import RagError

ALLOWED = {
    'search_rules',
    'lookup_monsters',
    'evaluate_encounter',
    'build_encounter',
    'generate_loot',
}


def adapt_responses_payload(payload, profile):
    body = copy.deepcopy(payload)
    tools = list(body.get('tools', []))
    history = []
    for item in body.get('input', []) if isinstance(body.get('input'), list) else []:
        if item.get('type') == 'additional_tools':
            tools.extend(item.get('tools', []))
            if item.get('content'):
                history.append(
                    {
                        'type': 'message',
                        'role': item.get('role', 'developer'),
                        'content': item['content'],
                    }
                )
        else:
            history.append(item)
    if isinstance(body.get('input'), list):
        body['input'] = history
    flat = {}
    names = {}
    for definition in tools:
        namespace = definition.get('name') if definition.get('type') == 'namespace' else None
        children = definition.get('tools', []) if namespace else [definition]
        for tool in children:
            name = tool.get('name', '')
            if namespace == 'mcp__dnd' and name in ALLOWED and tool.get('type') == 'function':
                key = f'{namespace}__{name}'
                flat[key] = {**tool, 'name': key}
                names[key] = (namespace, name)
            elif (
                namespace is None
                and name.startswith('mcp__dnd__')
                and name.split('__', 2)[-1] in ALLOWED
            ):
                flat[name] = tool
                names[name] = ('mcp__dnd', name.split('__', 2)[-1])
    body['tools'] = list(flat.values())
    for item in history:
        if item.get('type') == 'function_call' and item.get('namespace'):
            namespace = item.pop('namespace')
            key = f'{namespace}__{item["name"]}'
            if key not in names:
                raise RagError(
                    'unsupported_codex_tool',
                    'History refers to a tool outside the configured MCP profile',
                )
            item['name'] = key
    body.update(profile.template_options())
    body['max_output_tokens'] = profile.max_output_tokens
    # The same server profile governs both clients. No effort string invents a budget.
    body['reasoning'] = {
        **body.get('reasoning', {}),
        'effort': 'medium' if profile.thinking else 'none',
    }
    return body, names


def adapt_response_event(event, names):
    if isinstance(event, list):
        return [adapt_response_event(x, names) for x in event]
    if not isinstance(event, dict):
        return event
    result = {k: adapt_response_event(v, names) for k, v in event.items()}
    if result.get('type') == 'function_call' and result.get('name') in names:
        namespace, name = names[result['name']]
        result.update(namespace=namespace, name=name)
    return result


def create_codex_proxy(native, directory: Path, *, recorder=None):
    app = FastAPI()

    @app.get('/health')
    async def health():
        return {
            'status': 'ok',
            'model': native.profile.model_alias,
            'thinking': native.profile.thinking,
            'reasoning_budget_tokens': native.profile.reasoning_budget_tokens,
        }

    @app.post('/v1/responses')
    async def responses(request: Request):
        original = await request.json()
        try:
            body, names = adapt_responses_payload(original, native.profile)
            count = native.count_input(body, api='responses')
            native.ensure_safe(body, count)
        except RagError as exc:
            return JSONResponse({'error': exc.as_dict()}, status_code=400)
        session = request.headers.get('X-DND-Session-Id', 'unknown')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', session):
            return JSONResponse({'error': 'Invalid session ID'}, status_code=400)
        target = directory / session
        target.mkdir(parents=True, exist_ok=True)
        record = {
            'id': str(uuid.uuid4()),
            'input_tokens': count,
            'original': original,
            'effective': body,
            'exposed_tools': list(names),
        }

        def write(data):
            with (target / 'wire.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(data, ensure_ascii=False) + '\n')

        write({'kind': 'request', **record})
        trace_id = request.headers.get('X-DND-Trace-Id')
        if recorder and recorder.client and trace_id:
            with recorder.client.start_as_current_observation(
                name='codex-wire-input',
                trace_context={'trace_id': trace_id},
                input=body,
                metadata={
                    'input_tokens': count,
                    'server_window': native.profile.context_size,
                    'original_request_id': record['id'],
                    'exposed_tools': list(names),
                },
            ):
                pass
        client = httpx.AsyncClient(timeout=native.profile.http_timeout_seconds)
        try:
            response = await client.send(
                client.build_request('POST', native.native_url + '/v1/responses', json=body),
                stream=True,
            )
        except Exception:
            await client.aclose()
            raise
        if response.status_code != 200:
            content = await response.aread()
            await response.aclose()
            await client.aclose()
            write(
                {
                    'kind': 'upstream_error',
                    'id': record['id'],
                    'status': response.status_code,
                    'body': content.decode(errors='replace'),
                }
            )
            return JSONResponse(json.loads(content), status_code=response.status_code)
        if not body.get('stream'):
            data = adapt_response_event(json.loads(await response.aread()), names)
            await response.aclose()
            await client.aclose()
            write({'kind': 'response', 'id': record['id'], 'response': data})
            return JSONResponse(data)

        async def chunks():
            try:
                async for line in response.aiter_lines():
                    if line.startswith('data:') and line[5:].strip() != '[DONE]':
                        event = adapt_response_event(json.loads(line[5:]), names)
                        if event.get('type') == 'response.completed':
                            actual = event.get('response', {}).get('usage', {}).get('input_tokens')
                            write(
                                {
                                    'kind': 'response',
                                    'id': record['id'],
                                    'count_parity': actual == count,
                                    'response': event.get('response'),
                                }
                            )
                            if actual is not None and actual != count:
                                raise RagError(
                                    'token_parity',
                                    'Codex effective native count does not match upstream usage',
                                )
                        line = 'data: ' + json.dumps(event, ensure_ascii=False)
                    yield (line + '\n').encode()
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(chunks(), media_type='text/event-stream')

    return app
