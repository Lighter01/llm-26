from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def test_turn_tool_retrieval_are_nested_without_second_search(tmp_path):
    import dnd_rag.agent.observability as obs

    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key='pk-lf-unit',
        secret_key='sk-lf-unit',
        base_url='http://127.0.0.1:1',
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
    )
    recorder = obs.ObservationRecorder(tmp_path, client=client)
    result = {'hits': [{'id': 'exact-chunk', 'score': 0.7, 'page_content': 'Original text'}]}
    with recorder.turn('session-1', 'turn-1', {'input': 'Find a rule'}):
        with recorder.tool('search_rules', {'query': 'rule'}):
            recorder.retrieval(result)
    recorder.flush()
    spans = exporter.get_finished_spans()
    byname = {s.name: s for s in spans}
    assert byname['retrieval'].parent.span_id == byname['search_rules'].context.span_id
    assert byname['search_rules'].parent.span_id == byname['turn-1'].context.span_id
    assert 'exact-chunk' in str(byname['retrieval'].attributes)
    assert (tmp_path / 'session-1' / 'turns.jsonl').exists()
