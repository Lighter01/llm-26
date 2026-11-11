# Сборка книг

Production-пайплайн для XPHB, XDMG и XMM. Все компоненты работают с закреплённым локальным submodule; полный результат каждой книги читается из одного JSON.

| Каталог | Ответственность и точки входа |
| --- | --- |
| [common](common/README.md) | Строгий JSON, IDs/origins, обход дерева, пути и запись артефактов |
| [runtime](runtime/README.md) | Git preflight, локальный native runtime и UID/lookup API |
| [inventory](inventory/README.md) | `inventory.mjs`: инвентарь узлов, сущностей и зависимостей |
| [assembly](assembly/README.md) | `assemble_books.mjs`: главы и обязательные вставки |
| [enrichment](enrichment/README.md) | `enrich_books.mjs`: связанные компоненты и placement graph |
| [resolution](resolution/README.md) | `resolve_books.mjs`: orchestration, manifest, хэши и атомарная публикация |
| [validation](validation/README.md) | Проверка исходной структуры и полноты доменного содержимого |

Основная команда из `lab2`:

```bash
npm --prefix tools/ingestion run resolve
```

Допустимы:

- `--books XPHB,XDMG,XMM`
- `--upstream PATH`
- `--output-root PATH`
- `--strict`
- `--force`
- `--validate-only`
- `--inventory PATH`
- `--assembly PATH`
- `--enrichment PATH`
- `--diagnostics-root PATH`
- `--help`

Относительные пути считаются от каталога вызова, включая npm-запуск.

```text
data/resolved/5etools/<upstream_sha>/<assembler_signature>/
├── xphb.resolved.json
├── xdmg.resolved.json
├── xmm.resolved.json
└── manifest.json
```

При явном `--books` сохраняется выбранное подмножество книг и manifest.

Схема **книги 1.0.0** не менялась при реорганизации. `book`, `chapters` и `domain` сохраняют исходное содержимое. Manifest **2.0.0** описывает эти четыре файла: код/конфигурацию, snapshot, schema digest, file/content hashes и краткую валидацию. JSON Schema хранится только в [resolution/resolved-book.schema.json](resolution/resolved-book.schema.json).

`file_sha256` включает служебные метаданные, `content_sha256` — содержательную проекцию `dnd-book-content-v1`. Подпись сборки считается по production-коду, Node, схеме и настройкам до создания временных входов. Идентичный повтор проверяет и переиспользует результат; `--force` пересобирает этот build-id, проверяет staging и атомарно меняет каталоги. Соседние версии сохраняются. `--validate-only` ничего не пишет и не требует inventory/enriched-файлов.

При обычной сборке рабочий каталог в системном tmp удаляется в `finally`, в том числе при ошибке. `--diagnostics-root` явно сохраняет подробные отчёты и входы вне финального датасета; этот путь и временные имена не входят в подпись. Ошибка не публикует частичную книгу. [Регрессии](../../../../tests/ingestion/README.md) проверяют эти свойства и все требования полноты.

[Техническая документация](../../../../docs/ingestion/README.md) описывает архитектуру, модель данных, алгоритмы, разработку и проверенный результат.
