# Технические пробы

Ниже приведены исторические пробы совместимости и измерения 5–6 ноября 2026 года (Europe/Moscow). Они описывают тогдашние версии и условия, а не результаты новой проверки. Разработка и независимое ревью завершены. Одноразовые логи удалены; постоянные дополнительные измерения перечислены в [results/technical](../../results/technical/README.md), штатные прогоны — в [EXPERIMENTS.md](EXPERIMENTS.md). Непроведённые проверки не считаются PASS.

После C5 хранилище перенесено в `data/qdrant/` проекта через bind mount. Старый `dnd_rag_lab2_qdrant` удалён после проверки сохранности всех коллекций и reuse без пересборки. Упоминания named volume ниже сохраняют условия исходных проб; [проверка переноса](VALIDATION.md#после-c5--перенос-хранилища-qdrant-в-проект) описывают текущее размещение.

| Проверка | Наблюдение |
| --- | --- |
| Python / uv | system 3.13.1; project uv-managed 3.13.13; uv 0.11.6. |
| CUDA | Elevated nvidia-smi: RTX 3060 Laptop, 6144 MiB; driver 617.42, CUDA UMD 13.4. Sandbox NVML недоступен. |
| Docker | CLI 29.9.2; Desktop initially stopped; `docker desktop start` выполнен. |
| LLM | Согласованный GGUF 5060482240 B; установленный unified llama.cpp serve найден, Task 9/C3 PASS, детали ниже. |
| Model / tokenizer revision | `hf models info google/embeddinggemma-2 --expand sha --format json`: f9972ac22e696a105c482202646979e33e4b5a1e. |
| Qdrant | Server/client 1.20.0; живые BM25/RRF/quantization/persistence PASS, детали ниже. |

Закреплённые API: [EG2 card](https://huggingface.co/google/embeddinggemma-2), [Qdrant 1.20.0](https://github.com/qdrant/qdrant/releases/tag/v1.20.0), [native full-text BM25](https://qdrant.tech/documentation/search/text-search/full-text-search/), [quantization](https://qdrant.tech/documentation/manage-data/quantization/). Версии Python-пакетов закрепляются uv.lock; ниже приведены наблюдения установленного адаптера на дату проб.

## Embedding и реальные координаты — PASS

`uv run --group test python -m pytest tests/rag/integration/test_embedding_live.py --run-models -q` → 1 passed, 40.57 s (после выявления и добавления torchvision 0.29.2, необходимого AutoProcessor даже в text-only режиме). Model config действительно имеет vision_config=None/audio_config=None; dtype BF16, Torch 2.15.0+cu132. CPU query FP32. Полный snapshot загружен в обычный HF cache. ST 6.2.0, Transformers 5.22.1. Project Python: 3.13.13 (uv-managed).

| Splitter 512/64 | Чанков | min / median / max raw tokens | Split/metadata, s |
| --- | --- | --- | --- |
| Markdown | 3175 | 3 / 387 / 512 | 6.657 |
| Recursive | 2848 | 4 / 466 / 512 | 7.340 |
| Source map H4 → Recursive | 5578 | 1 / 146 / 512 | 6.655 |

По всем книгам exact-slice violations=0. Body: 3869486 Unicode-символов, 687745 whitespace-слов, 4536 разделов карты. Это большой текстовый корпус; число физических страниц не выводится из числа чанков.

Проверены shape/finite GPU и CPU на 128/256/512/768. GPU batch в пробе — 4: первый encode 892.5 ms, затем 103.6–105.8 ms; пик Torch allocation 796217856 bytes. CPU load 3.582 s, четыре последовательных query 87.9/93.9/88.4/93.6 ms. Это ограниченная проба, не полный build и не замер QA. Оба query prompts доступны. Максимум полного embedding input явно ограничен 8192 независимо от большого tokenizer model_max_length. Новая opt-in проба сохраняет JSON в стандартный временный каталог pytest; команда не создаёт постоянный экспериментальный run.

## Qdrant — PASS (C1)

`uv run --group test python -m pytest tests/rag/integration/test_qdrant_live.py --run-qdrant -q` → 1 passed, 9.07 s. Server 1.20.0 commit 222b2e44ab1c3f17e8246396ead6558e45041df7, qdrant-client 1.20.0. Compose image `qdrant/qdrant:v1.20.0`, volume `dnd_rag_lab2_qdrant`. На 1024 fixed-векторах 128d для каждого none/scalar_int8/TurboQuant bits 4: 1024 indexed, dense находит исходный vector, native payload BM25 — уникальный термин, RRF с c=2/weights=[1,1] даёт совместный первый hit со score=1.0. QuantizationSearchParams ignore=false/rescore=false, исходные float32 сохранены. Проверены collection metadata, reset twice и persistence после restart без удаления volume. Disposable коллекции удалены.

Технические thresholds: indexing_threshold=1 KB (build identity), full_scan_threshold=10 KB (планировщик query; API не разрешает меньше 10). Ready требует green, валидные schema/ payload/count, реальные indexed vectors для достаточно большого fixture и пустые running/queued optimizations; approximate indexed count не обязан равняться points.

После restart 1.20.0 может приостановить optimizer (`grey`) полной ready-коллекции. Пустой optimizer diff из документации не возобновил его в пробе. Отдельная проба подтвердила: изменение max_optimization_threads будит очередь. Store меняет только runtime concurrency на 1 (на 2, если уже 1), записывает last_optimizer_resume в metadata и ждёт завершения. Ready build_id сохраняется; split/embed/upload не повторяются. Неполная building-коллекция всё равно пересоздаётся целиком.

После подключения общего Store.search проба повторена: 1 passed, 8.89 s; проверены и прямые native запросы, и фактическое общее ядро dense/hybrid.

## Первый полный baseline — C2

`experiment --config configs/experiments/g1_splitters/markdown.yaml --experiment-name g1_markdown_initial --study configs/experiments/study.yaml --group G1` → completed/built, 20 questions, 3175 points, 133.061 s wall. Кэш HF уже заполнен C1; скачивание зависимостей/весов не входит в это время. BF16 batch 16 сохранился без fallback. GPU allocated/reserved peak 2.715/5.996 GiB; процесс GPU worker peak RSS 2.327 GiB. Единичный NVML sample во время работы: 5795 MiB, GPU 99%; это не измеренный пик всей VRAM. После завершения worker/runtime NVML sample: 186 MiB. Локальная LLM не запускалась.

Повтор `g1_markdown_reuse_check` → completed/reused, 16.339 s, тот же build_id; tokenizer/splitting/document model/embedding/upload/index wait имеют elapsed_ms=null. Новых GPU workers нет (1 directory до/после). CPU query encoder загружается в каждом новом процессе; загрузка 8.873 s объясняет значительную часть reuse wall time. Метрики обоих runs совпали и воспроизведены офлайн без поиска. Числа, стадии и ограничения: [VALIDATION](VALIDATION.md), [baseline metrics](../../results/g1_markdown_initial/metrics.json).

## Task 9 — Nemotron / точный prompt: PASS

Найден установленный unified llama.cpp `~/.llama-app/llama serve`: 0.4.1-dev, build 11046, commit 60081bb2b (Clang 19.1.7). GGUF тот же согласованный `NVIDIA-Nemotron-3.5-Bolt-E4B-UD-Q4_K_XL.gguf`, 5060482240 B, architecture gemma4/42 blocks. Это checkpoint Nemotron на Gemma4, не fallback на другую модель.

Профиль `configs/llm/local.yaml`: 8192/1536/256, thinking=false, slot 1, gpu_layers=99, batch 512/ubatch 128, q8_0 K/V, KV offload=true, flash on, threads 8, temperature 0/top_p=1/ top_k=40/min_p=0/seed 42. Fit, context shift, prompt caching выключены. Шаблон из GGUF. Native `/apply-template` использует тот же chat parser, что Chat Completions; `/tokenize` add_special=true/parse_special=true. ChatOpenAI 1.7.4 передаёт max_completion_tokens; installed server соблюдает предел.

`pytest tests/rag/integration/test_llama_live.py --run-llama -q`: первый запуск 1 passed 16.63 s, повтор с ресурсами 1 passed 8.25 s. Count/usage 23=23 и 6027=6027; near-budget prompt из реальных passages, без reasoning/truncation. Первый cold startup 11.011 s, повтор 2.654 s. В повторе short 3 output tokens 274.2 ms; 6027 input/32 output — 3.912 s (технический limit 32, finish=length, не оценка QA). GPU used samples: before 672 MiB, ready 4245, short 4249, near-budget 4279, after 672. Это NVML по всей GPU, не private peak процесса. Child peak RSS 5557403648 B. Нативный процесс действительно сохранил inherited project.lock descriptor.

Сервер штатно остановлен, embedding GPU не запускался. Замеры полного ответа/нескольких прогретых QA и большого context выполнены в C3 ниже.

## C3 — полный QA и процессы: PASS

Живые `serve-retrieval` и `demo` с baseline reuse, real HTTP contracts, Streamlit server health и AppTest→реальный API. Первое QA 5.557 s, три ordinary warm min 2.085/median 3.146/max 5.475 s; технический вопрос с 6220 входными токенами 10.760 s, из них CPU query 5.661 s. Все 6 generation finish=stop, actual prompt counts совпали с native metrics, cache 0, shift/truncation 0. Decode примерно 56–58 tokens/s.

NVML whole-device peak 4279 MiB, фон 664/666 MiB до/после. Runtime tree peak PSS 7977704448 B (7.430 GiB), llama в этой точке 5555906560 B; sampled 0.5 s. Model/template SHA256, actual argv/props/profile и per-request native metrics сохранены в [паспорте C3](../../results/technical/c3-demo.json). Подробная таблица и условия измерения — [VALIDATION](VALIDATION.md#c3--nemotron-api-и-streamlit-pass).

Real parent-death/cleanup Uvicorn/Streamlit unit probes PASS, inherited flock сохраняется без родителя; чужой sentinel не завершён. Live второй runtime отклонён, SIGINT завершает LLM/UI и освобождает lock; Qdrant остаётся. Быстрый restart проверяет SO_REUSEADDR как Uvicorn, TIME_WAIT не принимается за чужой listener. Live C3 не заменяет QA20/содержательное рецензирование и выбор retrieval-конфига следующих задач.

## C4 — native индексы и офлайн-пересчёт: PASS

Все 10 обязательных retrieval конфигураций completed/built на общем gold 20. Native 10 коллекций green/ready, points/build IDs совпали с паспортами, indexed_vectors>0. Проверены фактические HNSW m/ef_construct и full_scan_threshold=10, optimizer indexing_threshold=1, dimension=768/Cosine. У 7 dense нет page_content text index, у 3 hybrid он присутствует; native schema сохранены в C4 evidence.

Все P/R/EC@1/5/10/MRR@10 точно совпали с offline recompute. Current YAML равны run snapshots/config_id; G5 body/char/line/token ranges неизменны. CSV 14 строк (10 comparison+4 reference), 1 dataset cohort. allocated/apparent volume bytes измерены после readiness; GPU workers завершены, flock свободен.

Выбран dense H4, 512/64, title=true, strip=false: EC@5 = .9700/MRR@10 = .9750. Полная [таблица и причины](EXPERIMENTS.md), [паспорт C4](../../results/technical/c4-evidence.json). 671 Python tests PASS, 3 live opt-in skipped; Ruff 124 файла PASS. Финальный QA20 и независимый code review относятся к Task 14, не к этой технической пробе.

## C5 — реальный QA20 и выбранный demo: PASS

[QA20](../../results/qa_final/run.json) completed/reused на выбранном source_map dense 512/64, те же index/build, без новой GPU-индексации. 20 фактических traces, config/gold/profile/prompts snapshots; При создании CSV имела 20 строк `not_reviewed`; теперь [agent-assisted рецензия](../../results/qa_final/qa_review.csv) заполнена. Исходный `qa_summary.json` остаётся снимком запуска до рецензии. Input 929–2366; 20/20 native count=usage=prompt_n, cache 0, thinking off, finish stop, warnings 0. Warm 19 min 1.843/mean 2.833/median 2.713/max 4.287 s; первый 4.318 s; полный run 110.107 s. Это реальный QA, но семантическая правильность не выводится из структурных проверок.

Свежий выбранный demo готов 20.105 s; новый Prone-вопрос через AppTest→HTTP 2.434 s, backend 2.023 s, input 813, 2 sources. Полные отрендеренные raw passages и previews/coordinates совпали с body. Server health PASS, новых GPU workers нет. После SIGINT own endpoints закрыты, flock свободен, Qdrant/results сохранены. Визуальный просмотр браузера не выполнялся. [Проверки и ограничения](VALIDATION.md).

После независимого review исправлены preflight/normalization, summary reference eligibility и cleanup живой собственной группы после wrapper exit; metadata/corpus/gold/embedding/LLM profile/QA20 неизменны. Полный gate 699 passed/3 explicit-live skipped 71.13 s, Ruff 126 files PASS. Повторный выбранный demo smoke PASS: ready 19.052 s, UI 2.269 s, 2 exact passages, тот же reused index/build, no new GPU worker, все own endpoints закрыты/lock free. Это повтор затронутого runtime, не новый QA20 или повтор дорогих 10 экспериментов. Same reviewer final verdict Yes, R1–R5 closed; optional probe-lock O1 deferred.

Для повторения используются [opt-in тесты](../user_docs/CLI.md#opt-in-проверки-с-настоящими-компонентами). Их JSON и копии логов направлены в `tmp_path` каждого теста и очищаются обычным механизмом pytest; постоянная папка результатов не используется. Здесь описаны прежние живые запуски; обычный pytest их пропускает.
