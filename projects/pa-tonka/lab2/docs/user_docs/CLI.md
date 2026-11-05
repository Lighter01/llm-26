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
карты — в [справочнике](../../configs/experiments/README.md). QA/demo/HTTP и полная серия
из 10 вариантов будут реализованы после C2; их команды пока не доступны.
