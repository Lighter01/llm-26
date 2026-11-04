# D&D RAG

Python-проект `dnd-rag` (Python ≥3.13, uv). Источник книг — закреплённый Git submodule `external/5etools-src`. Реализован сборщик XPHB/XDMG/XMM в самодостаточные resolved JSON и отдельный [экспортёр Markdown](src/dnd_rag/ingestion/markdown_export/README.md) с CLI. Остальные компоненты RAG пока не создаются.

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

Python-команды запускаются из корня `lab2` через `uv run`: uv подготавливает окружение проекта и устанавливает пакет по `pyproject.toml`. Указывать `PYTHONPATH`, активировать virtualenv или отдельно выполнять `uv sync` перед запуском не требуется. Тестовые зависимости подключаются через `--group test`, инструменты форматирования — через `--group lint`.

Входной каталог указывается явно. Повторная генерация — с `--force`. [Проверка результата](docs/ingestion/MARKDOWN_EXPORT_VALIDATION.md) содержит фактические команды, числа, примеры и ограничения готового Markdown-корпуса.

```text
src/dnd_rag/ingestion/
├── book_assembly/     # рабочий сборщик JSON
├── dev/               # диагностика upstream и одной главы
└── markdown_export/   # API/CLI; common/, rendering/, publication/
tests/ingestion/book_assembly/
├── unit/
├── integration/
├── smoke/
└── helpers/
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
