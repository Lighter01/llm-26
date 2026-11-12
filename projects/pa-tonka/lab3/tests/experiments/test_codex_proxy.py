import copy

from dnd_rag.config import LLMProfile


def test_additional_tool_namespaces_are_moved_without_losing_schema_or_history():
    from dnd_rag.runtime.codex_proxy import adapt_response_event, adapt_responses_payload

    prompt = {
        'model': 'dnd-nemotron',
        'input': [
            {
                'type': 'additional_tools',
                'role': 'developer',
                'tools': [
                    {
                        'type': 'namespace',
                        'name': 'mcp__dnd',
                        'tools': [
                            {
                                'type': 'function',
                                'name': 'search_rules',
                                'parameters': {
                                    'type': 'object',
                                    'properties': {'query': {'type': 'string'}},
                                },
                            }
                        ],
                    },
                    {
                        'type': 'namespace',
                        'name': 'functions',
                        'tools': [
                            {'type': 'function', 'name': 'read_mcp_resource', 'parameters': {}}
                        ],
                    },
                ],
            },
            {
                'type': 'message',
                'role': 'user',
                'content': [{'type': 'input_text', 'text': 'Keep all original text.'}],
            },
            {
                'type': 'function_call',
                'namespace': 'mcp__dnd',
                'name': 'search_rules',
                'call_id': 'c1',
                'arguments': '{"query":"Dash"}',
            },
            {'type': 'function_call_output', 'call_id': 'c1', 'output': 'Original tool result'},
        ],
        'reasoning': {'effort': 'none'},
        'stream': True,
    }
    original = copy.deepcopy(prompt)
    body, names = adapt_responses_payload(prompt, LLMProfile())
    assert prompt == original
    assert len(body['input']) == 3
    assert body['input'][0]['content'][0]['text'] == 'Keep all original text.'
    assert body['input'][1]['name'] == 'mcp__dnd__search_rules'
    assert body['input'][2]['output'] == 'Original tool result'
    assert [t['name'] for t in body['tools']] == ['mcp__dnd__search_rules']
    assert body['tools'][0]['parameters']['properties']['query'] == {'type': 'string'}
    assert body['max_output_tokens'] == 2048 and body['reasoning_budget_tokens'] == 0
    event = {
        'type': 'response.output_item.added',
        'item': {
            'type': 'function_call',
            'name': 'mcp__dnd__search_rules',
            'call_id': 'c2',
            'arguments': '',
        },
    }
    converted = adapt_response_event(event, names)
    assert (
        converted['item']['namespace'] == 'mcp__dnd' and converted['item']['name'] == 'search_rules'
    )
    assert converted['item']['call_id'] == 'c2'


def test_budgeted_effective_payload_preserves_reasoning_boundaries_and_usage():
    from dnd_rag.runtime.codex_proxy import adapt_response_event, adapt_responses_payload

    p = LLMProfile(thinking=True, reasoning_budget_tokens=512)
    body, names = adapt_responses_payload(
        {
            'input': [{'type': 'message', 'role': 'user', 'content': 'hi'}],
            'reasoning': {'effort': 'medium'},
        },
        p,
    )
    assert body['chat_template_kwargs']['enable_thinking'] is True
    assert body['reasoning']['effort'] == 'medium' and body['reasoning_budget_tokens'] == 512
    event = {
        'type': 'response.completed',
        'response': {
            'output': [
                {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': 'A thought.'}]},
                {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Done.'}]},
            ],
            'usage': {'input_tokens': 29, 'output_tokens': 18},
        },
    }
    assert adapt_response_event(event, names) == event
