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

Новые программные клиенты: `agent/` — create_agent, лимиты, наблюдаемость и общие reply/event contracts; `tools/` — общий StreamableHTTP MCP; `experiments/` — Codex exec/resume и проверяемый exporter. Их инициализация переиспользует retrieval и общий локальный LLM. `runtime/codex_proxy.py` адаптирует несовместимые namespace/additional_tools payloads, сохраняя полный журнал.

`game/` компилирует и загружает отдельный проверяемый JSON catalog из тех же закреплённых книг. Общие IDs связывают monster lookup и encounter, item variants разрешаются штатным upstream runtime, а не старым QA.

`cli.py` — Rich/prompt_toolkit чат поверх AgentService: команды, история ввода, Markdown, tool/summary/error events, последняя native оценка контекста и trace URL.
