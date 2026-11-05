# Устройство D&D RAG

Готовые Markdown XPHB/XDMG/XMM и `source_map.jsonl` поступают в indexing:
canonical body → token splitters → embedding input → GPU document embeddings →
Qdrant. CPU query encoder и retrieval используют готовую коллекцию. Следующий
этап разработки добавит prompt/LLM и проверку числовых цитат; сейчас QA не готов.

[config.py](../../src/dnd_rag/config.py) читает строгий YAML и локальные настройки.
Конфиги экспериментов задают изменяемые параметры retrieval, `.env` — адреса/пути,
`configs/llm/local.yaml` — отдельный бюджет и размещение LLM. Импорт конфигурации
не загружает Torch или модели. [contracts.py](../../src/dnd_rag/contracts.py)
содержит общие типы и RagError без зависимости от транспорта.

У системы два токенайзера: embedding tokenizer измеряет чанки и вход эмбеддера;
LLM tokenizer впоследствии будет считать полный chat prompt. Их числа не взаимозаменяемы.
Сырой `page_content` предназначен для цитат/BM25/оценки; производный `embedding_text`
меняет только представление для модели. Координаты Unicode и строки относятся к body,
без YAML и одной пустой строки после него. Метаданные печатных страниц наследуются
из карты с исходной атрибуцией, без восстановления страниц по размеру чанка.

Подробные параметры: [справочник конфигов](../../configs/experiments/README.md).
Готовая подготовка данных: [ingestion](../ingestion/ARCHITECTURE.md).
