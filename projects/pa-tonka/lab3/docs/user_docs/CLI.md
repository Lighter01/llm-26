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

`--llm-profile PATH` обязателен, YAML относительно project root; `-h/--help` — справка. Других параметров нет. `LLAMA_SERVER_BIN` — исполняемый файл (default llama-server), `LLM_MODEL_PATH` — GGUF, `LLM_BASE_URL` — loopback endpoint с `/v1` (default http://127.0.0.1:8080/v1). Запуск держит блокировку проекта и завершается Ctrl+C с cleanup дочерней модели. [Профили и ограничения thinking](../../configs/llm/README.md).

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
