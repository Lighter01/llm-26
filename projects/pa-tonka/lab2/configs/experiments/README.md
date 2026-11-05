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

Подготовлены10 полных YAML, включая [baseline G1](g1_splitters/markdown.yaml).
В resolved snapshot сохраняются shard=1, datatype=float32, Cosine,
indexing_threshold=1 KB (build) и full_scan_threshold=10 KB (planner).
При grey после restart меняется только runtime max_optimization_threads на 1/2;
фактическое действие сохраняется в metadata коллекции.
Карта групп и выбранные базы — [study.yaml](study.yaml); измерения выполняются последовательно.

## Карта study

| Поле | Тип / default | Значение |
| --- | --- | --- |
| schema_version | int, обязательно | Только 1. |
| groups | mapping[str,group], обязательно | Имена групп, например G1..G5. |
| qa_selection | object/null, null | Выбранный retrieval-профиль для последующего QA20. |
| qa_selection.run | str, обязательно в object | Имя completed retrieval-run. |
| qa_selection.config | str, обязательно в object | Полный project-relative YAML path выбранного профиля. |
| qa_selection.reason | str, непустая | Основание выбора по сохранённым сравнениям. |
| group.requires_base | bool, обязательно | G1 false, зависимые G2–G5 true. |
| group.selected_base_run | str/null, null | Имя completed retrieval-run под results; null блокирует dependent group. |
| group.selection_reason | str/null, null | Причина выбора базы по EC@5, MRR@10 и затратам. |
| group.comparisons | list[object], обязательно | Самостоятельные полные конфиги этой группы. |
| comparison.config | str, обязательно | Project-relative YAML path; однозначно сопоставляется с --config. |
| comparison.run | str/null, null | Имя сохранённого comparison run; исполнитель обновляет после завершения. |
| comparison.reference_run | str/null, null | Контрольный run; default — selected_base_run. Для initial G1 null. |
| comparison.changed_parameters | list[str], [] | Dotted paths полей YAML, точно соответствуют отличиям от reference snapshot. |

Run/base/reference — безопасные имена папок, config — явный путь. База/reference должны
быть completed, иметь тот же corpus/gold. Снимок group/reference/changes/reason пишется
в run.json; последующее редактирование карты не меняет историю. Runner не меняет YAML.
Карта не наследует параметры и не запускает следующую группу сама. До фактического выбора
зависимые базы остаются null, а их полные YAML считаются заготовками. Reuse-check не включается
в обязательные 10 сравнений.

## Программа G1–G5 и сводка

В репозитории10 полных YAML, без наследования. G1:markdown/recursive/source_map_recursive
(512/64,H4). G2:копии победителя G1 с512/128 и768/64. G3:hybrid-копия лучшей dense
базы G1/G2. G4:две независимые копии G3 — HNSW32/200/256 и stemmer=null,k1=1.5,b=.5.
G5:копии той же dense базы с title/strip=true/true иfalse/false. Невыбранные
зависимости в study имеют selected_base_run=null; соответствующие YAML — заготовки,
которые полностью обновляются по фактическим результатам до запуска.

У dependent группы explicit reference_run должен совпадать с selected_base_run,
а selection_reason — быть непустой строкой. Runner проверяет completed retrieval
reference, общий corpus/gold и точную declared delta всех эффективных полей. Это
не автоматический DAG: базы выбираются явно после сравнения EC@5, MRR@10 и затрат.

Корневое `qa_selection` — null до выбора; затем объект `{run,config,reason}`.
run — сохранённый retrieval-run, config — полный YAML, reason — обоснование
по всей обязательной серии. Это выбор для следующего QA20, не смысловая оценка QA.

`summarize-results --study PATH --output PATH` читает только study и сохранённые
run/metrics JSON. CSV содержит comparison и reference строки; один прежний контроль
может присутствовать в нескольких группах без повторной индексации. Разные corpus/
gold/metric versions получают разные comparison_cohort; comparison_eligible=false
и comparison_error показывают несопоставимость. Failed/missing/not_run видны явно;
failed не получает успешных метрик. Агрегирования разных runs в одну метрику нет.

Сохраняются все P/R/EC@1/5/10,MRR@10, количество чанков/векторов, средний raw_tokens/
returned_count@k, отдельные all/warm mean/median/max/min, first query и stage timings.
preparation_ms — сумма измеренных tokenizer/split/document load/embedding/upload/
index wait/BM25 стадий только для built/rebuilt; для reuse пусто.
original_preparation_ms — та же сумма из сохранённого паспорта исходной сборки,
не время её повторения. Пропущенные стадии пусты, а не фиктивные нули.
Общий wall_time_ms включает проверку/reuse, CPU model и20 запросов. Пути к исходным
run/config snapshots сохранены. Сводку можно перезаписать; файлы внутри run защищены.
