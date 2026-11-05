# Установка и запуск

Команды запускаются из корня lab2. Нужны Python ≥3.13, uv, Docker Desktop с Linux
engine/WSL integration и CUDA GPU для новой векторизации корпуса. Для обычных
тестов модели, Docker и GPU не нужны.

```bash
uv sync --group test --group lint
cp .env.example .env
uv run --group test python -m pytest
uv run --group lint ruff check src tests
uv run --group lint ruff format --check src tests
```

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
| RAG_API_URL | http://127.0.0.1:8000, будущий адрес API для UI |

YAML эксперимента выбирает corpus/chunking/embedding/index/retrieval/evaluation,
а не адреса сервисов. [Все поля и defaults](../../configs/experiments/README.md).
LLM-профиль отдельно фиксирует окно 8192, максимум ответа 1536, запас 256,
максимум 5 чанков и thinking=false. Размещение GPU/batch/KV ещё не измерено;
поля null не являются готовым профилем запуска Nemotron.

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

Retrieval сейчас доступен через Python `Retriever` и аналитический runner; отдельный
HTTP launcher `serve-retrieval` добавляется в Task 11. Лимит Python retrieval по умолчанию
из YAML (10), допустим 1..configured limit. Полные payload и rank/score_kind сохраняются
без LLM; отсутствие score-порога означает, что далёкий по смыслу вопрос обычно всё равно
получит ближайшие dense-векторы. Это не проверка достаточности ответа.
