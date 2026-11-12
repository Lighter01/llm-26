# Пакет dnd_rag

Автономный поиск по локальному каноническому корпусу. Импорт конфигурации/контрактов не загружает модели.

- `config.py`: строгие RagConfig, RuntimeSettings, YAML и разрешение путей.
- `contracts.py`: ошибки, точные chunks/provenance, index и retrieval результаты.
- `retrieval.py`: `Retriever.retrieve(question, limit)` → ранжированные исходные chunks.
- `indexing/`: corpus/source_map → tokenizer/chunks → GPU embeddings → Qdrant.
- `runtime/`: locks, владение процессами, подготовка/reuse/reset индекса, llama launcher.
- `evaluation/`: чистые evidence-контракты и retrieval-метрики.
- `ingestion/`: самостоятельная подготовка книг, сохранённая без изменения корпуса.
- `__main__.py`: административные команды с ленивыми импортами.

Потребитель вызывает `runtime.index.prepare_retriever(config, settings, session)` один раз и затем использует тот же CPU encoder. Retrieval не читает эталоны, старые результаты, LLM или интерфейс.
