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

`indexing/identity.py` вычисляет SHA256 canonical JSON эффективного build_spec:
corpus/map/metadata, chunking, embedding input/model/revision/dtype/dimension,
HNSW build, quantization, mode и активный BM25 preprocessing, версии алгоритмов/библиотек.
Query ef_search/k1/b/RRF/prompt, batch, пути cache/gold и имя run не входят.
Имена коллекций `rag_<полный hash>`; UUIDv5 points зависят от index_id/file/char range.
Одинаковые тексты разных мест не склеиваются.

`indexing/store.py` управляет только указанной собственной коллекцией. Metadata коллекции
хранят owner/build_spec/index_id/build_id/expected_points и building→ready; фиктивного
point нет. Upsert повторяет те же IDs. Ready выставляется после schema/payload/count и
дренирования очереди оптимизаций. BM25 для hybrid строится после upload отдельным шагом,
dense его не создаёт; поиск использует raw page_content. Для квантования оригиналы
сохраняются, поиск не rescoring. Совместимая ready-коллекция переиспользуется полностью;
отсутствующая/неполная или `--rebuild` проходят весь build, без кэшей стадий.
Сетевая ошибка и недоказанное владение не приводят к удалению. Возобновление optimizer
после restart описано в [пробах](../rag/TECHNICAL_PROBES.md).

`runtime/application.ensure_index` сначала валидирует corpus и паспорт готовой коллекции.
Только при необходимости запускает `indexing.build` отдельным процессом: tokenizer →
split/metadata/IDs → GPU encoder → upload/index readiness. Документная модель завершается
вместе с worker; следующий этап загрузит CPU QueryEncoder. В `.runtime/builds/<uuid>/`
остаются immutable request, stages/result и worker.log для диагностики; это не кэш.
`reset_index` — отдельная ветка без ensure/build: по config вычисляет текущий identity,
по index_id вообще не читает corpus/gold/tokenizer и удаляет только проверенную коллекцию.

`runtime/lock.py` и `processes.py` обеспечивают один runtime. flock удерживается всем
сроком session; созданные процессы наследуют открытый descriptor через pass_fds.
При смерти родителя живой ребёнок сохраняет lock. Штатный выход/Ctrl+C останавливает
только process groups данного запуска, затем закрывает descriptor. Lock-файл сохраняется.
Qdrant volume и результаты не очищаются при остановке.

`retrieval.py` предоставляет `Retriever.retrieve(question, limit=None)`. Он использует
постоянный CPU QueryEncoder и QdrantStore.search без чтения Markdown, gold или LLM.
Dense query идёт по named `dense` с hnsw_ef. Hybrid посылает 20 dense + 20 native BM25
prefetch, сервер объединяет их равновесным RRF и возвращает до10. Score — cosine либо
rrf, не вероятность. Нет score_threshold и дополнительного поиска ради диагностики.
Порядок серверных ties сохраняется; одинаковые IDs убираются без дополнения выдачи.
Успешная пустота отличается от технической ошибки. Timings отдельно измеряют CPU
embedding, search и весь retrieval. Этот интерфейс общий для аналитики и будущего API.

`evaluation/gold.py` сверяет выбранный validated YAML с текущими body/source_map,
соответствующим `validation_report.json` (PASS, written, тот же raw hash/corpus/counts)
и каждым точным срезом цитаты. Старый сохранённый gold после FAIL не принимается.
Смысловую истинность эталонов эти проверки не доказывают. Insufficient не входят в средние.

`evaluation/metrics.py` пересчитывает множество всех релевантных чанков Rq по всему
manifest для каждого вопроса/разбиения. Релевантность: пересечение внутри того же файла
и body version ≥50% короткого диапазона. Precision@k делит на k даже при короткой выдаче;
Recall — на |Rq| (пустой Rq → 0 с отдельным признаком); MRR@10 — средний reciprocal rank.
Evidence Coverage объединяет все диапазоны top-k без relevance-фильтра, считает дробю
каждую gold alternative, берёт max альтернатив факта и равные средние фактов/вопросов.
Половины разных alternatives не складываются. Raw tokens суммируют overlap повторно
как стоимость контекста, EC учитывает символ один раз. Метрики @1/5/10 считаются до
будущего сокращения LLM-контекста и не являются оценкой правильности ответа.
