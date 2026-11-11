# Indexing

- `corpus.py`: `load_corpus(Path) -> CorpusSnapshot`; canonical body, hash, вложенная карта, реальные заголовки и интервалы собственного содержания разделов.
- `chunking.py`: `split_corpus(corpus, ChunkingConfig, count_tokens) -> list[ChunkDraft]`; готовые LangChain Markdown/Recursive splitters и custom H1–H4 → Recursive. `primary_spans` выделяет неперекрывающиеся исходные участки custom.
- `embedding.py`: `prepare_embedding_text`, `load_token_counter`, `DocumentEncoder` (GPU batched iterator) и `QueryEncoder.encode(question)` (CPU FP32). Тяжёлые импорты только при явной загрузке tokenizer/модели.
- `identity.py`: `make_identity`/`assign_ids`, canonical JSON, версии и фиксированные технические thresholds; не загружает tokenizer ради reuse/reset.
- `store.py`: inspect/build/manifest/reset только одной owned коллекции, batching, BM25 schema, quantization, readiness и provenance. Загрузка Qdrant отделена от worker.
- `build.py`: внутренний GPU worker `build_index`, полная подготовка и измерения стадий. Использует унаследованный lock родителя, не захватывает второй.

ChunkDraft ещё не имеет index_id/chunk_id. Metadata и текст описаны в общих [contracts](../contracts.py). API не запускает ingestion и не меняет корпус. [Устройство](../../../docs/user_docs/ARCHITECTURE.md) · [Параметры](../../../configs/experiments/README.md).
