# Ingestion: сборка книг D&D

Сборщик создаёт самодостаточные resolved JSON трёх книг из закреплённого локального Git submodule `external/5etools-src`:

- **XPHB** — Player's Handbook (2024);
- **XDMG** — Dungeon Master's Guide (2024);
- **XMM** — Monster Manual (2025).

Сохраняются все доступные части книг, правила, характеристики, дочерние компоненты, таблицы, raw tags и image metadata. Результат относится к материалам выбранного snapshot. Отдельный [Markdown-рендерер](markdown_export/README.md) читает готовые JSON через Python API или CLI `uv run python -m dnd_rag.ingestion.markdown_export --input-build PATH --output-dir PATH`. OCR, чанкинг, embeddings и RAG не выполняются.

## Установка и первый запуск

Все команды выполняются из `lab2` в Linux/WSL. Нужны Git, Node/npm для установки инструментов и `python3` со стандартной библиотекой, который Node-сборщик внутренне вызывает для атомарного force на Linux. Для самой Node-сборки Python virtualenv не требуется. Пользовательские Python-команды — чтение готового JSON, Markdown-экспорт и Python-тесты — запускаются через `uv run`; uv подготавливает окружение проекта автоматически.

После нового клонирования проекта инициализируйте уже зарегистрированный submodule:

```bash
git submodule update --init --recursive
npm ci --prefix tools/ingestion --no-audit --no-fund
npm --prefix tools/ingestion run resolve -- --upstream external/5etools-src
```

Node **24.22.2** и test dependency Ajv **8.20.0** устанавливаются только в `tools/ingestion`; npm scripts выбирают локальный Node. Для установки нужен npm registry и разрешённые install scripts пакета Node. После установки сборка работает локально без сети. Зависимости сайта, HTTP-сервер, браузер и upstream build/generation commands не требуются.

Успех заканчивается `Resolved PASS (created/reused/replaced); manifest: ...`. Сохраняйте путь к этому manifest: он определяет конкретную версию книг.

```text
data/resolved/5etools/<upstream_sha>/<assembler_signature>/
├── xphb.resolved.json
├── xdmg.resolved.json
├── xmm.resolved.json
└── manifest.json
```

Первый длинный хэш — commit upstream; второй — digest кода, схемы, Node и настроек сборки. Изменение версии не требует ручного удаления старых результатов. Существующие валидные исторические версии сохраняются.

## Повторный запуск, проверка и force

```bash
npm --prefix tools/ingestion run resolve
npm --prefix tools/ingestion run resolve -- --validate-only
npm --prefix tools/ingestion run resolve -- --force
```

Обычный повтор проверяет готовый build и переиспользует его без изменения файлов/mtime. `--validate-only` проверяет **текущий вычисленный build-id**, ничего не пишет и не готовит отсутствующие входы. Обе команды обходятся без сохранённых inventory/assembled/enriched-файлов, но CLI проверяет pinned upstream.

`--force` заново проверяет входы, формирует книги и атомарно заменяет только этот build-id после проверки staging. Разные versions не повреждаются. Повреждённый известный book/hash можно восстановить при читаемом manifest; чужая identity, нечитаемый manifest, symlinks и посторонние файлы требуют отдельного разбора, а не автоматического удаления.

## Параметры основной CLI

Параметры npm передаются после `--`:

| Параметр | Назначение / значение по умолчанию |
| --- | --- |
| `--books XPHB,XDMG,XMM` | Выбор уникальных core IDs, по умолчанию все три; допустимо подмножество |
| `--upstream PATH` | Путь к зарегистрированному submodule, по умолчанию `external/5etools-src` относительно проекта |
| `--output-root PATH` | Root финальных версий, по умолчанию `data/resolved/5etools` |
| `--strict` | Явно фиксирует strict policy, уже включённую по умолчанию; критичные ошибки всегда блокируют успех |
| `--force` | Пересборка/замена только текущего build-id |
| `--validate-only` | Read-only проверка текущего build; несовместим с force |
| `--diagnostics-root PATH` | Явно оставить промежуточные входы и подробные отчёты вне финального датасета |
| `--inventory PATH` | Developer input: проверенный каталог inventory или его report.json |
| `--assembly PATH` | Developer input: проверенный каталог assembly или его report.json |
| `--enrichment PATH` | Developer input: проверенный каталог enrichment или его report.json |
| `--help` | Параметры и назначение CLI |

Явные относительные пути считаются от каталога вызова, включая npm через `INIT_CWD`. `--books xmm` нормализуется в XMM и создаёт отдельный build-id с одной книгой и manifest. Книги не используют payloads соседних JSON.

```bash
npm --prefix tools/ingestion run resolve -- --books XMM --output-root /tmp/dnd-single-book
npm --prefix tools/ingestion run resolve -- --help
```

## Временные данные и диагностика

Обычный resolve создаёт inventory/assembly/enrichment в системном tmp и удаляет рабочий каталог при успехе и ошибке. В `data/` постоянно остаются только final versions. Для подробного отчёта нужен явный диагностический запуск; на cache hit новые отчёты не создаются, поэтому используйте force:

```bash
npm --prefix tools/ingestion run resolve -- --force \
  --diagnostics-root .cache/ingestion/diagnostics/5etools
```

Root диагностики должен находиться вне upstream и root финального вывода. В `<diagnostics-root>/<sha>/resolution/<final_signature>/` сохраняются `report.json` и `placement-audit.jsonl`; соседние каталоги inventory/assembly/ enrichment содержат проверяемые промежуточные входы. JSON Schema остаётся только в исходниках. Явно сохранённой диагностикой управляет разработчик.

При ошибке CLI возвращает ненулевой код и stderr; после входа в orchestration также указывает failure report в `.cache/ingestion/diagnostics/5etools/<sha>/failures/` либо explicit diagnostics root. Ранние preflight/argument errors могут не иметь JSON report. Прежний PASS не делает новый неуспешный запуск успешным. [Руководство разработчика](../../../docs/ingestion/DEVELOPMENT.md) объясняет реестры, stage scope и восстановление после сбоев.

## Обновление submodule

Сборщик требует чистый checkout, совпадающий с gitlink из **HEAD основного репозитория**. Изменённые tracked-файлы и staged-only gitlink блокируют запуск независимо от strict. Ingestion сам не обновляет и не переключает submodule.

Обновление выполняет пользователь отдельно:

```bash
git submodule update --remote external/5etools-src
git -C external/5etools-src log -1 --oneline

git add external/5etools-src
git commit -m "chore: update 5etools submodule"

npm --prefix tools/ingestion run recon -- --report /tmp/dnd-recon.json
npm --prefix tools/ingestion test
npm --prefix tools/ingestion run resolve
```

`update --remote` меняет checkout, но не gitlink уже существующего коммита. Один `git add` недостаточен: нужен commit основного проекта. Для инициализации или восстановления закреплённой версии используется `git submodule update --init --recursive`. Не запускайте генерацию, изменяющую tracked-файлы canonical upstream, как способ починить обычную сборку.

## Чтение и проверки

В manifest **2.0.0** указаны file/content hashes, схема книги **1.0.0** и краткая валидация. Каждый JSON читается без upstream/Node/других книг. Например:

```bash
uv run python docs/ingestion/examples/read_book.py /path/to/build --book XPHB --chapter 3
```

Исполняемый пример показывает книгу, главу, вставку, разные origins и subclasses. [Модель данных](../../../docs/ingestion/DATA_MODEL.md) содержит контракт, JSON Pointers, pages, recipes/shared content, оба хэша и standalone Node-проверку.

```bash
npm --prefix tools/ingestion test
npm --prefix tools/ingestion run test:unit
npm --prefix tools/ingestion run test:smoke
npm --prefix tools/ingestion run test:integration
```

Проверенный snapshot, counts, regression checklist, ручные выборки и ограничения описаны в [VALIDATION](../../../docs/ingestion/VALIDATION.md). PASS не означает полную сверку печатных страниц или OCR. Неизвестные страницы остаются null; обычные внешние text tags не расширяют корпус автоматически.

## Экспорт готовых книг в Markdown

[Markdown export](markdown_export/README.md) читает конкретный каталог с `manifest.json` и тремя resolved-книгами. Python ≥3.13 со stdlib достаточно; Node, исходники 5e.tools и запуск сборщика для экспорта не требуются.

```bash
uv run python -m dnd_rag.ingestion.markdown_export \
  --input-build data/resolved/5etools/UPSTREAM_SHA/ASSEMBLER_SIGNATURE \
  --output-dir data/markdown/5etools/UPSTREAM_SHA
```

Результат — `xphb.md`, `xdmg.md`, `xmm.md`, `source_map.jsonl`. Повторная генерация требует `--force`. Координаты карты относятся к **Markdown-body без YAML**, а не к полному файлу. Полный CLI/API и пример чтения диапазона — в README модуля; числа и примеры готовых книг — в [проверке результата](../../../docs/ingestion/MARKDOWN_EXPORT_VALIDATION.md).

## Навигация

- [book_assembly](book_assembly/README.md) — production pipeline; CLI в `resolution/`.
- [dev](dev/README.md) — recon, chapter probe и самостоятельные developer стадии.
- [markdown_export](markdown_export/README.md) — самостоятельный Python-рендерер книг и карты разделов, CLI и публикация с `--force`.
- [Техническая документация](../../../docs/ingestion/README.md) — архитектура, модель данных, алгоритм, разработка и проверенный результат.
- [Тесты](../../../tests/ingestion/README.md) и [инструменты](../../../tools/ingestion/README.md).
