# Indexing

- `corpus.py`: `load_corpus(Path) -> CorpusSnapshot`; canonical body, hash,
  вложенная карта, реальные заголовки и интервалы собственного содержания разделов.
- `chunking.py`: `split_corpus(corpus, ChunkingConfig, count_tokens) -> list[ChunkDraft]`;
  готовые LangChain Markdown/Recursive splitters и custom H1–H4 → Recursive.
  `primary_spans` выделяет неперекрывающиеся исходные участки custom.

ChunkDraft ещё не имеет index_id/chunk_id. Metadata и текст описаны в общих
[contracts](../contracts.py). API не запускает ingestion и не меняет корпус.
[Устройство](../../../docs/user_docs/ARCHITECTURE.md) ·
[Параметры](../../../configs/experiments/README.md).
