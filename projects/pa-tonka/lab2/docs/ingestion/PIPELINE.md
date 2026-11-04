# Механизмы сборки и проверки

Точка входа — [resolution/resolve_books.mjs](../../src/dnd_rag/ingestion/book_assembly/resolution/resolve_books.mjs). Ниже описан актуальный production-проход после реорганизации, а не порядок исследовательских этапов. Термины wrapper, origin и canonical placement определены в [модели данных](DATA_MODEL.md).

## 1. Preflight и идентичность сборки

`inspectSnapshot` находит основной Git root и запись submodule mode `160000` в дереве **HEAD**, проверяет инициализацию, checkout SHA и чистоту tracked-файлов, включая staged changes внутри upstream. Несвязанные ignored/untracked файлы сами по себе не означают изменения snapshot. Затем проверяется Node engine из upstream `package.json`; текущий snapshot требует `>=24`.

Для финальной signature хэшируются production `.mjs/.json/.py` внутри `book_assembly`, включая схему и atomic helper. README, `dev/`, тесты и tmp выходы в эту карту не входят. Generator содержит версию resolver, schema version, Node, code digest и нормализованную конфигурацию: выбранные книги, strict policy и алгоритм content hash. Порядок выбора книг нормализуется по core IDs.

`build_id = upstream_sha / generator.signature`. Пути вывода, диагностический режим, `--force`, `--validate-only` и случайный tmp root не определяют содержимое и не входят в signature. Fingerprint доступен **до** подготовки входов, поэтому проверка готовой сборки не требует сохранённых inventory/enriched-файлов.

Обычный повтор проверяет текущий build через `verifyResolvedBuild` и возвращает `PASS (reused)`. `--validate-only` выполняет ту же read-only проверку и не создаёт входы или отчёты об ошибке. Обе команды всё равно требуют чистый pinned upstream. Без готового текущего build `--validate-only` завершается ошибкой.

## 2. Инвентаризация

Inventory читает все tracked JSON из upstream `data/` и сохраняет digests. Книги выбираются по уникальному `id` в `books.json` и `book-*.json`, затем сопоставляются с `contents` по составу и порядку. Допустимы стандартные префиксы `Chapter N:`/`Appendix X:` и одна проверяемая пара XMM: `Introduction` / `How to Use a Monster`. Неизвестное отличие не переименовывает источник автоматически, а даёт ошибку.

Обход учитывает все JSON-поля, включая значения вне `entries`. Фиксируются каждая позиция, JSON Pointer, тип/name/id, контекст страницы, таблицы/изображения и ссылки. Обязательные statblocks, структурные `ref...`/`{#...}`, обычные entity tags, query/document/navigation/formatting tags классифицируются раздельно. Tokenization и UID/hash grammar берутся из upstream; spans имеют единицы **UTF-16 code units**, поэтому Python slice по Unicode code points им не равен. Default source также задаёт upstream: например, `{@spell Fireball}` не становится XPHB автоматически из-за расположения строки в пересмотренной книге.

Source catalog индексирует записи корневых массивов с `source` выбранной книги; у magicvariant учитывается `inherits.source`. Foundry overlays, generated projections, book structure и canonical source records различаются. Метаданные внешних прямых целей не становятся рекурсивным чужим корпусом. Для обязательных книжных целей вызывается native required lookup, включая loader-generated items. Неизвестные identity/ref/type и отсутствующие required targets блокируют следующую стадию.

Entry grammar проверяется и внутри исходных карточек. Типы `range/duration`, monster/item metadata отделены от render entries; `statblockData` начинает новый payload. Неизвестный render type даёт `UNKNOWN_SOURCE_ENTRY_TYPE` с prop, record ID, файлом и точным Pointer.

## 3. Главы и native resolution

Для каждой исходной главы `assembleChapter` вызывает `Renderer.utils.preload.pGetPreloaded`. Оригинал не мутируется. Native preload может вернуть unresolved statblock без исключения, поэтому каждый ожидаемый ref сверяется по исходному occurrence. При silent miss выполняется `DataLoader.pCacheAndGet(..., {isCopy: true, isRequired: true})` и повторный preload.

Упаковка wrapper сохраняет полный исходный reference, lookup, processed data, placement и entity origin. Физический record проверяется по raw hash, набору полей, source и native identity. Для виртуального item требуется реальный base и template; физический путь не придумывается. Несколько физических кандидатов помечаются явно.

Оставшиеся активные refs проверяет `auditRequiredReferences`. Для native `DataLoaderDereferencerFacade` используются соответствующие верхние поля payload. Для `refOptionalfeature/refFeat` задаётся `preserve.prerequisite: true`, поскольку generic feature dereferencer иначе может убрать требования. Fallback ограничен двумя проходами и проверкой прогресса; активный `_copy` после native loading является ошибкой. Неизвестные processed entry types также отклоняются. Исходные recipes под `_versions/entriesTemplate/_mod` помечаются отдельно от активных ссылок.

В текущих книжных деревьях все обязательные refs — statblocks. Новый тип обязательной ссылки непосредственно в книге требует поддержки source placement и wrapper conversion; известность такого типа внутри entity не означает, что book-level adapter уже умеет его раскрывать. Сейчас этот случай явно останавливается как `UNSUPPORTED_BOOK_REFERENCE`.

После преобразования независимый validator восстанавливает каждую главу через `original_reference`, сравнивает исходный JSON и порядок, все occurrence IDs, sources/pages и таблицы/изображения **на исходных местах**. Общие итоговые счётчики могут увеличиться из-за добавленных карточек.

## 4. Доменное обогащение

Граф начинается с явных вставок, определяющих табличных строк и именованных разделов своей книги. Каждый новый компонент должен иметь source evidence, реальный книжный anchor и объяснённое отношение. Canonical registry и очередь ограничивают разворачивание; обычный prose tag сам по себе не запускает поиск всей внешней библиотеки.

| Область | Правило |
| --- | --- |
| Class/subclass | Точные source/classSource/className; отдельные полные class/subclass features, уровни, таблицы развития, стартовые сведения и fluff |
| Feat/optional feature | Сохранение prerequisites, featureType, repeatable, cost, additionalSpells и остальных исходных полей |
| Summons | Обратные связи `summonedBySpell/summonedByClass`; один canonical placement у родителя, полные формулы и исходные `_versions` без выбора произвольного уровня |
| Monster | Индивидуальный/групповой fluff, native copy/mod, legendaryGroup и имеющиеся regional/lair data; совпадающие blocks отмечены в shared content |
| Items | ItemGroup members, packContents, ammunition, properties/masteries/types, реальные templates и derivations; deck/card/vehicle representations и subsets |
| Другие категории | Species/race, backgrounds, conditions/actions/rules, hazards/traps, bastions/facility rewards, skills/languages/deities, loot и приложения по фактическим данным |

`itemType` читается из native `Renderer.item.getType` после item build: этот registry не является обычным hover cache. Для поддерживаемых loot/script metadata используется полный проверенный source JSON с методом `verified_source_metadata`. Это явные маршруты, не fallback по одному имени.

Отдельные правила дополняют scope локальным evidence: связанные с предметом существа той же книги, equipment монстра, weapon из feature, упаковки уже размещённых предметов, source-defined aliases разделов/табличных labels и действия внутри содержащих правил. Все правила находятся в `enrichment_plan.mjs` / `enrichment_content.mjs` и проверяются source audit. Например, item `classFeatures` может означать доступность для внешнего Artificer; оно не трактуется как состав класса XPHB и не расширяет чужую книгу.

## 5. Исчерпывающий placement audit

Каждая source-defined запись выбранных core источников получает решение:

| Статус | Доказательство |
| --- | --- |
| `materialized` | Полный raw source recipe и resolved payload у canonical anchor |
| `represented_book_structure` | Сохранённые book/catalog metadata и все главы |
| `represented_generated_projection` | Generated navigation/rule/table view совпадает с уже материализованной структурой |
| `excluded_tool_integration` | Отдельное Foundry-представление, не самостоятельный tabletop material |
| `excluded_renderer_taxonomy` | Неиспользуемый category label без описания/правил, только разрешённые metadata fields |
| `excluded_web_font_asset` | Font registry без narrative/rules/image content |
| `unreviewed_critical` | Нет доказанного placement или узкого допустимого исключения; сборка FAIL |

Generated tables сравниваются по **всем содержательным полям**, включая footnotes, caption, colLabelRows, styles и новые поля. Нормализуются только доказанные navigation/control transforms штатного generator. Faux groups требуют конкретные source controls и полный состав/порядок таблиц. Generated rules сопоставляются с entries с учётом удаления source entry IDs штатным generator. Слепого исключения всей generated-категории нет.

Проверяются raw recipes по физическим Pointers, игровые поля, prerequisites, дочерние features/cards, closure обязательных endpoints, source pages, canonical forest и точные shared-content paths. Финализация повторяет проверку enriched inputs и placement decisions перед объявлением книги полной.

## 6. Сериализация и финализация

Строгий JSON отвергает undefined, функции, Map/Set, NaN/Infinity, sparse arrays, циклы и неизвестные нестандартные объекты. Сериализация не удаляет поля ради удобства. Допустимы два проверяемых native runtime omissions:

- `variants` cache generic magicvariant с парами `base/specificVariant`, если в source record такого поля нет; все теоретические комбинации не становятся книжными карточками;
- undefined optional `_baseSrd`, `_baseSrd52`, `_baseBasicRules`, `_baseFreeRules2024`, `_baseValue` у native Specific Variant.

Omissions записываются в detailed report. `_fullEntries`, исходные игровые поля, tags, формулы, таблицы и изображения остаются. Оболочка книги формируется без изменения `book/chapters/domain`, затем проверяется после JSON round trip. Считаются file/content hashes и manifest 2.0.0 с краткими validation results.

## 7. Публикация, force и ошибки

Writer получает lock `.<signature>.lock` только для своего build-id. Все файлы сначала полностью пишутся и fsync-ятся в sibling `.<signature>.staging-*`, затем проверяются как готовая сборка и выполняется повторный preflight. Первая публикация — rename. `--force` использует Linux `renameat2(RENAME_EXCHANGE)` через stdlib Python helper: читатель видит прежний или новый полный каталог без окна отсутствия build-id.

Force заново готовит/проверяет необходимые промежуточные стадии и финализирует книги. Явные проверенные developer inputs можно переиспользовать. Подменяются только текущий вычисленный build-id и управляемые им файлы. Чужая identity, нечитаемый manifest, symlinks и посторонние файлы не удаляются автоматически. Повреждённый известный book/hash при читаемом manifest исправляется force.

Ошибки до publication не меняют прежний валидный результат. После входа в финальную orchestration пишется компактный failure report вне `data/` с `published_books: []`; preflight/argument errors могут остановиться раньше, оставив только stderr. В диагностическом режиме stage reports остаются в указанном root. Default tmp удаляется и при ошибке, пустой failed snapshot output directory убирается; valid соседние версии сохраняются.

Нормальный выход освобождает свой lock/staging. Жёсткое прерывание процесса может оставить lock/staging; автоматической очистки после crash нет. Post-publication cleanup/fsync warning не откатывает уже выполненную атомарную публикацию. Действия при сбоях описаны в [DEVELOPMENT.md](DEVELOPMENT.md).
