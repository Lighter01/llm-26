"""Native-tool LangChain agent, sessions and bounded per-turn execution."""

import asyncio
import json
from contextvars import ContextVar
from pathlib import Path
from time import perf_counter

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.memory import InMemorySaver

from dnd_rag.agent.config import AgentConfig
from dnd_rag.agent.contracts import AgentEvent, AgentReply, ContextStats
from dnd_rag.agent.observability import ObservationRecorder
from dnd_rag.contracts import RagError

_turn = ContextVar('dm_agent_turn', default=None)
SYSTEM_PROMPT = Path(__file__).with_name('prompts').joinpath('system.txt').read_text()


def tool_data(message):
    artifact = getattr(message, 'artifact', None)
    if isinstance(artifact, dict) and artifact.get('structured_content') is not None:
        return artifact['structured_content']
    content = message.content
    if isinstance(content, list):
        content = '\n'.join(x.get('text', '') for x in content if x.get('type') == 'text')
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return {'text': content}


def underlying_error(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, RagError):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


class AgentGuard(AgentMiddleware):
    def __init__(self, service):
        self.service = service

    async def awrap_model_call(self, request, handler):
        service, turn = self.service, _turn.get()
        if turn['model_calls'] >= service.config.max_model_calls:
            raise RagError('step_limit', 'Maximum model calls reached')
        turn['model_calls'] += 1
        if service.native:
            messages = (
                [request.system_message] if request.system_message else []
            ) + request.messages
            kwargs = dict(request.model_settings)
            if request.tools:
                kwargs['tools'] = [convert_to_openai_tool(t) for t in request.tools]
            if request.tool_choice is not None:
                kwargs['tool_choice'] = request.tool_choice
            payload = service.native.payload(messages, **kwargs)
            count = service.native.count_input(payload)
            service.measure(count)
            if count > service.config.context_limit:
                raise RagError(
                    'context_budget', 'History exceeds agent budget; compaction is required'
                )
        response = await handler(request)
        for msg in response.result if hasattr(response, 'result') else [response]:
            if isinstance(msg, AIMessage):
                usage = msg.usage_metadata
                turn['generations'].append(usage)
                service.recorder.write(
                    'generation', {'message': msg.model_dump(mode='json'), 'usage': usage}
                )
        return response

    async def awrap_tool_call(self, request, handler):
        service, turn = self.service, _turn.get()
        if turn['tool_calls'] >= service.config.max_tool_calls:
            raise RagError('step_limit', 'Maximum tool calls reached')
        turn['tool_calls'] += 1
        call = request.tool_call
        service.emit('tool_started', {'name': call['name'], 'arguments': call['args']})
        before = perf_counter()
        with service.recorder.tool(call['name'], call['args']) as observation:
            try:
                result = await handler(request)
            except Exception as exc:
                result = ToolMessage(
                    content=json.dumps({'error': {'code': 'tool_error', 'message': str(exc)}}),
                    tool_call_id=call['id'],
                    name=call['name'],
                    status='error',
                )
            data = tool_data(result)
            failed = result.status == 'error' or bool(data.get('error'))
            observation.update(output=data, level='WARNING' if failed else 'DEFAULT')
            if call['name'] == 'search_rules' and 'hits' in data:
                service.recorder.retrieval(data)
            record = {
                'name': call['name'],
                'arguments': call['args'],
                'call_id': call['id'],
                'result': data,
                'status': 'error' if failed else 'completed',
                'latency_ms': (perf_counter() - before) * 1000,
            }
            turn['tools'].append(record)
            service.recorder.write('tool_completed', record)
            service.emit(
                'tool_error' if failed else 'tool_completed',
                {'name': call['name'], 'latency_ms': record['latency_ms']},
            )
            return result


class AgentService:
    def __init__(self, *, native_llm=None, model=None, tools=None, config=None, recorder=None):
        self.native = native_llm
        self.model = model or native_llm.chat_model
        self.config = config or AgentConfig()
        self.recorder = recorder or ObservationRecorder(Path('.runtime/sessions'))
        self.tools = tools
        self.graphs = {}
        self.checkpointer = InMemorySaver()
        self.contexts = {}
        self.last_records = {}
        if self.native:
            self.native.on_payload = self._wire_payload

    def emit(self, kind, payload):
        event = AgentEvent(kind=kind, payload=payload)
        self.recorder.event(event)
        turn = _turn.get()
        if turn and turn.get('on_event'):
            turn['on_event'](event)

    def measure(self, count, *, compacted=False):
        turn = _turn.get()
        stats = ContextStats(
            input_tokens=count,
            agent_limit=self.config.context_limit,
            server_window=self.native.profile.context_size if self.native else 16384,
            compacted=compacted or turn.get('compacted', False),
        )
        turn['context'] = stats
        turn['max_context'] = max(turn['max_context'], count)
        self.emit('context_measured', stats.model_dump())
        return stats

    def _wire_payload(self, payload, count):
        if _turn.get():
            phase = _turn.get().get('phase', 'agent')
            if phase == 'agent':
                self.measure(count)
            else:
                self.emit(
                    'summary_input_measured',
                    {'input_tokens': count, 'server_window': self.native.profile.context_size},
                )
            self.recorder.write(
                'wire_input', {'payload': payload, 'input_tokens': count, 'phase': phase}
            )

    async def _graph(self, session_id):
        if session_id not in self.graphs:
            tools = self.tools
            if tools is None:
                client = MultiServerMCPClient(
                    {
                        'dnd': {
                            'transport': 'streamable_http',
                            'url': self.config.mcp_url,
                            'headers': {'X-DND-Session-Id': session_id},
                        }
                    }
                )
                tools = await client.get_tools()
            middleware = []
            if self.native:
                from dnd_rag.agent.memory import build_memory_middleware

                middleware.append(
                    build_memory_middleware(
                        self.native,
                        self.native.profile,
                        self.emit,
                        config=self.config,
                        tools=tools,
                        system_prompt=SYSTEM_PROMPT,
                        recorder=self.recorder,
                        turn_getter=lambda: _turn.get(),
                    )
                )
            middleware.append(AgentGuard(self))
            self.graphs[session_id] = create_agent(
                self.model,
                tools=tools,
                system_prompt=SYSTEM_PROMPT,
                middleware=middleware,
                checkpointer=self.checkpointer,
            )
        return self.graphs[session_id]

    async def ainvoke(self, session_id, user_text, *, turn_id, on_event=None):
        before = perf_counter()
        turn = {
            'model_calls': 0,
            'phase': 'agent',
            'compacted': False,
            'tool_calls': 0,
            'generations': [],
            'tools': [],
            'max_context': 0,
            'context': self.contexts.get(
                session_id, ContextStats(agent_limit=self.config.context_limit)
            ),
            'on_event': on_event,
        }
        token = _turn.set(turn)
        text, status, error, trace_id = '', 'completed', None, None
        try:
            with self.recorder.turn(
                session_id, turn_id, {'input': user_text, 'tags': ['lab3', 'own']}
            ) as observation:
                trace_id = observation.trace_id
                try:
                    async with asyncio.timeout(self.config.timeout_seconds):
                        graph = await self._graph(session_id)
                        callbacks = (
                            [CallbackHandler(public_key=self.recorder.client._resources.public_key)]
                            if self.recorder.client
                            else []
                        )
                        result = await graph.ainvoke(
                            {'messages': [HumanMessage(content=user_text)]},
                            config={
                                'configurable': {'thread_id': session_id},
                                'callbacks': callbacks,
                                'recursion_limit': 2
                                * (self.config.max_model_calls + self.config.max_tool_calls)
                                + 8,
                            },
                        )
                        final = result['messages'][-1]
                        text = final.text if isinstance(final, AIMessage) else str(final.content)
                except TimeoutError:
                    status = 'timeout'
                    error = {'code': 'timeout', 'message': 'Turn time limit reached'}
                except Exception as exc:
                    rag = underlying_error(exc)
                    status = rag.code if rag else 'error'
                    error = rag.as_dict() if rag else {'code': 'agent_error', 'message': str(exc)}
                if error:
                    await self._close_interrupted_tools(session_id)
                    self.emit('error', error)
                usage = {}
                for key in ['input_tokens', 'output_tokens', 'total_tokens']:
                    values = [u.get(key) if u else None for u in turn['generations']]
                    usage[key] = (
                        sum(values) if values and all(type(v) is int for v in values) else None
                    )
                usage.update(
                    model_calls=turn['model_calls'],
                    tool_calls=turn['tool_calls'],
                    max_context_tokens=turn['max_context'],
                    latency_ms=(perf_counter() - before) * 1000,
                    api_cost=0.0,
                )
                reply = AgentReply(
                    text=text,
                    status=status,
                    context=turn['context'],
                    trace_id=trace_id,
                    usage=usage,
                    error=error,
                )
                observation.update(
                    output=reply.model_dump(mode='json'),
                    level='DEFAULT' if status == 'completed' else 'ERROR',
                )
                self.recorder.write('reply', {'reply': reply.model_dump(mode='json')})
                self.last_records[session_id] = {
                    'tools': turn['tools'],
                    'generations': turn['generations'],
                }
                self.contexts[session_id] = turn['context']
                return reply
        finally:
            _turn.reset(token)
            self.recorder.flush()

    async def _close_interrupted_tools(self, session_id):
        """Preserve history and explicitly close calls with no available result."""
        graph = self.graphs.get(session_id)
        if graph is None:
            return
        config = {'configurable': {'thread_id': session_id}}
        state = await graph.aget_state(config)
        messages = state.values.get('messages', [])
        answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
        pending = [
            call
            for m in messages
            if isinstance(m, AIMessage)
            for call in m.tool_calls
            if call['id'] not in answered
        ]
        if pending:
            closures = [
                ToolMessage(
                    content=json.dumps(
                        {
                            'error': {
                                'code': 'interrupted',
                                'message': 'Tool result unavailable after interrupted turn; no successful execution is asserted',
                            }
                        }
                    ),
                    tool_call_id=call['id'],
                    name=call['name'],
                    status='error',
                )
                for call in pending
            ]
            await graph.aupdate_state(config, {'messages': closures}, as_node='tools')
            self.recorder.write(
                'interrupted_tool_closures', {'call_ids': [c['id'] for c in pending]}
            )

    async def aclose(self):
        self.recorder.flush()
        if self.native:
            await self.native.aclose()
