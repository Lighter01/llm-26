# Технические пробы

2026-11-05, Europe/Moscow. Реализация Tasks 1–8. Непроведённые проверки не считаются PASS.

| Проверка | Наблюдение |
| --- | --- |
| Python / uv | system 3.13.1; uv 0.11.6. Project interpreter уточняется после sync. |
| CUDA | Elevated nvidia-smi: RTX 3060 Laptop, 6144 MiB; driver 617.42, CUDA UMD 13.4. Sandbox NVML недоступен. |
| Docker | CLI 29.9.2; Desktop initially stopped; `docker desktop start` выполнен. |
| LLM | GGUF существует, 5060482240 bytes. llama-server не в PATH. Task 9 probe ещё не выполнена. |
| Model / tokenizer revision | `hf models info google/embeddinggemma-2 --expand sha --format json`: f9972ac22e696a105c482202646979e33e4b5a1e. |
| Qdrant | Выбран server/client 1.20.0; живые BM25/quantization/persistence ещё не проверены. |

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
