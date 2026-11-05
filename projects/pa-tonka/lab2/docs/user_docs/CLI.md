# Установка и запуск

Команды запускаются из корня lab2. Нужны Python ≥3.13, uv, Docker Desktop с Linux
engine/WSL integration и CUDA GPU для новой векторизации корпуса. Для обычных
тестов модели, Docker и GPU не нужны.

```bash
uv sync --group test --group lint
cp .env.example .env
uv run --group test python -m pytest -m 'not integration'
uv run --group lint ruff check src tests
uv run --group lint ruff format --check src tests
```

Полный набор включает готовые ingestion integration-тесты. Им требуется явный
существующий resolved build, без автоматического выбора/сборки:

```bash
uv run --group test python -m pytest \
  tests/ingestion/markdown_export tests/ingestion/question_validation tests/rag --input-build \
  data/resolved/5etools/c3d53956346388b222aaaaf4637776f563e201b8/60d007f6a1c747e87aebb75bdb340996700e7e95e9af3ab8adb75b79413f3c81
```

Bare pytest без --input-build намеренно даёт setup errors для ingestion integration;
это существующий контракт подготовки данных. RAG live-проверки включаются отдельно.

uv создаёт окружение и устанавливает пакет. Torch закреплён в uv.lock; в Linux
используется CUDA-сборка. Не заменяйте её CPU-only ради прохождения проверки GPU.
Исходный corpus уже готов, пересборка ingestion не требуется. Его отдельные команды:
[руководство ingestion](../../src/dnd_rag/ingestion/README.md),
[валидатор вопросов](../../src/dnd_rag/ingestion/question_validation/README.md).

`.env` загружается явно. Приоритет: process env → `.env` → default. Пустой cache
означает стандартный Hugging Face cache. Пути раскрываются от lab2, `~` поддерживается.
Секреты и `.env` не попадают в результаты/Git.

| Переменная | Default / назначение |
| --- | --- |
| QDRANT_URL | http://127.0.0.1:6333 |
| QDRANT_STORAGE_VOLUME | dnd_rag_lab2_qdrant, persistent named volume |
| LLAMA_SERVER_BIN | llama-server в PATH, либо явный путь |
| LLM_MODEL_PATH | Путь Nemotron из .env.example; GGUF вне проекта |
| LLM_BASE_URL | http://127.0.0.1:8080/v1 |
| EMBEDDING_CACHE_DIR | Пусто: стандартный HF cache; иначе cache_folder |
| RAG_API_URL | http://127.0.0.1:8000, bind-адрес API и адрес для UI; loopback HTTP |

YAML эксперимента выбирает corpus/chunking/embedding/index/retrieval/evaluation,
а не адреса сервисов. [Все поля и defaults](../../configs/experiments/README.md).
LLM-профиль отдельно фиксирует окно 8192, максимум ответа 1536, запас 256,
максимум 5 чанков и thinking=false. Размещение GPU/batch/KV измерено в Task9;
полный справочник полей и локальный профиль приведены ниже.

Live-проверки включаются только явно: `--run-qdrant`, `--run-models`, `--run-llama`
для соответствующих tests/rag/integration. Skipped не подтверждают совместимость.
Точные результаты: [TECHNICAL_PROBES](../rag/TECHNICAL_PROBES.md).

## Индекс и reset

```bash
uv run python -m dnd_rag build-index --config configs/experiments/g1_splitters/markdown.yaml
# Полностью повторить все стадии, включая embeddings:
uv run python -m dnd_rag build-index --config configs/experiments/g1_splitters/markdown.yaml --rebuild
uv run python -m dnd_rag reset-index --config configs/experiments/g1_splitters/markdown.yaml
uv run python -m dnd_rag reset-index --index-id FULL_64_CHARACTER_SHA256
```

`build-index`: обязательный `--config PATH`, необязательный `--rebuild` (default false).
Совместимая ready-коллекция проверяется и переиспользуется; новая/неполная проходит
полную подготовку. Выход JSON содержит index/build IDs, action/reason и стадии.
Без GPU можно проверить/reuse готовый индекс; новый build требует CUDA. GGUF и llama-server
для этих команд не нужны. Если настроенный llama endpoint работает, GPU build откажет
из-за конфликта; остановите тот сервер самостоятельно, чужой процесс не завершается.

`reset-index`: ровно один обязательный selector `--config PATH` или `--index-id SHA256`.
Первый вычисляет текущий вариант. После смены corpus/зависимостей удаляйте прежний вариант
по полному lowercase ID из run.json. По ID не нужны книги, gold, tokenizer или модели.
Повторное удаление отсутствующей коллекции — успешный no-op (`deleted: false`).
Другие коллекции, results и Docker volume сохраняются. Сетевая ошибка не означает absence.

Обе команды берут общий lock до изменения runtime; второй запуск сразу отказывает.
Зависший файл `.runtime/project.lock` удалять не требуется. Диагностика GPU worker —
`.runtime/builds/<uuid>/worker.log`, request/result/stages рядом. Ctrl+C останавливает
свои процессы. Если parent аварийно умер, живые дети продолжают держать lock.

CLI exit: 0 success (включая reset no-op), 2 invalid config/arguments, 1 runtime failure.
Локальный Qdrant автоматически поднимается через Compose при недоступности; другой
QDRANT_URL должен уже обслуживаться совместимым сервером. Engine запускается отдельно
(`docker desktop start`). Управление постоянной базой:

```bash
docker compose -f compose.yaml up -d qdrant
docker compose -f compose.yaml stop qdrant
```

`stop` сохраняет volume. Не используйте `down -v`, если нужны готовые индексы.
Создание HNSW/BM25 асинхронно: приложение ждёт завершения очереди, одного принятого upsert мало.

Retrieval доступен через Python `Retriever`, аналитический runner и HTTP launcher
`serve-retrieval`. Лимит retrieval по умолчанию
из YAML (10), допустим 1..configured limit. Полные payload и rank/score_kind сохраняются
без LLM; отсутствие score-порога означает, что далёкий по смыслу вопрос обычно всё равно
получит ближайшие dense-векторы. Это не проверка достаточности ответа.

Для evaluation используйте только `data/questions/validated/questions.yaml` и соседний
`validation_report.json` со свежим PASS/written. Runner проверяет hashes и exact slices,
но не перезапускает генератор вопросов/ingestion. После изменения gold сравнивайте все
варианты на одной версии; старые и новые метрики не смешиваются. Основные средние —
20 answerable; 3 insufficient предназначены для отдельного будущего QA-анализа.

## Аналитический запуск

```bash
uv run python -m dnd_rag experiment \
  --config configs/experiments/g1_splitters/markdown.yaml \
  --experiment-name g1_markdown_initial \
  --study configs/experiments/study.yaml --group G1
```

Обязательны `--config PATH` и `--experiment-name NAME`. Необязательный `--rebuild`
по умолчанию false; `--study PATH` и `--group NAME` передаются только вместе.
Без карты можно выполнить самостоятельный эксперимент. Config задаёт все параметры,
CLI выбирает только файл/имя/режим. Name — один компонент `[A-Za-z0-9_.-]+`, кроме `.`/`..`.
Существующая `results/NAME/` отклоняется до изменения индекса. Для повтора выберите новое имя;
failed-run не удаляется и не перезаписывается.

Команда под общим lock проходит corpus/gold validation → ensure полной коллекции →
завершение GPU worker → один CPU query encoder → retrieval 20 вопросов → оценку/export.
LLM и GGUF не требуются. Первое скачивание модели входит в model-load time; для baseline
модель уже загружена C1-пробой. Первый encode отмечается отдельно от последующих.

`results/NAME/` содержит точные `config.yaml`, `gold.yaml`, effective `resolved_config.yaml`,
атомарно обновляемый `run.json`, `chunks_manifest.jsonl`, `relevance.json`,
`per_question.jsonl` с полной ranked выдачей и фактами coverage, `metrics.json`.
В run.json сохраняются index/build/config IDs, action/reason, исходный build provenance,
версии, Git dirty state, устройства и стадии. При reuse splitting/embedding/upload имеют
status=reused и elapsed_ms=null; первоначальные затраты доступны отдельно в build_provenance.
Mean/median/max/min и индивидуальные времена query/search, первый/warm calls, объём top-k
сохранены в metrics.json. Не суммируйте перекрывающуюся работу Qdrant как независимые стадии.

Для проверки reuse повторите ту же команду с новым именем `g1_markdown_reuse_check`.
Полная повторная векторизация здесь не ожидается. Reuse-check не является новым контролем
для сравнения стоимости подготовки. Метрики можно пересчитать без Qdrant/книг/моделей:

```python
from pathlib import Path
from dnd_rag.evaluation.retrieval_run import recompute_saved_metrics
metrics = recompute_saved_metrics(Path('results/g1_markdown_initial'))
```

Это Python API, отдельной CLI-команды для recompute нет. Полные правила сравнения и поля
карты — в [справочнике](../../configs/experiments/README.md). Demo/API реализованы ниже;
QA-аналитика реализована ниже; серия из10 вариантов описана в study и выполняется последовательно.

## llama.cpp и LLM-профиль

Используется найденный `~/.llama-app/llama`, build11046/60081bb2b, команда `serve`.
Локальный `.env` задаёт LLAMA_SERVER_BIN=/home/lighter_01/.llama-app/llama. Для отдельного
`llama-server` задайте его путь и `server_subcommand: null` в профиле. Бинарник/веса
остаются вне проекта, первая индексация всегда завершается до запуска LLM.

| Поле local.yaml | Default / значения | Назначение |
| --- | --- | --- |
| context_size | 8192, фиксировано | Полное окно, fit/context shift выключены. |
| max_output_tokens | 1536, фиксировано | Максимум генерации, не требуемая длина ответа. |
| safety_margin | 256, фиксировано | Резерв; полный input ≤6400. |
| max_context_chunks | 5, фиксировано | Максимум первых retrieval hits для QA. |
| thinking | false, фиксировано | --reasoning off и enable_thinking=false в count/generate. |
| server_subcommand | null / serve | null: standalone llama-server; serve: установленный unified llama. |
| model_alias | dnd-nemotron | Имя модели в локальном HTTP API. |
| gpu_layers | null / int≥0 | Обязательно при launch; local99 означает максимум доступных слоёв. |
| batch_size | null / int>0 | Logical prompt batch; local512, влияет на throughput/память. |
| ubatch_size | null / int>0, ≤batch | Physical prompt batch; local128, влияет на память. |
| cache_type_k / cache_type_v | null / f16,q8_0,q4_0 | Обязательны при launch; local q8_0/q8_0, тип KV cache. |
| kv_offload | true | GPU KV; false переносит KV в CPU RAM. |
| flash_attention | on / off, on | Attention backend; local on. YAML on заключать в кавычки. |
| threads | int>0, 8 | CPU generation и prompt threads. |
| temperature | float≥0, 0.0 | Greedy sampling при0; профиль явно фиксирован. |
| top_p | (0,1], 1.0 | Nucleus sampling. |
| top_k | int≥0, 40 | Sampling candidates. |
| min_p | [0,1], 0.0 | Sampling cutoff. |
| seed | int≥0, 42 | Seed; не обещание побитовой воспроизводимости на всех устройствах. |
| startup_timeout_seconds | float>0, 120 | Ожидание readiness, не лимит QA. |
| http_timeout_seconds | float>0, 180 | HTTP timeout; ориентир30s не timeout. |

Параметры размещения меняются технической пробой, без автоматического fallback. Окно,
резерв, модель и thinking без решения пользователя не меняются. В локальном профиле
уже проверены gpu_layers=99 и q8_0 KV; эти параметры не задают dtype эмбеддера.
Native count/generation используют одну template конфигурацию. ChatOpenAI1.7.4 посылает
лимит как max_completion_tokens; установленный llama.cpp его соблюдает.

Отдельный запуск сервера (занимает project lock, поэтому не запускайте параллельно demo):

```bash
uv run python scripts/start_llama_server.py --llm-profile configs/llm/local.yaml
```

Это тонкая обёртка над тем же launcher. Ctrl+C останавливает созданный процесс;
`.runtime/llama/server.log` и instance.json сохраняют диагностику/argv/profile/props.
Занятый LLM_BASE_URL даёт llm_conflict, запуск не завершает чужие процессы. Проба:

```bash
uv run --group test python -m pytest tests/rag/integration/test_llama_live.py --run-llama
```

## Контекст и цитаты QA

QA-ядро использует только текущий вопрос и первые пять hits. Полный prompt вместе
с chat template ограничен 6400 LLM-токенами; ответ — максимум 1536, запас — 256.
При переполнении целые чанки с конца удаляются с пересчётом. Ошибка
`context_budget_exceeded` предлагает сократить вопрос и не запускает генерацию.
Пустая успешная retrieval-выдача даёт `no_context`, пустые sources и null для usage/
generation timing. Ошибка зависимости остаётся ошибкой.

В sources попадают только действительно использованные `[n]` из текущего реестра,
с полным исходным текстом, превью до 400 символов и точными координатами. Номера
сохраняются, неизвестные `[n]` дают `unknown_citation`. Код, экранированные скобки
и настоящие Markdown links/images не считаются цитатами. `answer_truncated` означает
finish_reason=length; приложение сохраняет текст без скрытой повторной генерации.

## API и демонстрация

```bash
uv run python -m dnd_rag serve-retrieval --config configs/experiments/g1_splitters/markdown.yaml
# Остановить Ctrl+C перед следующим runtime:
uv run python -m dnd_rag demo --config configs/experiments/g1_splitters/markdown.yaml --llm-profile configs/llm/local.yaml
```

`serve-retrieval`: обязательный `--config PATH`, необязательный `--rebuild` (false).
`demo`: те же аргументы и обязательный `--llm-profile PATH`. Профили фиксируются
при запуске. Путь конфига/профиля разрешается от lab2. Запущен один Uvicorn worker
без reload; CPU query encoder загружается один раз в процессе API.

| Индекс / режим | Порядок |
| --- | --- |
| Новый / retrieval | Полный GPU build → worker exit → CPU query → API. GGUF/llama не нужны. |
| Готовый / retrieval | Проверка и reuse → CPU query → API; GPU document model не загружается. |
| Новый / demo | Полный GPU build → worker exit → CPU query → Nemotron → API → UI. |
| Готовый / demo | Проверка и reuse → CPU query → Nemotron → API → UI; без новой векторизации. |

`--rebuild` принудительно выбирает полный build для обоих режимов. Ошибка сборки
останавливает запуск до LLM/UI. Второй runtime отказывает с runtime_busy; не удаляйте
lock-файл. Ctrl+C останавливает собственные LLM/Streamlit, Qdrant и volume сохраняются.
Живые дети сохраняют защиту и при аварийной смерти родителя. Занятый API/UI/LLM порт
даёт конфликт: чужой сервис не завершается.

Откройте Streamlit на http://127.0.0.1:8501. Он обращается к RAG_API_URL и разрешает
отправку только при qa_ready. Ответ показывается целиком после проверки цитат; одна
текущая пара вопрос/ответ, без истории в prompt. Источники раскрывают полный текст,
body file/строки, разделы, превью с многоточием и печатные страницы с исходной
атрибуцией. Inherited section start не означает точную страницу всего фрагмента.
Смена конфига/модели требует остановить demo и запустить заново.

API по умолчанию http://127.0.0.1:8000, OpenAPI — `/docs`. RAG_API_URL поддерживает
http://127.0.0.1:PORT или http://localhost:PORT без path/query; порт UI фиксирован8501.
LLM_BASE_URL задаёт отдельный порт (обычно8080/v1). Примеры из другого терминала:

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/retrieve -H 'Content-Type: application/json' \
  -d '{"question":"How does the Help action work in combat?","limit":3}'
curl -s http://127.0.0.1:8000/ask -H 'Content-Type: application/json' \
  -d '{"question":"How does the Help action work in combat?"}'
```

`POST /retrieve`: question — непустая строка, limit — необязательный int, default
из YAML (10), 1..retrieval.limit. Возвращает question/index_id/build_id/mode, hits
с rank/score/score_kind/full chunk и timings_ms query_embedding/search/total.
`POST /ask`: только question; возвращает status/answer/sources/warnings, index/build,
context (переданные/удалённые chunk IDs, input_tokens,8192/1536/256), finish_reason
и timings_ms query_embedding/search/context/generation/postprocess/total.
History/config/model/collection и любые лишние поля запрещены.

`GET /health` возвращает index_ready/query_encoder_ready/retrieval_ready/qa_ready,
mode и index/build IDs. HTTP200 означает доступный retrieval,503 — его неготовность.
В serve-retrieval mode=retrieval_only, qa_ready=false, `/ask` даёт503 qa_disabled.
Здоровье проверяется без embeddings и без чтения всех payload.

Ошибки имеют вид `{error:{code,message,details?}}`:422 — поля/пустой вопрос/limit,
слишком длинный embedding input или context_budget_exceeded;503 — недоступная
зависимость;504 — её timeout;429 qa_busy — уже идёт QA;500 — внутренняя ошибка
с диагностикой в `.runtime/errors.log`, без traceback в ответе. `/retrieve` доступен
во время генерации. Citation warnings не меняют200. HTTP timeout профиля180s
отдельный от ориентира30s. Прерванный клиент не продолжает ответ вторым LLM-вызовом.

`.runtime/startup.json` сохраняет mode/PID/index_action/index_id/build_id, исходные
ensure_stages и события index_ready/gpu_worker_exited/cpu_query_loaded/llm_ready/
api_ready/ui_started с накопленным временем. Для reuse GPU worker не запускается,
соответствующие подготовительные стадии имеют status=reused, elapsed_ms=null.
LLM argv/profile/model/template hashes — `.runtime/llama/instance.json`; журналы —
`.runtime/llama/server.log` и `.runtime/ui.log`. Это диагностика, не кэш индексации.

## Сохранённый QA-запуск

```bash
uv run python -m dnd_rag evaluate-qa \
  --config configs/experiments/g1_splitters/markdown.yaml \
  --llm-profile configs/llm/local.yaml --experiment-name qa_markdown
# Необязательный --include-insufficient добавляет3 отдельных вопроса.
```

Обязательны `--config PATH`, `--llm-profile PATH`, `--experiment-name NAME`. Флаг
`--include-insufficient` по умолчанию false:20 основных вопросов; true:20+3.
Запуск занимает общий runtime lock, резервирует новое имя results до тяжёлой
работы, проверяет gold/индекс, выполняет build при необходимости, загружает один
CPU query encoder, затем Nemotron. UI не запускается. На каждый вопрос вызывается
один RagService.ask; контекст для проверки не ищется повторно. Повтор с тем же
именем запрещён, в том числе если рецензент уже изменил CSV.

Общие config.yaml/resolved_config.yaml/gold.yaml/run.json дополняются файлами:

- `llm_profile.yaml`: точный вход; `resolved_llm_profile.yaml`: все эффективные поля.
- `prompts/system.txt` и `prompts/context_builder.py`: snapshots system и сборщика
  динамического блока. Их hashes и фактический server model/template/profile — в run.json.
- `qa_answers.jsonl`: вопрос/категория, raw_answer и AskResult, фактический retrieval,
  context (IDs/budget), полные messages и citation_registry (все переданные raw chunks),
  used/unknown IDs, usage/finish/warnings/timings, native response и structural_diagnostics.
- `qa_review.csv`: наблюдаемые поля и пустые смысловые критерии correctness, completeness,
  citation_support с отдельными *_reason; missing_facts, uncited_claims, reviewer,
  review_method, reviewed_at, review_version. Изначально review_status=not_reviewed.
- `qa_summary.json`: expected/completed/failed/unattempted и timings для primary и
  insufficient раздельно; структурные наблюдения отделены от смысловых оценок.

Рецензент заполняет каждый критерий yes/partial/no/not_applicable с обоснованием
и review_status=reviewed/needs_review. Для агентской помощи review_method=agent_assisted,
для человеческой проверки human. Программа не делает correctness из существования
номера цитаты и не запускает LLM-as-judge. Пропущенная generation остаётся null,
времена warm исключают первый QA всего запуска. При сбое сохраняются предыдущие
ответы, строка ошибки и failed-паспорт/сводка; такой запуск не считается QA20.

Реальный финальный QA20 выполняется после C4 на выбранном профиле (Task14).

## Групповые эксперименты и CSV

```bash
uv run python -m dnd_rag experiment --config configs/experiments/g1_splitters/recursive.yaml \
  --experiment-name g1_recursive --study configs/experiments/study.yaml --group G1
uv run python -m dnd_rag summarize-results --study configs/experiments/study.yaml \
  --output results/retrieval_comparison.csv
```

`--study PATH` и `--group NAME` у experiment задаются вместе; без них остаётся
независимый retrieval-run. Карта не подставляет параметры: YAML всегда полный.
Имена новых runs задаёт `--experiment-name`; поле comparison.run в study ссылается
на сохранённый результат. Сначала закончите G1 и выберите базу, затем обновите
полные G2; после G2 — G3/G5; G4 всегда от G3. В зависимой группе selected_base_run=null
блокирует запуск, как и failed/reference с другими corpus/gold либо лишней дельтой.

`summarize-results`: обязательные `--study PATH` и `--output PATH`, других флагов нет.
Команда работает без runtime lock, .env, Qdrant, GPU и моделей; читает результаты
на диске и атомарно обновляет CSV. Она не выполняет новый retrieval. Missing/failed
и несовпадающие corpus/gold показаны явно, reuse не получает build_time=0. Столбцы,
семантика стадий и все10 профилей — в [справочнике](../../configs/experiments/README.md).
Выбор QA-профиля хранится в study.qa_selection и выполняется до финального QA20.
