# Проверка реализации

Этап C2: Tasks 1–8. QA/LLM/API/UI, полная серия экспериментов и финальное независимое
ревью относятся к следующим этапам. Skipped live tests не считаются доказательством.

| Требование | Проверенное поведение / доказательство |
| --- | --- |
| A01 | Готовый corpus: 687745 слов, 4536 sections; XPHB имеет262 различных явно атрибутированных печатных page endpoints (больше50). Gold20+3/59 facts, hashes и exact slices проверены read-only. |
| A02–A03 | Три реальные splitter по embedding tokenizer, max512; exact-slice violations=0, repeated paths/Unicode/ownership/partial headings покрыты unit tests. |
| A04 | EG2 revision f9972ac..., text-only BF16 GPU/FP32 CPU, finite shape128/256/512/768; full input без truncation. |
| A05 | Qdrant1.20 server/client, BM25/RRF/quantization реальные запросы, HNSW1024 indexed, persistence restart. |
| A06–A07 | Fingerprint excludes query/batch/inactive BM25, stable UUIDs/upsert, building not ready, safe targeted reset twice, foreign/network errors do not delete. |
| A08 | Shared dense/hybrid store tested live; pure metric fixtures prove50% boundary, full Rq, fractional EC, alternatives/union/equal weights. |
| A09 | Runner tests: unique names, retained failures, honest reuse/null timings, offline recomputation. Реальные baseline/reuse PASS, числа ниже. |
| A13 частично | Real subprocess tests: second runtime rejected, child holds lock after parent SIGKILL, own cleanup preserves sentinel. API generation gate ещё не реализован. |
| A16 частично | ARCHITECTURE/CLI/config reference/module navigation обновлены для Tasks1–8. Остальные команды будут документированы вместе с реализацией. |
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

LLM, budget/token-template parity, numeric citations, HTTP/API/UI и QA20 ещё не готовы
(A10–A12/A15). Девять остальных configs и групповые сравнения ещё не выполнены (A14).
Литературный отчёт и семантическое рецензирование QA пользователь поручит отдельно.
