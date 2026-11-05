# D&D RAG

Python-проект `dnd-rag` (Python ≥3.13, uv). Источник книг — закреплённый Git submodule `external/5etools-src`. Реализованы сборщик XPHB/XDMG/XMM в самодостаточные resolved JSON, [экспортёр Markdown](src/dnd_rag/ingestion/markdown_export/README.md) и [валидатор оценочных вопросов](src/dnd_rag/ingestion/question_validation/README.md) с API/CLI. Остальные компоненты RAG пока не создаются.

```bash
npm ci --prefix tools/ingestion --no-audit --no-fund
npm --prefix tools/ingestion run resolve
npm --prefix tools/ingestion test
```

Node.js и тестовые зависимости изолированы в `tools/ingestion`. Python-зависимости для сборки не нужны.

Экспорт готовой сборки не требует Node или checkout сайта:

```bash
uv run python -m dnd_rag.ingestion.markdown_export \
  --input-build data/resolved/5etools/UPSTREAM_SHA/ASSEMBLER_SIGNATURE \
  --output-dir data/markdown/5etools/UPSTREAM_SHA
```

Готовый набор оценочных вопросов проверяется отдельным
[валидатором вопросов](src/dnd_rag/ingestion/question_validation/README.md):

```bash
uv run python -m dnd_rag.ingestion.question_validation \
  --input data/questions/questions_codex.yaml \
  --corpus data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8 \
  --output-dir data/questions/validated
```

Python-команды запускаются из корня `lab2` через `uv run`: uv подготавливает окружение проекта и устанавливает пакет по `pyproject.toml`. Указывать `PYTHONPATH`, активировать virtualenv или отдельно выполнять `uv sync` перед запуском не требуется. Тестовые зависимости подключаются через `--group test`, инструменты форматирования — через `--group lint`.

Для Markdown-экспортёра входной каталог указывается явно, повторная генерация — с `--force`. [Проверка результата](docs/ingestion/MARKDOWN_EXPORT_VALIDATION.md) содержит фактические команды, числа, примеры и ограничения готового Markdown-корпуса.

```text
src/dnd_rag/ingestion/
├── book_assembly/     # рабочий сборщик JSON
├── dev/               # диагностика upstream и одной главы
├── markdown_export/   # API/CLI; common/, rendering/, publication/
└── question_validation/ # строгая проверка вопросов и точных цитат, API/CLI
tests/ingestion/book_assembly/
├── unit/
├── integration/
├── smoke/
└── helpers/
tests/ingestion/question_validation/ # маленькие fixtures, схема/цитаты/API/CLI
tests/ingestion/markdown_export/
├── unit/              # rendering/, publication/, API
├── integration/       # полный корпус, регрессии, CLI, воспроизводимость
├── fixtures/
└── helpers/
tools/ingestion/       # Node/npm и запуск тестов
docs/ingestion/        # итоговая техническая документация и примеры
data/resolved/5etools/ # только версионированные книги и manifest
data/markdown/5etools/ # три полные Markdown-книги и source_map.jsonl
```

[Команды и навигация ingestion](src/dnd_rag/ingestion/README.md) · [Сборщик](src/dnd_rag/ingestion/book_assembly/README.md) · [Тесты](tests/ingestion/README.md) · [Инструменты](tools/ingestion/README.md) · [Техническая документация](docs/ingestion/README.md).
