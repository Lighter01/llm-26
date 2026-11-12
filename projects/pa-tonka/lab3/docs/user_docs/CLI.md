# Установка и команды

Python ≥3.13, uv 0.11.6, Docker Compose. Для ingestion нужен Node ≥22/npm. Установите `uv sync --group test --group lint`, затем `npm --prefix tools/ingestion ci`. При клонировании подготовьте корпус по [ingestion](../ingestion/README.md). Веса EmbeddingGemma 2 должны быть доступны в HF cache; GPU нужен только для построения. Настройки копируются из `.env.example`; секреты в Git не добавляются.

## Выбор retrieval

Приоритет: явный `--config` > переменная процесса `RAG_CONFIG_PATH` > `.env` > `configs/rag/r3.yaml`. Относительные пути всегда от project root. Неверный путь — ошибка. `QDRANT_URL` по умолчанию http://127.0.0.1:6343; `EMBEDDING_CACHE_DIR` — необязательный каталог HF cache. Настройки `LLM_*` не являются условием работы retrieval.

## build-index

Подготавливает или переиспользует совместимую коллекцию. GPU-worker не работает одновременно с LLM; при занятом endpoint нужно завершить его владельцем.

```bash
uv run python -m dnd_rag build-index --config configs/rag/r9.yaml
```

| Параметр | Смысл |
|---|---|
| `--config PATH` | Необязательный YAML, иначе приоритет выше |
| `--rebuild` | Необязательный флаг полной пересборки, default false |
| `-h`, `--help` | Справка |

## inspect-index

Проверяет совместимость выбранной коллекции без загрузки моделей. Может запустить локальный Qdrant, если подтверждено отсутствие сервера.

```bash
uv run python -m dnd_rag inspect-index
```

`--config PATH` необязателен, выбор как выше; `-h/--help` показывает справку. Других параметров нет.

## reset-index

Удаляет только одну принадлежащую приложению коллекцию. Отсутствующая коллекция — no-op; чужая ownership не принимается.

```bash
uv run python -m dnd_rag reset-index --config configs/rag/r3.yaml
```

Ровно один обязательный селектор: `--config PATH` либо `--index-id SHA256` (полные 64 lowercase hex). `-h/--help` — справка. Данные корпуса не удаляются.

## Диагностика

Стадии build идут в stderr, JSON результата — stdout. Локальные worker/llama журналы — `.runtime/`. Прерывание завершает собственные дочерние процессы. Qdrant/data сохраняются. Старые QA/study команды не поддерживаются.

## Административный запуск LLM

После завершения GPU-worker можно проверить сервер отдельно:

```bash
uv run python scripts/start_llama_server.py --llm-profile configs/llm/off.yaml
```

`--llm-profile PATH` обязателен, YAML относительно project root; `-h/--help` — справка. Других параметров нет. `LLAMA_SERVER_BIN` — исполняемый файл (кодовый default llama-server; проверенный .env.example задаёт ~/.llama-app/llama для профилей с server_subcommand=serve), `LLM_MODEL_PATH` — GGUF, `LLM_BASE_URL` — loopback endpoint с `/v1` (default http://127.0.0.1:8080/v1). Запуск держит блокировку проекта и завершается Ctrl+C с cleanup дочерней модели. [Профили и ограничения thinking](../../configs/llm/README.md).

## Setup Langfuse и Codex

Поднимите [Langfuse Compose](../../infra/README.md), создайте локальный проект в http://127.0.0.1:3000 и сохраните SDK keys в `.env`. Можно инициализировать проект через LANGFUSE_INIT_*; все соответствующие credentials должны быть заданы до первого старта. Web/worker4.79.0, Node24.22.2, закреплённый официальный exporter и способ установки описаны в [baseline](../../configs/baseline/README.md). Используйте pnpm frozen lock; npm install без lock обнаружил peer conflict.

MCP diagnostic: `uv run python -m dnd_rag.tools.server`, параметров нет; bind127.0.0.1:8765/mcp, Ctrl+C завершает сервер. Этот отдельный процесс держит lock проекта: не запускайте одновременно вторую управляющую команду.

## prepare-game-data

Компилирует отдельный каталог игровых сущностей из закреплённого upstream, не меняя Markdown/source_map. Генерируемый каталог загружается tools один раз; сам tool ничего не компилирует.

```bash
uv run python -m dnd_rag prepare-game-data --output data/game/5etools
```

| Параметр | Смысл и default |
|---|---|
| `--source PATH` | Необязательный local 5etools root; иначе source_root из configs/game.yaml, исходно external/5etools-src |
| `--output PATH` | Необязательный output root; иначе output_root из configs/game.yaml, исходно data/game/5etools; SHA-каталог добавляется автоматически |
| `-h`, `--help` | Справка |

Пути относительно корня проекта. Требуется Node22+ (проверен24.22.2 из ingestion), pinned submodule и установленные ingestion dependencies. Повторная подготовка детерминирована; несовместимый manifest/неразрешённая ссылка — ошибка. Игровые данные игнорируются Git; воспроизводимая команда остаётся в репозитории.

## Параметры MCP tools

Это инструменты агента, не отдельные CLI-команды. Все обязательные поля перечислены ниже; неизвестное/неоднозначное имя требует уточнения.

| Tool | Обязательные поля | Необязательные поля/default |
|---|---|---|
| search_rules | query (непустая строка) | limit=5,1..10 |
| lookup_monsters | Нет: query/filters задают поисковый запрос | query=None, habitat=None, creature_type=None, limit=5,1..10 |
| evaluate_encounter | party_size>0, party_level1..20, monsters (непустой список monster_id/count>0) | Нет |
| build_encounter | party_size>0, party_level1..20, difficulty=low/moderate/high | habitat=None, creature_type=None, total_count=None (>0 если задан), required_monsters=[] (monster_id/count) |
| generate_loot | kind=individual/hoard, cr (стандартное число или дробь0..30) | count=1; hoard требует party_level1..20 и treasure_theme=Arcana/Armaments/Implements/Relics, count=1 |

Encounter build: ≤256 форм, ≤3 различных stat blocks, auto count1..min(12,2×party_size); явный total_count точный. Conflict/search_exhausted не выдаются за успешный подбор. Hoard CR относится к владельцу, individual count — к одинаковым существам. Полные фактические rolls и sources входят в result.

## run

Запускает полный локальный stack и оформленный чат. Сначала инфраструктура и каталог, затем reuse/build индекса; GPU-worker заканчивается до старта модели. Порты MCP8765/proxy8081 должны быть свободны. На неопределённый health check launcher отвечает ошибкой, не захватывает чужой процесс. После EOF/Ctrl+C/`/exit` модель и локальные серверы останавливаются, Docker и данные остаются.

```bash
uv run python -m dnd_rag run --interface cli --llm-profile configs/llm/off.yaml
```

| Флаг | Значение, обязательность и default |
|---|---|
| `--interface cli` | Необязательный, default cli; Streamlit пока не реализован |
| `--llm-profile PATH` | Необязательный YAML относительно project root; default configs/llm/off.yaml, другой штатный configs/llm/budgeted.yaml |
| `--config PATH` | Необязательный RAG YAML, иначе обычный приоритет RAG_CONFIG_PATH/.env/R3 |
| `--context-limit INT` | Необязательный native full-input порог, default9500, минимум1024; порог+output reserve+safety должны помещаться в server window |
| `--rebuild` | Необязательный, default false; принудительно пересобрать индекс до модели |
| `-h/--help` | Справка |

`/help` объясняет команды, `/new` создаёт UUID нового диалога и сохраняет предыдущие журналы, `/status` показывает model/session/trace URL и последнее измеренное число, `/exit` выходит. История ввода — `.runtime/cli.history`. Индикатор показывает input/agent limit/%; server16384 указан отдельно. Между измерениями счётчик не анимируется вымышленными токенами. Tool error и summary before→after выводятся отдельными событиями.

## smoke-stack

Стартует тот же stack, выполняет два настоящих turn с историей и оценкой двух Mages каждым выбранным агентом, сохраняет полный JSON со статусом/usage/trace/tools. Требует настроенных Langfuse и, для Codex, pinned exporter. Default проверяет обоих.

```bash
uv run python -m dnd_rag smoke-stack --agents both --output results/smoke.json
```

Поддерживает те же `--config`, `--llm-profile`, `--context-limit`, `--rebuild`, `-h/--help`, что run. Дополнительно `--agents own|codex|both` (необязательный, default both), `--output PATH` (необязательный JSON-файл; иначе только stdout). Флага `--interface` нет. Exit0 означает completed turns с traces, иначе1; JSON сохраняет причины ошибок. Смысловое качество ответа оценивается по содержимому, а не по exit code.

## evaluate-agents

Выполняет фиксированный набор последовательно через выбранный адаптер и общий launcher. Каждый запуск получает отдельный run-id; существующие результаты не перезаписываются. Pending rubric означает незавершённое оценивание даже при успешном выполнении модели.

```bash
uv run python -m dnd_rag evaluate-agents --dataset data/tasks/lab3.yaml --agent own --mode off --run-id own-off
```

| Флаг | Назначение, допустимость и default |
|---|---|
| `--agent own|codex` | Обязательный адаптер |
| `--mode off|budgeted` | Обязательный режим; budgeted использует512 reasoning tokens на блок |
| `--dataset PATH` | Необязательный YAML; default data/tasks/lab3.yaml, проверяется до старта модели |
| `--run-id ID` | Необязательный уникальный1..71 символ из letters/digits/._-; default agent-mode-UTC timestamp |
| `--results-dir PATH` | Необязательный корень; default results/lab3 |
| `--config PATH` | Необязательный RAG YAML, обычный приоритет env/.env/R3 |
| `--llm-profile PATH` | Необязательный; default configs/llm/<mode>.yaml; thinking обязан совпадать с mode |
| `--context-limit INT` | Необязательный общий input threshold; default9500, минимум1024 |
| `--timeout SECONDS` | Необязательный положительный per-turn timeout, default300 |
| `--only ID [ID ...]` | Необязательный явный smoke subset; только существующие IDs, selection сохраняется в manifest |
| `--rebuild` | Необязательный, default false; перестроить индекс перед моделью |
| `-h/--help` | Справка |

Все пути относительно project root. Exit0 означает complete execution/observability,1 — incomplete execution; semantic review первоначально pending. Режимы own/off, own/budgeted, codex/off, codex/budgeted запускаются отдельно с одним frozen dataset/model/tool fingerprint.

## score-agents

Офлайн пересчитывает формальные и явно заполненные смысловые критерии. Не вызывает LLM и не изменяет исходные turn records.

```bash
uv run python -m dnd_rag score-agents --run results/lab3/own-off --review results/lab3/own-off/review.csv --upload-scores
```

`--run PATH` обязателен; `--review PATH` необязателен, default <run>/review.csv; `--upload-scores` необязательный флаг, default false, отправляет scores в локальный Langfuse; `-h/--help` — справка. Без upload сервисы не нужны. Exit0 означает все rubric заполнены,1 — есть pending; failed tasks остаются failed независимо от заполненности.

## summarize-agents

Сводит сохранённые совместимые прогоны в comparison.csv/json рядом с run directories. Различающиеся common fingerprints — ошибка.

```bash
uv run python -m dnd_rag summarize-agents --runs results/lab3/own-off results/lab3/own-budgeted results/lab3/codex-off results/lab3/codex-budgeted
```

`--runs PATH [PATH ...]` обязателен; `-h/--help` — справка. Других флагов нет. Сравнение не меняет pending на success. Формулы и формат review описаны в [оценивании](EVALUATION.md).

Чат выводит `[n]` source block для фактических retrieval sources текущего диалога. Полные тексты/spans и честная section/page attribution сохраняются в AgentReply и registry; неизвестный номер даёт warning. Нумерация сохраняется при summary, `/new` открывает независимый scope. Registry копируется в `citations/<session>.json` измерительного run. Citation validity измеряет разрешимость номера, не semantic support.
