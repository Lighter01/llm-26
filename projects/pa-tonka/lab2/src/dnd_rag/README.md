# Пакет dnd_rag

Основной Python-пакет проекта. [Ingestion](ingestion/README.md) включает сборку книжного JSON отдельными Node CLI и самостоятельный Python-модуль [markdown_export](ingestion/markdown_export/README.md) с API/CLI. `py.typed` обозначает типизированный пакет; Node runtime находится в `tools/ingestion`. Директории indexing/retrieval/RAG/API появятся при реализации соответствующих компонентов.
# Retrieval

`retrieval.py`: общее stateless ядро `Retriever.retrieve(question, limit=None)`.
Получает готовый index/config, CPU QueryEncoder и QdrantStore; возвращает
RetrievalResult с ranked raw chunks и временем embedding/search. LLM/HTTP/UI
не нужны. [Indexing](indexing/README.md) · [Runtime](runtime/README.md) ·
[Архитектура](../../docs/user_docs/ARCHITECTURE.md).

