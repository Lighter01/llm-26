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
