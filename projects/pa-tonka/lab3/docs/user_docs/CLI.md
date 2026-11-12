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
