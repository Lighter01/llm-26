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

`indexing/corpus.py` сохраняет body побуквенно; проверяет LF, карту и line/char
границы. Markdown parser отличает настоящие mapped H1–H6 от `#` внутри кода.
Интервалы родителя за вычетом детей задают собственное содержание. Чанк наследует
только затронутые разделы, в порядке первого пересечения; одинаковые paths с разными
координатами сохраняются отдельно. Атрибуция страниц остаётся разделовой.

`indexing/chunking.py` использует `MarkdownTextSplitter` (regex separators) или
`RecursiveCharacterTextSplitter` по всей книге. Custom сначала выделяет участки
по началам заголовков до выбранной глубины, включая исходный префикс, и применяет
Recursive отдельно внутри каждого. Введение родителя не размножается. Размер и
overlap измеряются токенами без special tokens, пробелы/разделители сохраняются.
Адаптер сопоставляет последовательные выходные строки с исходным локальным участком,
проверяет непрерывность покрытия и однозначность offsets. Неоднозначность/потеря текста
завершает сборку диагностикой; tokenizer overlap не трактуется как число символов.

`indexing/embedding.py` загружает закреплённый tokenizer отдельно от SentenceTransformer.
DocumentEncoder явно требует CUDA и выбранный BF16/FP32; QueryEncoder загружается
один раз на CPU FP32. Неиспользуемые vision/audio encoders отключены через config_kwargs.
Производный input имеет ровно один `title: ... | text: ...`; независимые title/strip
не меняют raw content. Удаляются только пересечения с настоящими mapped H1–H6,
в том числе частично разрезанными. Document encode получает пустой prompt override,
query — штатный prompt_name модели. Весь input считается со special tokens до encode,
без silent truncation. Размерность сокращается библиотечным API, Normalize сохраняется;
векторы проверяются на форму/конечность и передаются в float32.
