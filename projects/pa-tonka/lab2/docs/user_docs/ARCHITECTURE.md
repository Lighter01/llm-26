# Устройство D&D RAG

Готовые Markdown XPHB/XDMG/XMM и `source_map.jsonl` поступают в indexing:
canonical body → token splitters → embedding input → GPU document embeddings →
Qdrant. CPU query encoder и retrieval используют готовую коллекцию. QA-ядро
упаковывает исходные фрагменты в prompt локальной LLM и проверяет числовые цитаты.

[config.py](../../src/dnd_rag/config.py) читает строгий YAML и локальные настройки.
Конфиги экспериментов задают изменяемые параметры retrieval, `.env` — адреса/пути,
`configs/llm/local.yaml` — отдельный бюджет и размещение LLM. Импорт конфигурации
не загружает Torch или модели. [contracts.py](../../src/dnd_rag/contracts.py)
содержит общие типы и RagError без зависимости от транспорта.

У системы два токенайзера: embedding tokenizer измеряет чанки и вход эмбеддера;
LLM tokenizer считает полный chat prompt. Их числа не взаимозаменяемы.
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
вместе с worker; затем загружается CPU QueryEncoder. В `.runtime/builds/<uuid>/`
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

`evaluation/artifacts.py` атомарно резервирует уникальную results-папку и обновляет
паспорт running→completed/failed. `retrieval_run.py` соединяет готовые компоненты под
одной RuntimeSession. GPU worker полностью завершается до CPU query loading. Manifest
получается scroll из текущей коллекции и не используется как кэш для другого build.
Все Rq, ranked raw hits, fact/alternative coverage, счётчики/токены и времена сохраняются.
Offline `recompute_saved_metrics` читает только сохранённые gold/manifest/hits после проверки
hash gold; reset коллекции не лишает run проверяемости. Failed и partial runs не дают
успешного среднего по подмножеству вопросов.

`evaluation/study.py` проверяет простую YAML-карту сравнений: явно выбранная completed база,
однозначный comparison, общий corpus/gold и фактические изменённые поля config snapshot.
Нет наследования или автоматического DAG; runner не переписывает study.yaml после запуска.

`runtime/llama.py` запускает установленный llama.cpp отдельным процессом через RuntimeSession.
Локально найден unified `~/.llama-app/llama serve`, build11046/60081bb2b: это тот же
сервер llama.cpp. Subcommand задан явно в LLM-профиле, путь — в .env. Процесс наследует
descriptor project.lock (проверено на живом PID). Уже занятый endpoint отклоняется:
полный профиль чужого запуска нельзя подтвердить, чужой процесс не завершается.

`rag/llm.py` обращается к Chat Completions через ChatOpenAI. Native `/apply-template`
использует те же messages/chat_template_kwargs/reasoning_effort, `/tokenize` считает
весь полученный prompt с add_special=true/parse_special=true. BOS, system и generation
prefix учитывает сервер. Реальные usage23/6027 совпали с подсчётом. Thinking=false,
один slot, auto fit/context shift/prompt cache выключены. Native response hook сохраняет
timings/usage этого же HTTP-вызова; второго запроса генерации нет.

`rag/context.py` передаёт первые пять исходных фрагментов вместе с вопросом, system
и явным списком номеров. Полный chat prompt должен занимать не более 6400 токенов:
8192 − 1536 − 256. При превышении удаляется целиком последний чанк, prompt считается
снова. Если не входит даже первый, generation не вызывается. System prompt — ресурс
пакета `rag/prompts/system.txt`, доступный независимо от рабочего каталога.

`rag/service.py` выполняет один retrieval и не более одной генерации; истории нет.
Пустая успешная выдача даёт no_context без обращения к LLM. AskTrace хранит реально
использованные messages, frozen registry и raw response для будущего QA-аудита.
`rag/citations.py` распознаёт `[n]` через Markdown parser вне кода, escapes и настоящих
links/images. Источники возвращаются только для допустимых использованных номеров,
без перенумерации. Неизвестные номера и finish_reason=length дают warnings; исходный
ответ сохраняется. Snippet — первые 400 Unicode-символов исходного чанка, координаты
и атрибуция страниц остаются прежними. Наличие номера не доказывает смысл цитаты.

`api.py` — транспорт над общим ядром: строгий question/limit, отдельные retrieval/QA
readiness и единый error envelope. Sync endpoints выполняются в thread pool;
неблокирующий QA gate даёт429, пока первый вызов упаковывает контекст/генерирует.
Retrieval продолжает обслуживаться. Конфиг, модель и collection не меняются через HTTP.

`runtime/application.py` запускает API программно в одном worker без reload, поэтому
родитель и API не загружают два query encoder. После ensure_index и выхода GPU worker
загружается CPU query; demo затем запускает llama.cpp и ожидает readiness. Supervisor
дожидается HTTP API перед запуском Streamlit; RuntimeSession владеет дочерними LLM/UI
и освобождает lock после их остановки. Retrieval-only не импортирует LLM-профиль/GGUF.
`ui.py` содержит только HTTP и представление текущего результата; история не идёт в QA.
