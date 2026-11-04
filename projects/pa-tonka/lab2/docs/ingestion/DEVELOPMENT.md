# Руководство разработчика

Установка и обычная эксплуатация находятся в [README ingestion](../../src/dnd_rag/ingestion/README.md). [ARCHITECTURE](ARCHITECTURE.md), [PIPELINE](PIPELINE.md) и [DATA_MODEL](DATA_MODEL.md) описывают реализацию и контракты.

## Разделение окружений

`pyproject.toml` задаёт Python ≥3.13, uv_build и группы зависимостей `test`/`lint`. Пользовательские Python-команды запускаются из корня `lab2` через `uv run python ...`, тесты — через `uv run --group test python -m pytest ...`, Ruff — через `uv run --group lint ruff ...`. uv подготавливает окружение автоматически; отдельные pip-команды, активация virtualenv и предварительный `uv sync` не нужны. Node/npm инфраструктура сборщика находится в `tools/ingestion`, root package.json/workspace не создаётся.

На Linux/WSL нужны Git, рабочие Node/npm для установки, затем локальный Node **24.22.2** из lock-файла. Установка проверялась с системными Node 22.22.3 и npm 10.9.8; npm scripts выбирают локальный бинарник. Ajv **8.20.0** — только test devDependency, production resolver его не использует. Node-сборщик внутренне вызывает системный `python3` со stdlib для Linux atomic exchange; Python-зависимости helper не устанавливаются. Нужна файловая система с поддержкой `renameat2(RENAME_EXCHANGE)` для force.

`npm ci --prefix tools/ingestion --no-audit --no-fund` требует доступа к registry и разрешённых install scripts пакета Node. После установки сборка/тесты используют локальные файлы. Upstream npm install, генерация сайта, HTTP server, Chromium и Playwright для текущего snapshot не нужны.

## Смена upstream

Сначала пользователь обновляет submodule и **фиксирует gitlink в основном репозитории**, затем запускает проверки. Checkout SHA и gitlink из HEAD обязаны совпадать. `git add` без commit не считается закреплением. Команды обновления не входят в код ingestion; рабочий checkout пользователя тесты не переключают.

После фиксации новой версии:

```bash
npm --prefix tools/ingestion run recon -- --report /tmp/dnd-recon.json
npm --prefix tools/ingestion run test:smoke
npm --prefix tools/ingestion test
npm --prefix tools/ingestion run resolve
```

Проверьте engine, структуру каталогов/книг, native routes, entry types, required references, raw source records, исключения и warnings. Snapshot-specific числа берутся из inventory; не заменяйте их ожиданиями по памяти. Изменение API следует закрывать минимальным адаптером и регрессией с file/Pointer evidence. Нельзя чинить несовместимость редактированием canonical upstream.

## Локальная разработка и диагностика

Основные тестовые команды:

```bash
npm --prefix tools/ingestion run test:unit
npm --prefix tools/ingestion run test:smoke
npm --prefix tools/ingestion run test:integration
npm --prefix tools/ingestion test -- --report /tmp/dnd-tests.json
```

Runner рекурсивно обнаруживает `tests/ingestion/**/*.test.mjs`. Группы определяются suffix `.integration.test.mjs`, `.smoke.test.mjs`, остальные — unit. Они не пересекаются. Пустая/неизвестная группа является ошибкой. Native runtime запускается отдельно из-за globals; runner использует `--test-isolation=none`, дочерним процессам удаляется `NODE_TEST_CONTEXT`.

Отчёт по умолчанию: `.cache/ingestion/tests/<upstream_sha>/<test_signature>/report.json`. Он содержит code/test/tool fingerprints, Node, snapshot, test events и counts. Это последний запуск данной версии, он атомарно перезаписывается; durations не детерминированы и не входят в книги. Missing summary, nonzero exit, failed/cancelled/skipped/todo или изменение кода/upstream во время прогона дают FAIL. Не редактируйте `.mjs/.json/.py` этих каталогов во время suite.

Полный integration-прогон несколько раз собирает книги и реальные fixture commits; он занимает минуты. Fixtures/выходы создаются в tmp и удаляются через teardown. Snapshot update test использует отдельный локальный shared clone и временный главный репозиторий, не меняя HEAD/index/gitlink пользователя. Матрица покрытия — в [VALIDATION.md](VALIDATION.md).

Для детальной проверки, сохранив данные вне рабочего датасета:

```bash
npm --prefix tools/ingestion run resolve -- --force \
  --output-root /tmp/dnd-resolved-review \
  --diagnostics-root /tmp/dnd-diagnostics
```

В диагностическом root находятся `<sha>/inventory/<signature>`, `assembly/<signature>`, `enrichment/<signature>` и `resolution/<final_signature>`. У каждой стадии свой scope/status. Inventory PASS ещё не доказывает полноту книги; промежуточные assembled/enriched formats имеют `book_complete: false`. Финальные книги остаются в output root.

| Диагностика | Содержимое |
| --- | --- |
| Inventory `report.json`, `books.json`, `files.jsonl` | Конфигурация, роли/хэши входов, дерево книг, счётчики и native loader registry |
| `nodes.jsonl`, `references.jsonl` | Исходные позиции, raw hashes, tables/images, refs, UTF-16 spans и required lookup probes |
| `source-entities.jsonl`, `external-targets.jsonl` | Core source records и metadata прямых внешних целей без recursive corpus |
| `dependencies.jsonl`, `variant-definitions.jsonl`, `issues.jsonl` | Связи, recipes и точные diagnostics |
| Assembly/enrichment outputs | Проверяемые промежуточные книги и report с provenance/digests |
| Resolution `report.json`, `placement-audit.jsonl` | Все validation results, input hashes, issues/omissions и каждое source placement decision |

Для применения reference span к строке в Python учитывайте UTF-16 единицы JS:

```python
text = "🙂 abc"
span = {"start": 3, "end": 6}
fragment = text.encode("utf-16-le")[span["start"] * 2:span["end"] * 2].decode("utf-16-le")
assert fragment == "abc"
```

Standalone `inventory`, `assemble`, `enrich` по умолчанию сохраняют developer входы в `.cache/ingestion/diagnostics/5etools`; `--output-root` меняет место вывода, но не автоматически место поиска ранее подготовленных стадий. Для пользовательского root передавайте явные `--inventory/--assembly` paths. Обычный `resolve` передаёт собственный tmp root и удаляет его.

`recon` проверяет source structure и representative native APIs. `prototype` — совместимый alias developer chapter probe на production assembler: `--book`, zero-based `--chapter`, `--upstream`, `--output-root`, `--help`. Он ограничен spell/monster chapters, по умолчанию XPHB/7, и не объявляет книгу полной. [dev/README](../../src/dnd_rag/ingestion/dev/README.md) содержит команды.

## Добавление типа или правила обогащения

1. Найдите физические source records и native loader/UID grammar. Укажите snapshot, файл и Pointer минимального примера; не используйте name как ID.
2. Обновите classification/required lookup в `runtime/inventory_runtime.mjs` и evidence в `inventory_sources.mjs` там, где это необходимо. Для нового book-level ref нужна поддержка `assembleChapter`, не только entity dereferencer.
3. Для supplemental материала задайте доказанное правило placement/relationship в `enrichment_plan.mjs` или `enrichment_content.mjs`. Обычное упоминание не разрешает расширение всей внешней книги.
4. Проверьте independent `validate_assembly/validate_enrichment`, raw preservation, наличие всех игровых полей, pages, closure, cycles и generated projections. Новое exclusion должно быть узким и подтверждённым, без generic skip.
5. Добавьте meaningful fixture/negative regression и при необходимости native или final corpus regression. Обновите schema/version/content projection только при реальном изменении собственного контракта, сохраняя открытые native поля.
6. Запустите подходящие группы, затем полный suite и сборку в `/tmp`; сверьте content/file hashes и исследуйте их изменение. Обновите текущую документацию.

Изменённые production bytes автоматически дают другой final signature. Модули стадий дополнительно ведут явные карты `codeFiles`; при добавлении используемого helper включите его в соответствующие stage fingerprints. `adapterPath` разрешает относительные module paths внутри `book_assembly`.

## Диагностика ошибок и восстановление

| Наблюдение | Действие |
| --- | --- |
| Upstream не найден/не инициализирован | `git submodule update --init --recursive`, затем проверить HEAD gitlink |
| Checkout differs from gitlink / staged-only | Зафиксировать выбранный gitlink отдельным commit основного проекта либо восстановить закреплённую версию; ingestion не выполняет это автоматически |
| Modified tracked files | Разобрать свои правки upstream и вернуть чистое закреплённое состояние; не обходить preflight |
| Node engine error | Использовать npm scripts или `tools/ingestion/node_modules/.bin/node`; проверить установку и engine нового snapshot |
| Unknown entry/ref/source identity, missing dependency | Открыть issue file/Pointer/UID, проверить native API и добавить адаптер/тест; strict не ослабляется |
| Stale/integrity/mixed-input report | Заново подготовить developer стадии текущим кодом/Node либо запустить обычный resolve с временными входами |
| Corrupt current book/hash | После проверки причин выполнить `resolve --force`; прежний читаемый manifest identity должен совпадать |
| Нечитаемый/чужой manifest, symlink или посторонние файлы | Разобрать и отдельно переместить/восстановить каталог; force не удаляет неизвестные пользовательские данные |
| Build is locked | Дождаться writer; после crash сначала убедиться, что он завершён, и проверить identity staging/target. Чужой активный lock не снимать |
| Linux exchange unavailable | Проверить `python3`/libc/filesystem; не заменять атомарную операцию удалением живого каталога |

Failure report при финализации находится в `.cache/ingestion/diagnostics/5etools/<sha>/failures/<signature>.json` либо в explicit diagnostics root. Ранние preflight/argument errors могут иметь только stderr. `--validate-only` ничего не пишет. Старый PASS не подтверждает неудачный новый запуск. Для проверки текущего build используйте CLI, для чтения исторической книги — standalone validator/пример из DATA_MODEL.

Разработчик управляет сохранённой explicit диагностикой и своими `/tmp` экспериментами. Не добавляйте её обратно в `data/` и не удаляйте валидные исторические final версии ради новой signature. `node_modules`, `.cache` и generated `data/resolved` игнорируются Git; package/lock и документация относятся к исходникам проекта.
