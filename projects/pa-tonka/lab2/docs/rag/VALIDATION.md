# Проверка реализации

Разработка завершена: сохранены 10 retrieval-конфигураций, реальный QA20, заполненная agent-assisted рецензия и [готовый отчёт](../../report/LAB2_REPORT.md). Ниже отделены воспроизводимые данные от исторической приёмки 5–6 ноября 2026 года. A01–A17 — обозначения проверок той приёмки; их содержание раскрыто в таблице и не требует служебного ТЗ. Старые числа тестов не являются результатом нынешнего запуска, skipped не подтверждает живую совместимость. Одноразовые журналы, ревью и диагностические пробы удалены; семь дополнительных JSON сохранены в [results/technical](../../results/technical/README.md).

| Требование | Проверенное поведение / доказательство |
| --- | --- |
| A01 | Готовый corpus: 687745 слов, 4536 sections; XPHB имеет 262 различных явно атрибутированных печатных page endpoints (больше 50). Gold 20+3/59 facts, hashes и exact slices проверены read-only. |
| A02–A03 | Три реальные splitter по embedding tokenizer, baseline 512/64 и experimental 768/64; exact-slice violations=0, repeated paths/Unicode/ownership/partial headings покрыты unit tests. |
| A04 | EG2 revision f9972ac..., text-only BF16 GPU/FP32 CPU, finite shape 128/256/512/768; full input без truncation. |
| A05 | Qdrant 1.20 server/client, BM25/RRF/quantization реальные запросы, HNSW 1024 indexed, persistence restart. |
| A06–A07 | Fingerprint excludes query/batch/inactive BM25, stable UUIDs/upsert, building not ready, safe targeted reset twice, foreign/network errors do not delete. |
| A08 | Shared dense/hybrid store tested live; pure metric fixtures prove 50% boundary, full Rq, fractional EC, alternatives/union/equal weights. |
| A09 | Runner tests: unique names, retained failures, honest reuse/null timings, offline recomputation. Реальные baseline/reuse PASS, числа ниже. |
| A10–A11 | Точный полный prompt, whole-tail budget и Markdown Citation Registry: 21 unit tests PASS; реальный count/usage 23/6027, C3 inputs 1683–6220. |
| A12 | Живые serve-retrieval/demo, один CPU encoder/API worker; Streamlit HTTP health и AppTest с настоящим QA API PASS. |
| A13 | Runtime lock и QA 429; parent-death/cleanup повторены с реальными Uvicorn/Streamlit, чужой sentinel сохраняется; быстрый restart после TIME_WAIT проверен. |
| A14 | Все 10 полных профилей completed/built; 14 CSV строк, 1 corpus/gold cohort, все метрики пересчитаны офлайн; выборы и причины в study/EXPERIMENTS. |
| A15 | Реальный results/qa_final completed: 20/20, actual messages/registry/usage проверены офлайн; CSV первоначально создана с `not_reviewed`; текущие 20 строк имеют заполненную agent-assisted рецензию. Optional insufficient 3 не запускались. |
| A16 | ARCHITECTURE/CLI/config reference/module navigation обновлены; все 7 --help сверены, schema/defaults проверены, выбранный demo реально запущен. Пакет для отчёта ниже. |
| A17 | Полный fresh-context code review и повторная проверка исправлений: R1–R5 закрыты, открытых обязательных замечаний нет. 699 passed/3 skipped, Ruff 126 files PASS; отчёт и границы ниже. |

## C2 — baseline и reuse: PASS

[Baseline](../../results/g1_markdown_initial/run.json) и [reuse-check](../../results/g1_markdown_reuse_check/run.json) completed, по 20 вопросов, errors=0/no_relevant_chunks=0. Один index_id: `49a0a1a1baa61ca0e02babf717626a341a92686ff27fcc2b67b487d002753221`, build_id `403ac973-45b6-44fd-b663-ebc10f1a9389`. 3175 points/unique IDs, manifest raw tokens 1093452. Original float32 vectors: 9753600 B (9.302 MiB). Для этой коллекции `du -s -B1` в контейнере: 30089216 B (28.695 MiB) allocated blocks; `du -sb`: 355194873 B (338.740 MiB) apparent size с sparse/preallocated WAL. Это разные виды размера, не RAM/VRAM. Артефакты каждого run занимают около 1.5 MiB.

| Метрика | @1 | @5 | @10 |
| --- | --- | --- | --- |
| Precision | 0.6000 | 0.2900 | 0.1650 |
| Recall | 0.404643 | 0.748452 | 0.805595 |
| Evidence Coverage | 0.438333 | 0.841667 | 0.895000 |

MRR@10=0.7375. Все агрегаты обоих runs идентичны; офлайн-пересчёт по сохранённым gold/manifest/hits также идентичен. [metrics.json](../../results/g1_markdown_initial/metrics.json) хранит все значения, per-question data и fact/alternative coverage — рядом в JSONL. Средний raw_tokens@5=1930.85, @10=3817.25; это embedding tokens, не LLM budget.

| Стадия | Baseline, s | Reuse, s |
| --- | --- | --- |
| Весь run | 133.061 | 16.339 |
| Splitting/metadata | 6.357 | reused, null |
| GPU document model load | 5.287 | reused, null |
| Embedding | 87.912 | reused, null |
| Upload | 2.797 | reused, null |
| Index readiness wait | 0.715 | reused, null |
| CPU query model load | 9.428 | 8.873 |

Остальные стадии, индивидуальные query/search и initial build provenance сохранены в run.json/metrics.json; reuse не выдаётся за нулевую стоимость новой сборки. Worker directories до/после reuse: 1/1, build_id тот же, новый GPU process не создавался. Первый retrieval 348.0 ms; прогретые 19: mean 136.95 ms/median 121.91 ms/max 264.06 ms. Это retrieval без LLM, не время полного QA.

BF16 GPU batch 16: Torch peak allocated 2915404288 B (2.715 GiB), reserved 6438256640 B (5.996 GiB); GPU worker peak RSS 2498748416 B. Reserved — кэш аллокатора, его нельзя приравнивать к чистой физической VRAM. После worker GPU освобождён; CPU-query peak RSS 2648383488 B. Corpus text и вопросы не менялись. Stage caches не добавлены.

Проверки: полный Python suite с явными test dirs и существующим --input-build — 597 passed, 2 live opt-in skipped (56.86 s); Ruff check/format — PASS. Model и Qdrant live probes выполнены отдельно и описаны в C1. Первый bare pytest дал 77 setup errors из-за отсутствующего ingestion --input-build; правильная полная команда прошла все 77.

Реальные версии/условия/пробы: [TECHNICAL_PROBES](TECHNICAL_PROBES.md). Пользовательские команды и различие quick/full pytest: [CLI](../user_docs/CLI.md).

## Текущее состояние оценки

QA20, 10 retrieval runs, рецензия и отчёт готовы. В [qa_review.csv](../../results/qa_final/qa_review.csv) оценены все 20 ответов: correctness — 15 yes / 4 partial / 1 no; completeness — 12 yes / 8 partial; citation_support — 15 yes / 5 partial. Метод `agent_assisted` не заменяет независимую человеческую оценку. `qa_summary.json` остаётся исходным снимком запуска до рецензирования; текущие оценки и разбор ошибок используются в [отчёте](../../report/LAB2_REPORT.md).

## C3 — Nemotron, API и Streamlit: PASS

2026-11-06, тот же baseline index/build, action=reused: GPU document worker не запускался. Retrieval-only готов за 13.632 s после начала launcher, 3 hits за 230.3 ms HTTP, health retrieval_ready=true/qa_ready=false/mode=retrieval_only; ask 503 qa_disabled, неверный limit 422, второй runtime отклонён. После SIGINT lock освобождён.

Полное demo: внешний процесс готов за 17.159 s; startup events index_ready 2.077 s → cpu_query_loaded 10.468 s → llm_ready 16.006 s → api_ready 16.229 s → ui_started 16.230 s. Cold означает первую QA после старта модели; disk/HF cache не очищались, скачиваний не было. Принятый профиль 8192/1536/256, thinking=false и Nemotron сохранены.

| Запрос | Полный вход | Выход, tokens | CPU query, s | Prompt eval, s | Decode, s | Полный QA, s |
| --- | --- | --- | --- | --- | --- | --- |
| Help, первый/cold | 2931 | 210 | .158 | 1.708 | 3.637 | 5.557 |
| Help, warm | 2931 | 210 | .284 | 1.430 | 3.707 | 5.475 |
| Vortex + Silence, warm | 1683 | 58 | .137 | .858 | .992 | 2.085 |
| Encounter XP, warm | 2670 | 91 | .122 | 1.361 | 1.595 | 3.146 |
| Большой вопрос, warm | 6220 | 85 | 5.661 | 3.478 | 1.513 | 10.760 |
| Help через UI, warm | 2931 | 210 | .110 | 1.480 | 3.689 | 5.428 |

Search 4.8–7.2 ms, context 11.7–29.4 ms, postprocess 0.24–1.09 ms; generation в API включает prompt+decode/HTTP. Prompt/decode в таблице — дельты native llama.cpp metrics того же запроса. Полные input counts совпали с prompt_tokens_total, cached input=0 для всех шести. Большой вопрос — техническая синтетическая нагрузка с повторённой заметкой, не дополнительный gold question; полные retrieved chunks прежние. Его CPU embedding 5.66 s виден отдельно и входит в 10.76 s. Все ответы finish=stop, sources только использованные (1–3), citation warnings=0; это не семантические grades.

Три обычных warm: min 2.085/median 3.146/max 5.475 s. Самый долгий измеренный случай 10.760 s; превышений 30 s в этой пробе нет. Это небольшая техническая выборка, не гарантия для любой длины ответа до 1536. UI round trip вместе с AppTest 6.077 s, backend 5.428 s; отрендерены 3 раскрываемых источника с raw text и атрибуцией страниц. Браузерная визуальная приёмка не выполнялась: проверены реальный Streamlit server и AppTest.

Пик NVML по всей GPU 4279 MiB из 6144, фон до 664/после 666 MiB. RAM: пик суммы PSS своего дерева 7977704448 B (7.430 GiB) при загрузке LLM; это учитывает shared pages пропорционально, не сумма дублированных RSS. В пике API PSS 2395288576 B, llama 5555906560 B, uv 26509312 B. Постоянный Qdrant и процесс самого измерителя не входят. Сэмплирование примерно 0.5 s, возможен пропуск коротких пиков. Дети найдены по всем threads /proc, включая spawn от supervisor. После demo LLM/UI завершены, lock свободен.

Паспорт и сырые измерения полного demo: [c3-demo.json](../../results/technical/c3-demo.json). При первоначальной разработке обнаружен и исправлен ложный TCP conflict из-за TIME_WAIT; чужой listener по-прежнему отвергается. Итоговые PSS samples учитывают детей всех threads `/proc`; первоначальные неполные RAM samples не используются и удалены. Модель, профиль, вопросы gold и индекс не менялись.

Итоговые проверки C3: полный Python suite с явными test dirs/--input-build — 660 passed, 3 opt-in live skipped за 63.36 s. Эти skip не подменяют отдельно выполненные C1/Task 9/C3 живые пробы. Targeted API/launcher/UI/store/retrieval/CLI — 53 passed до добавления двух socket-регрессий; обе socket-регрессии затем PASS, входят в полный suite. Wheel содержит system.txt с исходными bytes, cwd-independent загрузка PASS. Ruff check/format — PASS, 121 файлов отформатированы.

## C4 — эксперименты и выбор профиля: PASS

[Полное сравнение](EXPERIMENTS.md) · [CSV](../../results/retrieval_comparison.csv) · [Study](../../configs/experiments/study.yaml) · [Evidence](../../results/technical/c4-evidence.json). Десять unique config/index/build IDs, все completed/built, 20 вопросов/0 errors в каждом. Один corpus/gold cohort; 14 CSV строк =10 comparison+4 references.

G1 выбран source_map_recursive H4 по EC@5=.9700/MRR@10=.9750; после G2 сохранён 512/64. G3/G5 происходят от этого dense-контроля; оба G4 — независимо от g3_hybrid. Hybrid EC@5=.946667, no-stem профиль=0.9600, исходный dense=0.9700. Strip=true не меняет EC@5 по 20 вопросам/MRR, но raw_tokens@5 чуть больше; title=false ухудшает EC/MRR. QA selection: configs/experiments/g1_splitters/source_map_recursive.yaml, dense, title=true, strip=false, 5578 points, raw_tokens@5=1099.45. Причины и все индивидуальные question deltas сохранены; оптимальность за пределами gold 20 не заявляется.

Audit: все 10 метрик P/R/EC@1/5/10/MRR@10 совпали с offline recompute, source YAML совпали с snapshots/config_id; native Qdrant green/ready/points/indexed_vectors PASS. Raw G5 manifests совпали по body/ranges/lines/tokens. Измерены allocated/apparent collection bytes, controls не пересобирались. После этапа runtime lock свободен, GPU фон 735 MiB, Qdrant и результаты сохранены.

Полный Python suite: 671 passed, 3 explicit-live skipped за 64.06 s; Ruff check/format PASS, 124 файла. Новые QA-run тесты доказывают actual trace без второго retrieval, раздельные 20/3, пустые grades, неперезапись reviewer CSV и retained failed-run. На момент завершения C4 смысловая оценка ответов и независимое ревью ещё не проводились. Последующая приёмка и результаты ревью описаны ниже.

CSV exporters используют LF; Git diff --check проверяет и сгенерированную сводку. У strip EC@10=.9900 vs 0.9700 контроля: эффект отражён в CSV/EXPERIMENTS, выбор QA сохраняет принятый приоритет EC@5 и лимит 5 передаваемых чанков.

## C5 — QA20, эксплуатация и передача отчёту

[QA-run](../../results/qa_final/run.json) completed/reused, 20 основных вопросов, 0 errors/no_context, весь run 110.107 s с проверкой/загрузкой. Insufficient3 не включены. Все ответы finish=stop, warnings=0, budget violations=0, valid citations присутствуют; это структурные наблюдения, не correctness/completeness/citation_support.

Фактический input 929–2366 токенов. Для 20/20 count равен native usage/prompt_n, cache_n=0, reasoning отсутствует. Все messages восстановлены из сохранённого registry без нового поиска и совпали; registry — первые≤5 фактически извлечённых чанков. В этом прогоне budget drop не понадобился; большой ввод/whole-tail drop отдельно проверены unit/C3, не подменены этими короткими вопросами. Проверены 184 различных retrieved chunks: точные Unicode/body/line slices и hashes совпали. Config/gold/profile/system/context-builder snapshots совпадают с выбранными входами и hashes.

| Полный QA | Время, s |
| --- | --- |
| Первый после запуска LLM | 4.318 |
| Следующие 19: min / mean / median / max | 1.843 / 2.833 / 2.713 / 4.287 |
| Число запросов >30 s | 0 |

Первая генерация отделена; disk/HF cache не очищались. Native timings и все stage timings сохранены в QA JSONL/summary, медленные случаи не скрыты средним. Измерения C3 RAM/VRAM и near-budget 6220 остаются отдельной технической выборкой; QA20 не измеряет расход памяти для максимальных 1536 output tokens.

Свежий процесс demo с теми же index/build готов за 20.105 s, action=reused, новых GPU worker directories нет. Новый вопрос о Prone/standing up отправлен через Streamlit AppTest в настоящий HTTP API: UI roundtrip 2.434 s, backend 2.023 s, 813 input tokens, 2 sources. Оба full passages в UI побуквенно совпали с body; previews 400/флаги/координаты также совпали. Streamlit server health PASS. После SIGINT свои API/UI/LLM endpoints закрыты, lock свободен; Qdrant/10 коллекций и результаты сохранены. Браузерная визуальная приёмка не выполнялась.

Проверки перед независимым review: 671 passed, 3 explicit-live skipped за 65.14 s; Ruff check/format 124 files PASS. Имеющиеся C1 quant/BM25/RRF/persistence/reset и C4 native HNSW/readiness доказательства проверены по сохранённым probes; успешные дорогие пробы без изменений алгоритма повторно не запускались. `--help` всех 7 команд сохранён, сопоставлен с CLI; справочник полей/defaults — с config.py. Исходные пользовательские правки документации сохранены и входят в scope review.

Сохранённые материалы отчёта:

- Выбранный [полный config](../../configs/experiments/g1_splitters/source_map_recursive.yaml): dense, H4, 512/64, title=true, strip=false, 5578 points. Config ID `066ab9331834d48cda3b64423f8f7f2116b803562295e84ef06eadc7ee9a1493`.
- Index ID `c15629b74de71e32103d4e142cbe77d37573c7d50be3fab0450aef14feff6d7a`; collection=`rag_`+ID; build ID `76ed503e-a0a2-4312-a35e-337280402003`. QA и demo переиспользовали именно эту полную сборку.
- [Сравнение/причины](EXPERIMENTS.md), [CSV всех 10 профилей](../../results/retrieval_comparison.csv), [study](../../configs/experiments/study.yaml), исходные retrieval run/metrics/per_question/manifest/relevance доступны без Qdrant.
- [QA answers/реальный контекст](../../results/qa_final/qa_answers.jsonl), [worksheet](../../results/qa_final/qa_review.csv), [сводка](../../results/qa_final/qa_summary.json), снимки profile/prompts и полный паспорт в той же папке. Все 20 строк worksheet теперь имеют `review_status=reviewed`, `review_method=agent_assisted`, `review_version=qa20-semantic-v1`. Это отдельная рецензия сохранённых ответов, без нового QA-прогона.
- [Дополнительные измерения C3/C4 и анализ G1–G5](../../results/technical/README.md), [технические условия](TECHNICAL_PROBES.md), [запуск/диагностика](../user_docs/CLI.md). Они дополняют штатные runs; одноразовые приёмочные скрипты не входят в публичный интерфейс.

Оставшиеся границы: выбор сделан на том же небольшом gold 20, без статистической общности; 3 insufficient опциональны; page attribution остаётся разделовой; нет истории/streaming/reranker/MCP/Viewer/кэшей стадий. Эти функции не входят в согласованный MVP. Работа требует доступных внешних GGUF/llama.cpp/HF cache и доступного хранилища Qdrant, веса не включены в репозиторий.

## Итог независимого ревью и проверка исправлений

6 ноября 2026 года независимый рецензент проверил весь реализованный объём, включая тогдашние незакоммиченные документы; затем он же проверил исправления и регрессии. Офлайн пересчитаны 10 retrieval runs, проверены 49802 manifest records и 20 QA traces. Critical не выявлены; финальный verdict **Yes**, R1–R5 закрыты, обязательных замечаний не осталось. Это историческая приёмка: её одноразовые brief и review не сохраняются как зависимости проекта.

Исправлено: R1 — timeout/DNS/protocol/неопределённость прекращают startup до GPU/LLM/Compose, только ECONNREFUSED разрешает отсутствующий сервис; R2 — общий native URL для /v1 и /v1/; R3 — eligibility проверяет собственный reference/cohort и dependent selected base; R4 — актуализация служебного контекста разработки; R5 — owned group cleanup после выхода wrapper и эскалация TERM→KILL для оставшегося потомка с проверяемым inherited FLOCK. Каждый программный дефект воспроизведён RED→GREEN. Конфиги, corpus/gold, алгоритмы embeddings/чанков, IDs и исходный QA20 не изменялись; повторной индексации/QA20 не требовалось.

Финальный полный Python suite: **699 passed, 3 explicit-live skipped, 71.13 s**; Ruff check/format 126 files PASS. После R3 экспорт текущей C4-карты побайтово совпал с прежними 14 строками/all eligible. Исторический дополнительный demo после исправлений: готов 19.052 s, UI 2.269 s, 2 exact raw passages, прежние IDs/reused, без нового GPU worker; после SIGINT own endpoints закрыты и lock захвачен повторно. Все неизменяемые экспериментальные runs сохранены; отдельный журнал smoke удалён.

Optional **O1** отложен отдельно: lock внутри opt-in embedding/Qdrant live probes. Сейчас инструкция требует остановить другой runtime перед такими пробами; это усиление процедуры, приёмку MVP не блокирует. На момент C5 содержательная проверка QA20 ещё не выполнялась; впоследствии заполнена agent-assisted рецензия. Браузерный визуальный осмотр и статистическая общность не подтверждены.

## После C5 — перенос хранилища Qdrant в проект

2026-11-06 по отдельному поручению пользователя хранилище перенесено в [data/qdrant/](../../data/qdrant/). [Compose](../../compose.yaml) подключает его к `/qdrant/storage` через bind mount; хостовая файловая система ext4 в WSL. Каталог исключён из Git. Путь фиксирован в Compose; прежняя настройка `QDRANT_STORAGE_VOLUME` удалена из `.env.example`, локального `.env` и runtime.

Копирование выполнено при остановленном Qdrant с сохранением прав и разреженных файлов. Для всех **1582 файлов** совпали SHA-256, пути и атрибуты. После первого запуска и повторного перезапуска проверены все **10 коллекций / 49802 points**: прежние `index_id`/`build_id`, паспорта сборок, схемы, ID и полные payload записей. Все 10 конфигураций получили `index_action=reused`, документные эмбеддинги не пересчитывались, новых GPU workers нет. Поиск с одним CPU-эмбеддингом вопроса прошёл по всем 7 dense и 3 hybrid профилям.

После этих проверок исходный named volume **`dnd_rag_lab2_qdrant` удалён**. Qdrant оставлен работающим на данных проекта. Исходные `results/` и измерения C2–C5 не изменялись. Проверки затронутых настроек/preflight/build/launcher/runtime/CLI: **61 passed, 12.05 s**; Ruff check/format двух изменённых модулей PASS. Это отдельная проверка переноса, не новый прогон качества QA или всей программы экспериментов.

Одноразовый скрипт переноса, inventories, manifests и журналы проверки удалены после завершения миграции. Описание выше фиксирует исторический результат; оно не требует запускать миграцию повторно. Для обычной работы используются Compose и штатный CLI.

После удаления старого volume публичный `build-index` для выбранного профиля также вернул `action=reused`, исходный `build_id=76ed503e-a0a2-4312-a35e-337280402003` и reused/null стадии подготовки. В той же исторической проверке Docker подтвердил единственный bind mount из `data/qdrant/`, отсутствие старого named volume и работающий контейнер.

## Повторяемые проверки

Полные команды тестов и opt-in флаги приведены в [CLI](../user_docs/CLI.md#проверки-проекта). Полный Python-набор требует существующего resolved build через `--input-build`; unit-тесты используют временные fixtures. Live-пробы моделей, Qdrant и llama.cpp по умолчанию skipped и сохраняют JSON/копии логов в `tmp_path`. Их запуск не нужен для пересчёта отчёта.

[Сборщик отчёта](../../report/scripts/build_report_artifacts.py) независимо пересчитывает P/R/EC/MRR десяти runs по полным manifests/gold/hits, проверяет фактический QA-контекст и строит шесть графиков. [Механический аудит вопросов](../../data/questions/audit/audit_questions.py) проверяет структуру, точные цитаты, координаты и два дерева разделов по текущему корпусу, без генерационного промпта; смысловая оценка gold хранится отдельно. Эти проверки не запускают индексацию, Qdrant или LLM.

Проверка после уборки 11 ноября 2026 года: полный Python-набор с подготовленным `--input-build` — **702 passed, 3 skipped, 83.11 s**; Ruff check и format — PASS для 129 файлов (включая сборщик отчёта и аудит). Отчёт пересобран без рабочего архива: исходные данные, численные таблицы и шесть изображений не изменились. Механический аудит — PASS, 23 вопроса/78 точных альтернатив; проверены 536 локальных ссылок в 54 действующих Markdown-документах и все 6 изображений отчёта. Реальные GPU/LLM/Qdrant-пробы, десять экспериментов, QA20, индексация и миграция при этой проверке не запускались.
