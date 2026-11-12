"""Native full-payload budgets and guarded stock SummarizationMiddleware.

The custom summarizer prevents the SDK's overflow retry from silently removing a
middle section even when trim_tokens_to_summarize=None. Oversize inputs fail explicitly.
"""

import json
from contextlib import nullcontext
from pathlib import Path

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from dnd_rag.agent.config import AgentConfig
from dnd_rag.agent.contracts import ContextStats
from dnd_rag.agent.observability import LocalObservation
from dnd_rag.contracts import RagError

SUMMARY_PROMPT = Path(__file__).with_name('prompts').joinpath('summary.txt').read_text()


class ContextBudget:
    def __init__(self, native, config):
        self.native, self.config = native, config

    def inspect(self, payload):
        return ContextStats(
            input_tokens=self.native.count_input(payload),
            agent_limit=self.config.context_limit,
            server_window=self.native.profile.context_size,
        )

    def ensure_safe(self, payload):
        stats = self.inspect(payload)
        self.native.ensure_safe(payload, stats.input_tokens)
        if stats.input_tokens > self.config.context_limit:
            raise RagError(
                'context_budget',
                'Protected current exchange cannot fit the agent budget; reduce the requested tool output or start a new dialog',
                stats.model_dump(),
            )
        return stats


class NativeSummarization(SummarizationMiddleware):
    def __init__(
        self, native, profile, emit, *, config, tools, system_prompt, recorder, turn_getter
    ):
        self.native = native
        self.profile = profile
        self.config = config
        self.emit = emit
        self.schemas = [convert_to_openai_tool(t) for t in tools]
        self.system_prompt = system_prompt
        self.recorder = recorder
        self.turn_getter = turn_getter
        self.before = 0
        if (
            config.context_limit + profile.max_output_tokens + profile.safety_margin
            > profile.context_size
        ):
            raise RagError(
                'invalid_context_budget',
                'Agent threshold plus output reserve/safety exceeds server window',
            )
        if config.summary_tokens > profile.max_output_tokens:
            raise RagError(
                'invalid_summary_budget', 'Summary output reserve exceeds selected completion limit'
            )
        super().__init__(
            model=native.chat_model,
            trigger=('tokens', config.context_limit),
            keep=('tokens', config.recent_tokens),
            token_counter=self.full_count,
            summary_prompt=SUMMARY_PROMPT,
            trim_tokens_to_summarize=None,
            summarizer=self.safe_summary,
        )

    def payload(self, messages):
        return self.native.payload(
            [SystemMessage(content=self.system_prompt), *messages], tools=self.schemas
        )

    def full_count(self, messages):
        return self.native.count_input(self.payload(messages))

    def _determine_cutoff_index(self, messages):
        # Choose whole interactions only. Protect the latest real human request and all
        # subsequent tool calls/results, regardless of their size. Summary HumanMessages
        # are carried into the next replaced prefix, not treated as new user requests.
        boundaries = [
            i
            for i, m in enumerate(messages)
            if isinstance(m, HumanMessage)
            and m.additional_kwargs.get('lc_source') != 'summarization'
        ]
        if not boundaries or boundaries[-1] == 0:
            return 0
        current = boundaries[-1]
        candidates = [i for i in boundaries if 0 < i <= current]
        for cutoff in candidates:
            if (
                self.native.count_input(self.native.payload(messages[cutoff:]))
                <= self.config.recent_tokens
            ):
                return cutoff
        return current

    async def safe_summary(self, prefix):
        turn = self.turn_getter()
        if turn and turn['model_calls'] >= self.config.max_model_calls:
            raise RagError('step_limit', 'Summary would exceed per-turn model-call limit')
        # Serialize exactly the semantic message fields used by the native model,
        # including tool calls/results and retained reasoning. No content is pre-trimmed.
        replaced = self.native.payload(prefix)['messages']
        prompt = SUMMARY_PROMPT.format(messages=json.dumps(replaced, ensure_ascii=False))
        messages = [HumanMessage(content=prompt)]
        payload = self.native.payload(messages, max_tokens=self.config.summary_tokens)
        count = self.native.count_input(payload)
        self.native.ensure_safe(payload, count)
        self.emit(
            'compaction_started',
            {
                'before': self.before,
                'summary_input_tokens': count,
                'summary_output_reserve': self.config.summary_tokens,
                'removed_message_ids': [m.id for m in prefix],
            },
        )
        manager = (
            self.recorder.client.start_as_current_observation(
                name='compaction',
                input=replaced,
                metadata={'before': self.before, 'summary_input_tokens': count, 'trimmed': False},
            )
            if self.recorder.client
            else nullcontext(LocalObservation())
        )
        if turn:
            turn['model_calls'] += 1
            turn['phase'] = 'summary'
        try:
            with manager as span:
                response = await self.native.chat_model.ainvoke(
                    messages,
                    max_tokens=self.config.summary_tokens,
                    config={
                        'run_name': 'context_summary',
                        'metadata': {'lc_source': 'summarization'},
                    },
                )
                summary = response.text.strip()
                if not summary:
                    raise ValueError('Empty summary')
                if turn:
                    turn['generations'].append(response.usage_metadata)
                self.recorder.write(
                    'generation',
                    {
                        'phase': 'summary',
                        'message': response.model_dump(mode='json'),
                        'usage': response.usage_metadata,
                    },
                )
                span.update(output=summary)
                return summary
        except RagError:
            raise
        except Exception as exc:
            raise RagError('summary_error', f'Safe summarization failed: {exc}') from exc
        finally:
            if turn:
                turn['phase'] = 'agent'

    async def abefore_model(self, state, runtime):
        self.before = self.full_count(state['messages'])
        result = await super().abefore_model(state, runtime)
        if result:
            active = result['messages'][1:]  # RemoveMessage marker is not model input.
            after = self.full_count(active)
            turn = self.turn_getter()
            if turn:
                turn['compacted'] = True
            self.emit(
                'compaction_completed',
                {
                    'before': self.before,
                    'after': after,
                    'removed_messages': len(state['messages']) - len(active) + 1,
                    'preserved_current_task': True,
                },
            )
            # A generated summary alone is not proof that the next request is safe.
            ContextBudget(self.native, self.config).ensure_safe(self.payload(active))
        return result


def build_memory_middleware(
    native_llm,
    profile,
    emit,
    *,
    config=None,
    tools=(),
    system_prompt='',
    recorder=None,
    turn_getter=lambda: None,
):
    from dnd_rag.agent.observability import ObservationRecorder

    return NativeSummarization(
        native_llm,
        profile,
        emit,
        config=config or AgentConfig(),
        tools=tools,
        system_prompt=system_prompt,
        recorder=recorder or ObservationRecorder(Path('.runtime/sessions')),
        turn_getter=turn_getter,
    )
