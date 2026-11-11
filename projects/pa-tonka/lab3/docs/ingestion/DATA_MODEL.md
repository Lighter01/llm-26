# Модель данных и контракт результата

Книга имеет схему **1.0.0**, manifest — **2.0.0**; версия resolver сейчас **0.6.2**. Эти номера описывают разные контракты. Каноническая [JSON Schema](../../src/dnd_rag/ingestion/book_assembly/resolution/resolved-book.schema.json) использует Draft 2020-12 и хранится в исходниках. В финальные каталоги схема и подробные отчёты не копируются.

## Каталог и самодостаточность

```text
data/resolved/5etools/<upstream_sha>/<assembler_signature>/
├── xphb.resolved.json
├── xdmg.resolved.json
├── xmm.resolved.json
└── manifest.json
```

При явном `--books` публикуется выбранное подмножество и manifest. Для чтения конкретной книги достаточно её JSON: внешний registry, другие книги и upstream не требуются. Manifest удобен для выбора файла и проверки целостности. CLI выбирает текущий build-id по snapshot/коду/настройкам, а не по времени файла или лексикографическому порядку каталогов. Сохраняйте путь из вывода `resolve`.

## Корень книги

| Поле | Содержание |
| --- | --- |
| `artifact_kind`, `stage`, `schema_version` | `resolved_book`, `6`, `1.0.0`; `stage` обозначает формат финализации, а не номер последней выполненной задачи |
| `generator` | Имя/версия resolver, Node, schema version, config, code/config digests и signature |
| `upstream` | Repository, checkout/gitlink SHA, подтверждение их совпадения, tracked cleanliness и package version |
| `provenance` | Signatures и report digests inventory/assembly/enrichment; также digest входного enriched JSON |
| `scope` | `all_source_chapters`, `embedded_references_resolved`, `domain_enrichment`, `book_complete` — все `true` после проверок |
| `book` | ID, title, дата публикации из каталога, полный `catalog_entry`, `catalog_origin`, `source_file`, `source_metadata` |
| `chapters` | Все исходные части, включая приложения и credits, в исходном порядке |
| `domain` | Уникальные canonical entities данной книги, их placements и relationships |

Собственная оболочка строго задана. Native payloads, catalog и source recipes остаются открытыми JSON-объектами, чтобы новые игровые поля не отбрасывались. Схема не заменяет source audit и семантические проверки графа.

## Главы и вставки

`chapters[*]` содержит `chapter_index` с нуля, `title`, `original_id`, `origin` и `content`. `content` — полное исходное дерево с прежними массивами, полями, порядком, таблицами, изображениями и строковыми tags. Обязательные statblocks заменены wrappers `kind: embedded_entity`:

| Поле wrapper | Назначение |
| --- | --- |
| `occurrence_id` | Конкретное появление в исходной книге |
| `entity_id` | Идентичность сущности независимо от числа появлений |
| `original_reference` | Полный исходный statblock reference |
| `lookup` | Native `prop`, `source`, `hash`, `lookup_page`, UID при наличии и entity ID |
| `placement` | Книга размещения, глава и её source origin |
| `entity_origin` | Источник самой карточки, её страница и физический locator/lookup evidence |
| `data` | Полный обработанный native payload, включая поля вне `entries` |
| `derivation` | `null` либо доказанное native происхождение виртуального предмета |

Замена wrappers на `original_reference` точно восстанавливает исходную главу. При поиске книжных появлений обход останавливается на wrapper: его `data` относится к карточке, а не к исходным позициям главы. Внутри native payload возможны полностью раскрытые `statblockInline`; это уже часть карточки.

`type: table/tableGroup`, list/nested entries и `type: image` остаются в исходной форме. У изображений сохраняются href/path, caption/title, credit, map/grid metadata и другие поля. Наличие ссылки не означает наличие пикселей в clone или извлечение текста из рисунка. Raw `{@...}` tags не конвертируются. Отсутствие самого файла картинки не является ошибкой сборки текстового корпуса.

## Canonical entities и отношения

`domain.entities` содержит один canonical node на identity внутри книги. Узлы двух представлений:

- `book_insertion`: `occurrence_id` адресует полный wrapper в `chapters` **этой же книги**; дублировать payload в domain не требуется;
- `domain_component`: полный payload находится в `data`, дополнительно есть `loading_method` и `derivation`. Обычно это subclass/feature, summon, fluff, legendary group, item member или связанные rules metadata.

В обоих случаях есть `prop`, `data_origin`, `source_records` и `canonical_placement`. Последний содержит реальный source `anchor`, `relation` и `parent_entity_id` либо `null`. Anchor указывает книгу, главу, occurrence и origin настоящего книжного узла; это может быть вставка, именованный раздел, строка таблицы или абзац. Это не выдуманная глава.

Canonical parents образуют лес без циклов. Первое canonical placement не удаляет повторные исходные появления. `domain.relationships` хранит `from_entity_id`, `to_entity_id`, relation, evidence и anchor. Обычные endpoints материализованы в этой книге. `inheritance_provenance` — специальная связь происхождения: внешний родитель наследования не обязан получать отдельный книжный placement. Metadata nodes без native hash могут иметь `record:` ID.

`source_records[*]` сохраняет record ID, prop, origin и **полный `raw`** с `representation: source_recipe`. Здесь `_copy/_mod` и исходные UID допустимы: это рецепт для трассировки, тогда как экспортируемый результат находится в `data`. В native payload также сохраняются отложенные `_versions`, `entriesTemplate`, `_mod`; их refs отделены от активных обязательных вставок. Не выводите `raw` как ещё одну копию игрового текста.

У индивидуального fluff `shared_content` перечисляет точные пары `path → parent_entity_id/parent_path` для совпадающих entry/image blocks. Полный native результат остаётся в `data`. Markdown-экспортёр выводит общий блок один раз, сохраняя индивидуальный текст и дополнительные связи.

## Идентификаторы и JSON Pointers

Форматы создаёт `common/book_schema.mjs`:

```text
occurrence:<BOOK_ID>:chapter:<index>:<encoded-source-json-pointer>
entity:<encoded-lowercase-prop>:<encoded-lowercase-source>:<encoded-native-hash>
record:<encoded-source-file>:<encoded-source-json-pointer>
```

Токены Pointer экранируются как `~0` и `~1`, а ID дополнительно использует URI encoding. Native hash сам может содержать percent escapes. Потребителю удобнее считать ID непрозрачной строкой и пользоваться registry/полями payload. Не выделяйте UID простым `split('|')` и не объединяйте записи только по имени. Для features идентичность учитывает class/subclass/source/level, для deity — дополнительный контекст. Item aliases `baseitem/itemGroup/magicvariant` используют native lookup namespace `item`, сохраняя свой `prop` в canonical node.

Origin pointers адресуют физический **исходный JSON**; `shared_content` paths относятся к processed payload. Они не взаимозаменяемы. Source file paths относительны upstream; абсолютные пути окружения в книгу не записываются.

## Страницы и происхождение

Origin хранит `file`, `json_pointer`, `source`, `upstream_commit`, `printed_page`, `page_attribution`, `page_origin_pointer`; дополнительные evidence-поля уточняют физическую запись, template или loader lookup.

| Атрибуция | Значение |
| --- | --- |
| `explicit` | Страница указана у исходного узла или получена как собственная page native entity с соответствующим evidence |
| `inherited_section_start` | Известно начало ближайшего исходного раздела/предка; это не точная страница каждого вложенного фрагмента |
| `unknown` | Точной страницы нет; `printed_page: null` |

`placement.origin.source/page` относится к книге появления. `entity_origin` или `data_origin` относится к самой карточке. Например, PHB включает Ape с `source: XMM`; источники и страницы сохраняются раздельно. `lookup_page`, например `bestiary.html`, является ресурсом загрузчика, а не номером страницы печатной книги.

Для виртуального item `file/json_pointer` могут быть `null` и `lookup_source: generated_item`. `derivation` содержит проверенные base item и magicvariant template с target IDs и физическими origins. При нескольких кандидатах сохраняется `ambiguous_physical_candidates`; путь не угадывается. Неизвестная страница компонента не заполняется страницей его книжного anchor.

## Manifest и два хэша

Manifest 2.0.0 содержит:

- `build_id`, `upstream` и `assembler` с кодом/настройками/Node identity;
- `books[ID]`: относительный `path`, размер `bytes`, `file_sha256`, `content_sha256`;
- `schema`: версия книги и SHA-256 канонического файла схемы;
- `validation`: status, `PASS_FOR_PINNED_SNAPSHOT`, checks, статистика книг, агрегаты placement audit и краткие warnings.

В нём нет обязательных внешних `report_path`/artifact files. Подробный report и JSONL audit доступны через диагностический запуск. У исторической сборки, адаптированной при реорганизации, возможно поле `storage_migration`: изменён manifest, прежние байты книг сохранены. Manifest не хэширует сам себя.

`file_sha256` — SHA-256 всех UTF-8 байтов книги. `content_sha256` использует каноническую проекцию **`dnd-book-content-v1`** из [resolved_content.mjs](../../src/dnd_rag/ingestion/book_assembly/resolution/resolved_content.mjs): ключи объектов сортируются, порядок массивов сохраняется.

Учитываются `book/chapters/domain`, весь игровой `data/raw`, текст/tags, таблицы, картинки/credit, source, фактические страницы/атрибуции, IDs, placements и связи. Исключаются корневые generator/upstream/provenance, технические поля собственных origins, loader diagnostics, физические locators, reference spans и вспомогательные anchor labels. Это исключения **по роли** поля: игровые `hash`, `version`, `generator`, `origin` и underscore-поля не удаляются по имени.

Смена только snapshot SHA при неизменном содержимом может сохранить content hash, изменив file hash и каталог. Если физический перенос меняет canonical ID или occurrence position, content hash также может измениться: IDs и позиции являются частью проекции. Для пересчёта используйте указанный модуль, а не хэш всего JSON или собственное удаление ключей. Практический пример — ниже.

## Чтение и Markdown-экспорт

Проверяемый [пример на Python](examples/read_book.py) читает manifest и одну книгу, проверяет размер/file hash, выбирает главу и вставку, затем получает subclasses Barbarian через отношения. Нужна только стандартная библиотека:

```bash
uv run python docs/ingestion/examples/read_book.py /path/to/build --book XPHB --chapter 3
```

Для простого чтения manifest необязателен:

```python
import json
from pathlib import Path

book = json.loads(Path("/path/to/build/xphb.resolved.json").read_text(encoding="utf-8"))
chapter = book["chapters"][3]  # Индекс Character Classes в проверенном snapshot.
```

Проверка готовой книги и content hash без импорта native runtime:

```bash
tools/ingestion/node_modules/.bin/node --input-type=module - /path/to/build/xphb.resolved.json <<'JS'
import {readFile} from "node:fs/promises";
import {validateResolvedBook} from "./src/dnd_rag/ingestion/book_assembly/resolution/resolved_schema.mjs";
import {contentSha256} from "./src/dnd_rag/ingestion/book_assembly/resolution/resolved_content.mjs";
const book = JSON.parse(await readFile(process.argv[2], "utf8"));
console.log(validateResolvedBook(book));
console.log(contentSha256(book));
JS
```

Markdown-экспортёр идёт по `chapters` в исходном порядке, использует wrappers на их местах и добавляет domain components по anchors и parent relations. Печать всех `domain.entities` подряд создаст дубли, поскольку features могут уже находиться в native родителе. Общий fluff можно подавлять только по `shared_content`. Игровые поля вне `entries` требуют отдельного вывода. Таблицы и все части книг сохраняются, включая текст DMG Appendices B/C; изображения исключаются при экспорте. Публичный интерфейс и body-relative source map описаны в [README экспортёра](../../src/dnd_rag/ingestion/markdown_export/README.md). Chunking/indexing не реализованы.
