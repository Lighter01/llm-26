# Пакет dnd_rag

Основной Python-пакет проекта. [Ingestion](ingestion/README.md) — готовая подготовка книжного JSON/Markdown и gold. Node runtime изолирован в `tools/ingestion`. `config.py` и `contracts.py` задают строгие настройки и общие объекты без загрузки моделей.

## Retrieval

`retrieval.py`: общее stateless ядро `Retriever.retrieve(question, limit=None)`. Получает готовый index/config, CPU QueryEncoder и QdrantStore; возвращает RetrievalResult с ranked raw chunks и временем embedding/search. LLM/HTTP/UI не нужны. [Indexing](indexing/README.md) · [Runtime](runtime/README.md) · [Архитектура](../../docs/user_docs/ARCHITECTURE.md).

[Evaluation](evaluation/README.md) содержит gold, чистые метрики, run artifacts, аналитический runner и карту сравнений. [RAG](rag/README.md) — точный бюджет, локальная LLM и Citation Registry. `api.py` задаёт stateless HTTP-контракт, `ui.py` — Streamlit-клиент без моделей. `__main__.py` — тонкий CLI build-index, reset-index, experiment, serve-retrieval, demo, evaluate-qa, summarize-results.

