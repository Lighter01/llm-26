# Технические пробы

2026-11-06, Europe/Moscow. Реализация Tasks 1–11. Непроведённые проверки не считаются PASS.

| Проверка | Наблюдение |
| --- | --- |
| Python / uv | system 3.13.1; project uv-managed 3.13.13; uv 0.11.6. |
| CUDA | Elevated nvidia-smi: RTX 3060 Laptop, 6144 MiB; driver 617.42, CUDA UMD 13.4. Sandbox NVML недоступен. |
| Docker | CLI 29.9.2; Desktop initially stopped; `docker desktop start` выполнен. |
| LLM | Согласованный GGUF5060482240B; установленный unified llama.cpp serve найден, Task9/C3 PASS, детали ниже. |
| Model / tokenizer revision | `hf models info google/embeddinggemma-2 --expand sha --format json`: f9972ac22e696a105c482202646979e33e4b5a1e. |
| Qdrant | Server/client 1.20.0; живые BM25/RRF/quantization/persistence PASS, детали ниже. |

Закреплённые API: [EG2 card](https://huggingface.co/google/embeddinggemma-2),
[Qdrant 1.20.0](https://github.com/qdrant/qdrant/releases/tag/v1.20.0),
[native full-text BM25](https://qdrant.tech/documentation/search/text-search/full-text-search/),
[quantization](https://qdrant.tech/documentation/manage-data/quantization/).
Версии Python-пакетов закрепляются uv.lock; измерения живого адаптера ниже по мере выполнения.

## Embedding и реальные координаты — PASS

`uv run --group test python -m pytest tests/rag/integration/test_embedding_live.py --run-models -q`
→ 1 passed, 40.57 s (после выявления и добавления torchvision 0.29.2, необходимого
AutoProcessor даже в text-only режиме). Model config действительно имеет
vision_config=None/audio_config=None; dtype BF16, Torch 2.15.0+cu132. CPU query FP32.
Полный snapshot загружен в обычный HF cache. ST 6.2.0, Transformers 5.22.1.
Project Python: 3.13.13 (uv-managed).

| Splitter 512/64 | Чанков | min / median / max raw tokens | Split/metadata, s |
| --- | --- | --- | --- |
| Markdown | 3175 | 3 / 387 / 512 | 6.657 |
| Recursive | 2848 | 4 / 466 / 512 | 7.340 |
| Source map H4 → Recursive | 5578 | 1 / 146 / 512 | 6.655 |

По всем книгам exact-slice violations=0. Body: 3869486 Unicode-символов,
687745 whitespace-слов, 4536 разделов карты. Это большой текстовый корпус;
число физических страниц не выводится из числа чанков.

Проверены shape/finite GPU и CPU на 128/256/512/768. GPU batch в пробе — 4:
первый encode 892.5 ms, затем 103.6–105.8 ms; пик Torch allocation 796217856 bytes.
CPU load 3.582 s, четыре последовательных query 87.9/93.9/88.4/93.6 ms.
Это ограниченная проба, не полный build и не замер QA. Оба query prompts доступны.
Максимум полного embedding input явно ограничен 8192 независимо от большого
tokenizer model_max_length. Подробные исходные числа —
[embedding-probe.json](../../.agents/work/implementation/embedding-probe.json).

## Qdrant — PASS (C1)

`uv run --group test python -m pytest tests/rag/integration/test_qdrant_live.py --run-qdrant -q`
→ 1 passed, 9.07 s. Server 1.20.0 commit
222b2e44ab1c3f17e8246396ead6558e45041df7, qdrant-client 1.20.0.
Compose image `qdrant/qdrant:v1.20.0`, volume `dnd_rag_lab2_qdrant`.
На 1024 fixed-векторах 128d для каждого none/scalar_int8/TurboQuant bits4:
1024 indexed, dense находит исходный vector, native payload BM25 — уникальный термин,
RRF с c=2/weights=[1,1] даёт совместный первый hit со score=1.0.
QuantizationSearchParams ignore=false/rescore=false, исходные float32 сохранены.
Проверены collection metadata, reset twice и persistence после restart без удаления volume.
Disposable коллекции удалены. [Числа](../../.agents/work/implementation/qdrant-probe.json).

Технические thresholds: indexing_threshold=1 KB (build identity), full_scan_threshold=10 KB
(планировщик query; API не разрешает меньше 10). Ready требует green, валидные schema/
payload/count, реальные indexed vectors для достаточно большого fixture и пустые
running/queued optimizations; approximate indexed count не обязан равняться points.

После restart 1.20.0 может приостановить optimizer (`grey`) полной ready-коллекции.
Пустой optimizer diff из документации не возобновил его в пробе. Отдельная проба
подтвердила: изменение max_optimization_threads будит очередь. Store меняет только
runtime concurrency на 1 (на 2, если уже 1), записывает last_optimizer_resume в metadata
и ждёт завершения. Ready build_id сохраняется; split/embed/upload не повторяются.
Неполная building-коллекция всё равно пересоздаётся целиком.

После подключения общего Store.search проба повторена: 1 passed, 8.89 s;
проверены и прямые native запросы, и фактическое общее ядро dense/hybrid.

## Первый полный baseline — C2

`experiment --config configs/experiments/g1_splitters/markdown.yaml --experiment-name g1_markdown_initial --study configs/experiments/study.yaml --group G1`
→ completed/built,20 questions,3175 points,133.061s wall. Кэш HF уже заполнен C1;
скачивание зависимостей/весов не входит в это время. BF16 batch16 сохранился без fallback.
GPU allocated/reserved peak2.715/5.996GiB; процесс GPU worker peak RSS2.327GiB.
Единичный NVML sample во время работы:5795MiB, GPU99%; это не измеренный пик всей VRAM.
После завершения worker/runtime NVML sample:186MiB. Локальная LLM не запускалась.

Повтор `g1_markdown_reuse_check` → completed/reused,16.339s, тот же build_id;
tokenizer/splitting/document model/embedding/upload/index wait имеют elapsed_ms=null.
Новых GPU workers нет (1 directory до/после). CPU query encoder загружается в каждом
новом процессе; загрузка8.873s объясняет значительную часть reuse wall time.
Метрики обоих runs совпали и воспроизведены офлайн без поиска.
Числа, стадии и ограничения: [VALIDATION](VALIDATION.md),
[baseline metrics](../../results/g1_markdown_initial/metrics.json).

## Task9 — Nemotron / точный prompt: PASS

Найден установленный unified llama.cpp `~/.llama-app/llama serve`:
0.4.1-dev, build11046, commit60081bb2b (Clang19.1.7). GGUF тот же согласованный
NVIDIA-Nemotron-3.5-Bolt-E4B-UD-Q4_K_XL.gguf,5060482240B, architecture gemma4/42 blocks.
Это checkpoint Nemotron на Gemma4, не fallback на другую модель.

Профиль configs/llm/local.yaml:8192/1536/256,thinking=false,slot1,gpu_layers99,
batch512/ubatch128,q8_0 K/V,KV offload=true,flash on,threads8,temperature0/top_p1/
top_k40/min_p0/seed42. Fit,context shift,prompt caching выключены. Шаблон из GGUF.
Native `/apply-template` использует тот же chat parser, что Chat Completions;
`/tokenize` add_special=true/parse_special=true. ChatOpenAI1.7.4 передаёт
max_completion_tokens; installed server соблюдает предел.

`pytest tests/rag/integration/test_llama_live.py --run-llama -q`:
первый запуск1 passed16.63s, повтор с ресурсами1 passed8.25s. Count/usage23=23 и
6027=6027; near-budget prompt из реальных passages, без reasoning/truncation.
Первый cold startup11.011s, повтор2.654s. В повторе short3 output tokens274.2ms;
6027 input/32 output —3.912s (технический limit32, finish=length, не оценка QA).
GPU used samples:before672MiB,ready4245,short4249,near-budget4279,after672.
Это NVML по всей GPU, не private peak процесса. Child peak RSS5557403648B.
Нативный процесс действительно сохранил inherited project.lock descriptor.

[Паспорт пробы](../../.agents/work/implementation/llama-probe.json),
initial probe сохранён отдельно. Сервер штатно остановлен, embedding GPU не запускался.
Замеры полного ответа/нескольких прогретых QA и большого context выполнены в C3 ниже.

## C3 — полный QA и процессы: PASS

Живые `serve-retrieval` и `demo` с baseline reuse, real HTTP contracts, Streamlit
server health и AppTest→реальный API. Первое QA5.557s, три ordinary warm
min2.085/median3.146/max5.475s; технический вопрос с6220 входными токенами10.760s,
из них CPU query5.661s. Все6 generation finish=stop, actual prompt counts совпали
с native metrics, cache0, shift/truncation0. Decode примерно56–58 tokens/s.

NVML whole-device peak4279MiB, фон664/666MiB до/после. Runtime tree peak PSS
7977704448B (7.430GiB), llama в этой точке5555906560B; sampled0.5s. Model/template
SHA256, actual argv/props/profile и per-request native metrics сохранены в
[паспорте C3](../../.agents/work/implementation/c3-demo.json). Подробная таблица и
условия измерения — [VALIDATION](VALIDATION.md#c3--nemotron-api-и-streamlit-pass).

Real parent-death/cleanup Uvicorn/Streamlit unit probes PASS, inherited flock
сохраняется без родителя; чужой sentinel не завершён. Live второй runtime отклонён,
SIGINT завершает LLM/UI и освобождает lock; Qdrant остаётся. Быстрый restart проверяет
SO_REUSEADDR как Uvicorn, TIME_WAIT не принимается за чужой listener. Live C3
не заменяет QA20/содержательное рецензирование и выбор retrieval-конфига следующих задач.
