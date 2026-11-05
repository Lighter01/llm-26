# Конфигурации экспериментов

YAML выбирается через `--config`; каждый вариант самостоятельный, без наследования.
Неизвестные поля, повторные ключи, неверные типы и границы — ошибка. Пути раскрываются
от корня lab2, `~` — от home. Имя запуска задаётся только CLI. Локальные адреса —
в [.env.example](../../.env.example), LLM — в [отдельном профиле](../llm/local.yaml).

| Поле | Тип / default | Значения и влияние |
| --- | --- | --- |
| schema_version | int, 1 | Только 1. |
| corpus.directory | path, обязательно | Три книги и source_map.jsonl, без поиска latest. |
| chunking.strategy | str, markdown | markdown / recursive / source_map_recursive. |
| chunking.chunk_size | int, 512 | 100..1000 сырых токенов embedding tokenizer. |
| chunking.chunk_overlap | int, 64 | 0..size−1; целевой максимум overlap готового splitter. |
| chunking.max_heading_level | int, 4 | 1..6; первичные границы только custom-стратегии. |
| embedding.model_id | str, google/embeddinggemma-2 | Адаптер text-only; произвольные архитектуры не гарантированы. |
| embedding.revision | str, обязательно | Конкретный 40-символьный Git SHA модели и tokenizer. |
| embedding.dimension | int, 768 | 128 / 256 / 512 / 768, штатная нормализация после усечения. |
| embedding.include_title | bool, true | Книга и paths в embedding input; false → `title: none`. |
| embedding.strip_markdown_headings | bool, false | Удалять mapped H1–H6 только из embedding input. Независим от title. |
| embedding.query_prompt_name | str, QuestionAnswering | QuestionAnswering / SearchQuery; только query, проверяется у модели. |
| embedding.document_dtype | str, bfloat16 | bfloat16 / float32 на GPU, без fallback; query всегда FP32 CPU. |
| embedding.document_batch_size | int, 16 | >0; техническое потребление памяти, не меняет index_id. |
| index.hnsw.m | int, 16 | ≥2; связность графа, память/стоимость сборки. |
| index.hnsw.ef_construction | int, 100 | >0; ширина поиска при построении (API ef_construct). |
| index.quantization | str, none | none / scalar_int8 / turboquant_4bit; исходные float32 сохраняются. |
| retrieval.mode | str, dense | dense / hybrid (native payload BM25 + dense, RRF). Меняет build. |
| retrieval.limit | int, 10 | ≥10 для оценки @1/5/10. |
| retrieval.ef_search | int, 128 | >0; query HNSW, reuse. |
| retrieval.hybrid_candidates_per_branch | int, 20 | >0 и ≥limit для hybrid; кандидаты каждой ветви. |
| retrieval.rrf_constant | int, 2 | >0; сумма 1/(c+rank0), равные веса. Только query. |
| bm25.tokenizer | str, word | Закреплённый профиль word. Только hybrid build. |
| bm25.lowercase | bool, true | Независимое приведение термов к нижнему регистру. |
| bm25.stemmer | object/null, {type: snowball, language: english} | null выключает stemming. Только hybrid build. |
| bm25.stopwords | str/null, english | null выключает English stopwords. Только hybrid build. |
| bm25.k1 | float, 1.2 | ≥0; насыщение TF, API k. Только query. |
| bm25.b | float, 0.75 | 0..1; поправка на длину документа. Только query. |
| evaluation.questions | path, data/questions/validated/questions.yaml | Validated gold и соседний validation_report.json. |
| evaluation.k | list[int], [1,5,10] | Обязательные три среза, другой список отклоняется. |
| evaluation.mrr_k | int, 10 | Только 10. |

Фиксированы: text-only, Normalize/Cosine, float32 stored vectors, named `dense`,
один shard, FP32 CPU query. Квантованный поиск использует rescore=false/ignore=false.
Полный input эмбеддера проверяется с prefix/special tokens, без обрезания.

Смена corpus, splitter/size/overlap, embedding input/dtype/dimension/revision,
HNSW build или hybrid preprocessing означает полный новый build. Query-параметры,
gold и batch не меняют fingerprint. Dense игнорирует BM25 при вычислении identity.
Готовая совместимая коллекция переиспользуется целиком; `--rebuild` повторяет все
стадии. Кэшей chunks/vectors и достройки dense → hybrid нет.

На текущем этапе подготовлен [baseline G1](g1_splitters/markdown.yaml).
Карта групп и результаты добавляются вместе с аналитическим runner.
