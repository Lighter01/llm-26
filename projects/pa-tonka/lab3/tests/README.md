# Проверки

`rag/` — конфигурация, exact corpus/chunks, embeddings, index identity/store/build, retrieval/metrics и владение процессами. `ingestion/` — самостоятельная подготовка книг и точные координаты. Явные live-маркеры: rag_models/rag_qdrant/rag_llama; integration использует существующие resolved inputs.

Основной набор: `uv run --group test python -m pytest -m 'not integration and not rag_models and not rag_qdrant and not rag_llama'`. Ruff: `uv run --group lint ruff check src tests`. Node: `npm --prefix tools/ingestion run test:unit`.
