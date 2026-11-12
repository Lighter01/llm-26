# Проверки

`rag/` — конфигурация, exact corpus/chunks, embeddings, index identity/store/build, retrieval/metrics и владение процессами. `ingestion/` — самостоятельная подготовка книг и точные координаты. Явные live-маркеры: rag_models/rag_qdrant/rag_llama; integration использует существующие resolved inputs.

Основной набор: `uv run --group test python -m pytest -m 'not integration and not rag_models and not rag_qdrant and not rag_llama'`. Ruff: `uv run --group lint ruff check src tests`. Node: `npm --prefix tools/ingestion run test:unit`.

`agent/` — программный агент, модельный transport, history/limits и Langfuse observations; `tools/` — MCP registry/serialization; `experiments/` — Codex subprocess/resume/export и преобразование реальных protocol payloads. В `agent/integration/` находится явный shared-stack smoke; он требует DM_LIVE_STACK=1 и уже работающего стека.

`game/` проверяет каталоги и чистые игровые правила на маленьких независимых fixtures, без сети и LLM.
