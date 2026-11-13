# Установка, запуск и команды

Команды выполняются из корня `lab3` через `uv run python -m dnd_rag`. Устройство системы — в [ARCHITECTURE](ARCHITECTURE.md), формулы и файлы измерений — в [EVALUATION](EVALUATION.md).

- [Какой сценарий выбрать](#какой-сценарий-выбрать)
- [Быстрый запуск](#быстрый-запуск)
- [Настройки и адреса](#настройки-и-адреса)
- [Диалог и сквозная проверка](#диалог-и-сквозная-проверка)
- [Измерения и оценивание](#измерения-и-оценивание)
- [Подготовка данных и индекса](#подготовка-данных-и-индекса)
- [Журналы и диагностика](#журналы-и-диагностика)

## Какой сценарий выбрать

| Нужно | Команда | Что запускается |
| --- | --- | --- |
| Поговорить с собственным агентом | `run` | Полный стек и CLI. |
| Проверить tools, историю и traces обоих агентов | `smoke-stack` | Тот же стек и две связанные реплики на адаптер. |
| Измерить выбранного агента | `evaluate-agents` | Стек и фиксированный датасет. |
| Оценить сохранённые ответы | `score-agents` | Офлайн; Langfuse нужен только для upload. |
| Сравнить готовые прогоны | `summarize-agents` | Только сохранённые файлы. |
| Подготовить / проверить / удалить индекс | `build-index` / `inspect-index` / `reset-index` | Qdrant; GPU только для построения. |
| Скомпилировать игровые сущности | `prepare-game-data` | Локальные JSON и Node.js. |

`run`, `smoke-stack` и `evaluate-agents` — отдельные запуски. Каждый сам готовит каталог/индекс и поднимает LLM с MCP; перед следующим остановите предыдущий. Для изучения уже выполненной лабораторной начните с [маршрута по Langfuse](DEMO.md#разбор-сохранённых-результатов-в-langfuse).

## Быстрый запуск

### 1. Подготовить окружение

Нужны Linux/WSL, Python ≥ 3.13, uv, Docker Compose и Node ≥ 22/npm. Версии Python-пакетов закреплены в `uv.lock`.

```bash
uv sync --group test --group lint
npm --prefix tools/ingestion ci
cp -n .env.example .env
```

`cp -n` сохраняет существующие настройки. После нового клонирования подготовьте [корпус](../ingestion/README.md) и закреплённый 5etools. Для нового индекса нужны веса EmbeddingGemma 2 и CUDA GPU; готовая коллекция используется повторно.

### 2. Проверить локальные зависимости

В `.env` задайте пути `LLAMA_SERVER_BIN` и `LLM_MODEL_PATH`, адреса и ключи Langfuse. Инструкция [infra](../../infra/README.md) описывает Compose и инициализацию проекта. Для Codex дополнительно нужен установленный CLI и [закреплённый exporter](../../configs/baseline/README.md). Запустите Docker engine.

Готовый `.env.example` рассчитан на `~/.llama-app/llama` с `server_subcommand: serve`. Для отдельного `llama-server` согласуйте путь и `server_subcommand: null` в [LLM-профиле](../../configs/llm/README.md).

### 3. Запустить чат

```bash
uv run python -m dnd_rag run --llm-profile configs/llm/off.yaml
```

Дождитесь готовности инфраструктуры, каталога, индекса, LLM и MCP. При новой индексации GPU-worker завершается до старта GGUF. `/exit`, EOF или Ctrl+C закрывают чат и его процессы; Docker и данные сохраняются.

## Настройки и адреса

Относительные пути разрешаются от корня проекта, поддерживается `~`. Приоритет RAG-конфигурации: `--config` → переменная процесса `RAG_CONFIG_PATH` → `.env` → `configs/rag/r3.yaml`. Ошибочный путь не заменяется молча другим профилем.

| Настройка | По умолчанию / назначение |
| --- | --- |
| `QDRANT_URL` | `http://127.0.0.1:6343`; отдельное хранилище `data/qdrant/`. |
| `LLM_BASE_URL` | `http://127.0.0.1:8080/v1`; локальный llama.cpp. |
| `LLAMA_SERVER_BIN`, `LLM_MODEL_PATH` | Бинарник и GGUF; пути из `.env.example` согласуйте с машиной. |
| `EMBEDDING_CACHE_DIR` | Пусто: стандартный HF cache. |
| `LANGFUSE_BASE_URL` | `http://127.0.0.1:3000`. |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | SDK-ключи локального проекта, обязательны для агентного стека. |

MCP использует `8765/mcp`, compatibility proxy Codex — `8081/v1`. Секреты и локальные данные исключены из Git. Настройки LLM не требуются для самостоятельного retrieval.

## Диалог и сквозная проверка

### Общие флаги `run` и `smoke-stack`

| Флаг | Обязательность / default | Назначение |
| --- | --- | --- |
| `--config PATH` | Нет; приоритет выше. | RAG YAML, штатные R3/R9. |
| `--llm-profile PATH` | Нет; `configs/llm/off.yaml`. | Альтернатива — `configs/llm/budgeted.yaml`. |
| `--context-limit INT` | Нет; `9500`, минимум `1024`. | Порог сокращения полного входа, отдельный от окна модели. |
| `--rebuild` | Флаг, `false`. | Полная пересборка индекса до запуска модели. |

Порог вместе с резервом ответа и safety должен помещаться в физическое окно профиля. Все основные команды поддерживают `-h` / `--help`.

### Чат: `run`

Использует общие флаги и `--interface cli` — необязательный, единственное значение и default `cli`. Streamlit отложен. Выводятся Markdown, события tools/summary/error и зарегистрированные источники `[n]`.

| Команда чата | Действие |
| --- | --- |
| `/help` | Подсказка по управлению. |
| `/new` | Новый UUID диалога; прежние журналы сохраняются. |
| `/status` | Модель, session, trace и последнее измерение контекста. |
| `/exit` | Завершение с очисткой собственных процессов. |

Индикатор показывает `input / agent limit / %` и отдельно server window. Он обновляется по измерениям. История ввода хранится в `.runtime/cli.history`; нумерация источников переживает summary, новый диалог получает отдельный реестр. Допустимость номера не доказывает смысловую поддержку утверждения.

### Проверка стека: `smoke-stack`

```bash
uv run python -m dnd_rag smoke-stack --agents both --output results/smoke.json
```

К общим флагам добавляются:

| Флаг | Обязательность / default | Назначение |
| --- | --- | --- |
| `--agents own\|codex\|both` | Нет; `both`. | Адаптеры для двух связанных запросов об оценке Mages. |
| `--output PATH` | Нет; только stdout. | Сохранить JSON статусов, usage, tools и traces. |

`--interface` здесь отсутствует. Код 0 означает завершённые проверочные реплики с traces, 1 — неполную проверку. Правильность объяснения оценивается отдельно от exit code.

## Измерения и оценивание

### Новый прогон: `evaluate-agents`

```bash
uv run python -m dnd_rag evaluate-agents \
  --agent own --mode off --run-id own-off
```

`--config`, `--context-limit`, `--rebuild` действуют как [общие флаги](#общие-флаги-run-и-smoke-stack). Остальные параметры:

| Флаг | Обязательность / default | Назначение |
| --- | --- | --- |
| `--agent own\|codex` | Да. | Выбранный адаптер. |
| `--mode off\|budgeted` | Да. | Thinking выключен либо бюджет 512 на блок. |
| `--dataset PATH` | Нет; `data/tasks/lab3.yaml`. | Проверяется до запуска модели. |
| `--run-id ID` | Нет; agent-mode-UTC timestamp. | Новое имя: 1–71 символ, первый — ASCII-буква/цифра, далее ASCII letters/digits/`._-`. |
| `--results-dir PATH` | Нет; `results/lab3`. | Корень результатов. |
| `--llm-profile PATH` | Нет; `configs/llm/<mode>.yaml`. | Thinking должен соответствовать `--mode`. |
| `--timeout SECONDS` | Нет; `300`, положительное число. | Таймаут одной реплики. |
| `--only ID [ID ...]` | Нет; весь набор. | Известные item IDs для явно помеченной диагностической подвыборки. |

Все реплики одного item идут в одной сессии; следующий item получает новую. Существующий каталог не перезаписывается. Код 0 означает полное выполнение и наблюдаемость, 1 — incomplete; смысловые критерии первоначально `pending`. Четыре клетки сравнения используют один common fingerprint.

### Пересчёт: `score-agents`

```bash
uv run python -m dnd_rag score-agents --run results/lab3/own-off --upload-scores
```

| Флаг | Обязательность / default | Назначение |
| --- | --- | --- |
| `--run PATH` | Да. | Сохранённый каталог прогона. |
| `--review PATH` | Нет; `<run>/review.csv`. | Явные оценки смысловых критериев. |
| `--upload-scores` | Флаг, `false`. | Отправить scores в локальный Langfuse. |

LLM не вызывается, исходные записи не меняются. Код 0 означает заполненные критерии, 1 — оставшиеся pending. Неудачная задача остаётся неудачной после оценивания.

### Сравнение: `summarize-agents`

```bash
uv run python -m dnd_rag summarize-agents --runs \
  results/lab3/own-off results/lab3/own-budgeted \
  results/lab3/codex-off results/lab3/codex-budgeted
```

Единственный параметр `--runs PATH [PATH ...]` обязателен. Команда пишет `comparison.csv/json` рядом с каталогами; разные common fingerprints вызывают ошибку. Формулы и порядок заполнения review — в [EVALUATION](EVALUATION.md).

## Подготовка данных и индекса

### Игровой каталог: `prepare-game-data`

```bash
uv run python -m dnd_rag prepare-game-data
```

| Флаг | Обязательность / default | Назначение |
| --- | --- | --- |
| `--source PATH` | Нет; `source_root` из `configs/game.yaml`. | Закреплённый upstream, штатно `external/5etools-src`. |
| `--output PATH` | Нет; `output_root` из того же YAML. | Штатно `data/game/5etools`; SHA-каталог добавляется автоматически. |

Нужны Node и ingestion-зависимости. Сборка детерминирована, Markdown/source_map не меняются. Параметры пяти агентных инструментов — в [MCP-справочнике](../../src/dnd_rag/tools/README.md).

### Коллекция: `build-index`, `inspect-index`, `reset-index`

```bash
uv run python -m dnd_rag build-index --config configs/rag/r3.yaml
uv run python -m dnd_rag inspect-index --config configs/rag/r3.yaml
```

Обе команды принимают необязательный `--config PATH` с общим приоритетом. `build-index` дополнительно принимает `--rebuild` (флаг, default `false`) и подготавливает либо использует совместимую коллекцию. `inspect-index` проверяет паспорт без загрузки моделей; при подтверждённом отсутствии может запустить Qdrant.

Для удаления одной принадлежащей проекту коллекции:

```bash
uv run python -m dnd_rag reset-index --config configs/rag/r3.yaml
```

Обязателен ровно один селектор: `--config PATH` или `--index-id SHA256` — полный lowercase hex из 64 символов. Отсутствующая коллекция — no-op; чужая не удаляется. Корпус и результаты сохраняются.

### Отдельные диагностические серверы

| Запуск | Параметры и поведение |
| --- | --- |
| `uv run python scripts/start_llama_server.py --llm-profile configs/llm/off.yaml` | `--llm-profile PATH` обязателен; `-h/--help`. Только LLM и проектный lock. |
| `uv run python -m dnd_rag.tools.server` | Без параметров. MCP на `127.0.0.1:8765/mcp`, подготовка каталога/индекса и lock до выхода. |

Остановите диагностический сервер перед общим launcher. Профиль и бинарник должны соответствовать друг другу.

## Журналы и диагностика

| Где смотреть | Содержание |
| --- | --- |
| `.runtime/llama/` | Actual argv, model/template hashes и `server.log`. |
| `.runtime/sessions/`, `.runtime/codex-wire/` | Полные turns, исходные/effective запросы Codex. |
| `results/lab3/<run-id>/` | Ответы, review, metrics, manifest и raw; [справочник артефактов](EVALUATION.md#файлы-одного-запуска). |

| Симптом | Действие |
| --- | --- |
| `runtime_busy` | Завершите прежний runtime; живой ребёнок может удерживать lock. Не удаляйте lock-файл для обхода. |
| Занят порт | Остановите владельца сервиса; приложение не завершает чужие процессы. |
| Ошибка Langfuse | Проверьте Docker, адрес и SDK-ключи проекта. |
| `context_budget` | Уменьшите запрос/выдачу либо начните новый диалог; история не усекается скрыто. |
| `run_exists` | Выберите новый run-id, сохранив прежние результаты. |

Ошибки основного CLI идут в stderr. Код 2 обозначает неверные аргументы/конфигурацию, 1 — сбой выполнения; специальные значения score/smoke/evaluate описаны выше. Ctrl+C в чате обрабатывается как штатный выход. Проверки и условия live-проб перечислены в [VALIDATION](../rag/VALIDATION.md).
