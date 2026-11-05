# Проверка реализации

Этап C3: Tasks 1–11. Реализованы локальная LLM, QA/API/UI. Полная серия экспериментов,
QA20 и финальное независимое ревью относятся к следующим этапам. Skipped live tests не считаются доказательством.

| Требование | Проверенное поведение / доказательство |
| --- | --- |
| A01 | Готовый corpus: 687745 слов, 4536 sections; XPHB имеет262 различных явно атрибутированных печатных page endpoints (больше50). Gold20+3/59 facts, hashes и exact slices проверены read-only. |
| A02–A03 | Три реальные splitter по embedding tokenizer, max512; exact-slice violations=0, repeated paths/Unicode/ownership/partial headings покрыты unit tests. |
| A04 | EG2 revision f9972ac..., text-only BF16 GPU/FP32 CPU, finite shape128/256/512/768; full input без truncation. |
| A05 | Qdrant1.20 server/client, BM25/RRF/quantization реальные запросы, HNSW1024 indexed, persistence restart. |
| A06–A07 | Fingerprint excludes query/batch/inactive BM25, stable UUIDs/upsert, building not ready, safe targeted reset twice, foreign/network errors do not delete. |
| A08 | Shared dense/hybrid store tested live; pure metric fixtures prove50% boundary, full Rq, fractional EC, alternatives/union/equal weights. |
| A09 | Runner tests: unique names, retained failures, honest reuse/null timings, offline recomputation. Реальные baseline/reuse PASS, числа ниже. |
| A10–A11 | Точный полный prompt, whole-tail budget и Markdown Citation Registry:21 unit tests PASS; реальный count/usage23/6027, C3 inputs1683–6220. |
| A12 | Живые serve-retrieval/demo, один CPU encoder/API worker; Streamlit HTTP health и AppTest с настоящим QA API PASS. |
| A13 | Runtime lock и QA429; parent-death/cleanup повторены с реальными Uvicorn/Streamlit, чужой sentinel сохраняется; быстрый restart после TIME_WAIT проверен. |
| A16 частично | ARCHITECTURE/CLI/config reference/module navigation обновлены для Tasks1–11. Команды следующих задач будут документированы вместе с реализацией. |
| A17 частично | Targeted tests и Ruff выполнены. Независимое review запланировано после полного плана. |

## C2 — baseline и reuse: PASS

[Baseline](../../results/g1_markdown_initial/run.json) и
[reuse-check](../../results/g1_markdown_reuse_check/run.json) completed, по20 вопросов,
errors=0/no_relevant_chunks=0. Один index_id:
`49a0a1a1baa61ca0e02babf717626a341a92686ff27fcc2b67b487d002753221`,
build_id `403ac973-45b6-44fd-b663-ebc10f1a9389`.
3175 points/unique IDs, manifest raw tokens1093452.
Original float32 vectors:9753600B (9.302MiB). Для этой коллекции `du -s -B1`
в контейнере:30089216B (28.695MiB) allocated blocks; `du -sb`:355194873B
(338.740MiB) apparent size с sparse/preallocated WAL. Это разные виды размера,
не RAM/VRAM. Артефакты каждого run занимают около1.5MiB.

| Метрика | @1 | @5 | @10 |
| --- | --- | --- | --- |
| Precision | 0.6000 | 0.2900 | 0.1650 |
| Recall | 0.404643 | 0.748452 | 0.805595 |
| Evidence Coverage | 0.438333 | 0.841667 | 0.895000 |

MRR@10=0.7375. Все агрегаты обоих runs идентичны; офлайн-пересчёт по сохранённым
gold/manifest/hits также идентичен. [metrics.json](../../results/g1_markdown_initial/metrics.json)
хранит все значения, per-question data и fact/alternative coverage — рядом в JSONL.
Средний raw_tokens@5=1930.85, @10=3817.25; это embedding tokens, не LLM budget.

| Стадия | Baseline, s | Reuse, s |
| --- | --- | --- |
| Весь run | 133.061 | 16.339 |
| Splitting/metadata | 6.357 | reused, null |
| GPU document model load | 5.287 | reused, null |
| Embedding | 87.912 | reused, null |
| Upload | 2.797 | reused, null |
| Index readiness wait | 0.715 | reused, null |
| CPU query model load | 9.428 | 8.873 |

Остальные стадии, индивидуальные query/search и initial build provenance сохранены
в run.json/metrics.json; reuse не выдаётся за нулевую стоимость новой сборки.
Worker directories до/после reuse:1/1, build_id тот же, новый GPU process не создавался.
Первый retrieval348.0ms; прогретые19: mean136.95ms/median121.91ms/max264.06ms.
Это retrieval без LLM, не время полного QA.

BF16 GPU batch16: Torch peak allocated2915404288B (2.715GiB), reserved6438256640B
(5.996GiB); GPU worker peak RSS2498748416B. Reserved — кэш аллокатора, его нельзя
приравнивать к чистой физической VRAM. После worker GPU освобождён; CPU-query peak
RSS2648383488B. Corpus text и вопросы не менялись. Stage caches не добавлены.

Проверки: полный Python suite с явными test dirs и существующим --input-build —
597 passed,2 live opt-in skipped (56.86s); Ruff check/format — PASS. Model и Qdrant
live probes выполнены отдельно и описаны в C1. Первый bare pytest дал77 setup errors
из-за отсутствующего ingestion --input-build; правильная полная команда прошла все77.

Реальные версии/условия/пробы: [TECHNICAL_PROBES](TECHNICAL_PROBES.md).
Пользовательские команды и различие quick/full pytest: [CLI](../user_docs/CLI.md).

## Ограничения текущего этапа

QA20 и его review worksheet ещё не выполнены (A15). Девять остальных configs и
групповые сравнения ещё не выполнены (A14). Независимое ревью — после полного плана.
Литературный отчёт и семантическое рецензирование QA пользователь поручит отдельно.

## C3 — Nemotron, API и Streamlit: PASS

2026-11-06, тот же baseline index/build, action=reused: GPU document worker не
запускался. Retrieval-only готов за13.632s после начала launcher, 3 hits за230.3ms
HTTP, health retrieval_ready=true/qa_ready=false/mode=retrieval_only; ask503 qa_disabled,
неверный limit422, второй runtime отклонён. После SIGINT lock освобождён.

Полное demo: внешний процесс готов за17.159s; startup events index_ready2.077s →
cpu_query_loaded10.468s → llm_ready16.006s → api_ready16.229s → ui_started16.230s. Cold означает первую QA после
старта модели; disk/HF cache не очищались, скачиваний не было. Принятый профиль
8192/1536/256, thinking=false и Nemotron сохранены.

| Запрос | Полный вход | Выход, tokens | CPU query, s | Prompt eval, s | Decode, s | Полный QA, s |
| --- | --- | --- | --- | --- | --- | --- |
| Help, первый/cold | 2931 | 210 | .158 | 1.708 | 3.637 | 5.557 |
| Help, warm | 2931 | 210 | .284 | 1.430 | 3.707 | 5.475 |
| Vortex + Silence, warm | 1683 | 58 | .137 | .858 | .992 | 2.085 |
| Encounter XP, warm | 2670 | 91 | .122 | 1.361 | 1.595 | 3.146 |
| Большой вопрос, warm | 6220 | 85 | 5.661 | 3.478 | 1.513 | 10.760 |
| Help через UI, warm | 2931 | 210 | .110 | 1.480 | 3.689 | 5.428 |

Search4.8–7.2ms, context11.7–29.4ms, postprocess0.24–1.09ms; generation в API
включает prompt+decode/HTTP. Prompt/decode в таблице — дельты native llama.cpp
metrics того же запроса. Полные input counts совпали с prompt_tokens_total, cached
input=0 для всех шести. Большой вопрос — техническая синтетическая нагрузка с
повторённой заметкой, не дополнительный gold question; полные retrieved chunks прежние.
Его CPU embedding5.66s виден отдельно и входит в10.76s. Все ответы finish=stop,
sources только использованные (1–3), citation warnings=0; это не семантические grades.

Три обычных warm: min2.085/median3.146/max5.475s. Самый долгий измеренный случай10.760s;
превышений30s в этой пробе нет. Это небольшая техническая выборка, не гарантия для
любой длины ответа до1536. UI round trip вместе с AppTest6.077s, backend5.428s;
отрендерены3 раскрываемых источника с raw text и атрибуцией страниц. Браузерная
визуальная приёмка не выполнялась: проверены реальный Streamlit server и AppTest.

Пик NVML по всей GPU4279MiB из6144, фон до664/после666MiB. RAM: пик суммы PSS
своего дерева7977704448B (7.430GiB) при загрузке LLM; это учитывает shared pages
пропорционально, не сумма дублированных RSS. В пике API PSS2395288576B, llama
5555906560B, uv26509312B. Постоянный Qdrant и процесс самого измерителя не входят.
Сэмплирование примерно0.5s, возможен пропуск коротких пиков. Дети найдены по всем
threads /proc, включая spawn от supervisor. После demo LLM/UI завершены, lock свободен.

Паспорт и сырые измерения: [demo](../../.agents/work/implementation/c3-demo.json),
[retrieval-only](../../.agents/work/implementation/c3-retrieval.json). Начальный
неполный технический прогон сохранён отдельно: четыре QA были успешны, генератор
тестового большого вопроса не достиг длины. Повтор выявил/исправил ложный TCP conflict
из-за TIME_WAIT; регрессия RED→GREEN, чужой listener по-прежнему отвергается.
Первоначальные RAM samples не учитывали детей non-main threads и не используются.
Модель, профиль, вопросы gold и индекс не менялись.

Итоговые проверки C3: полный Python suite с явными test dirs/--input-build —
660 passed,3 opt-in live skipped за63.36s. Эти skip не подменяют отдельно выполненные
C1/Task9/C3 живые пробы. Targeted API/launcher/UI/store/retrieval/CLI —53 passed
до добавления двух socket-регрессий; обе socket-регрессии затем PASS, входят в полный
suite. Wheel содержит system.txt с исходными bytes, cwd-independent загрузка PASS.
Ruff check/format — PASS,121 файлов отформатированы. Обязательная пауза после Task11.
