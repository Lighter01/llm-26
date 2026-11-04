# Валидация, результаты и ограничения

Проверен локальный snapshot **5e.tools 2.39.0**: `8790755429c346d20020eed7826d312d484c393f`. Resolver **0.6.2**, схема книги **1.0.0**, manifest **2.0.0**. Checkout совпадает с gitlink из HEAD; tracked upstream чистый до и после проверок. Результат — **PASS_FOR_PINNED_SNAPSHOT**.

## Актуальный результат

```text
data/resolved/5etools/8790755429c346d20020eed7826d312d484c393f/
└── 60d007f6a1c747e87aebb75bdb340996700e7e95e9af3ab8adb75b79413f3c81/
    ├── xphb.resolved.json
    ├── xdmg.resolved.json
    ├── xmm.resolved.json
    └── manifest.json
```

Это конкретная проверенная версия, не путь «latest». Историческая сборка resolver 0.6.1 сохранена отдельно; при реорганизации её manifest адаптирован к четырёхфайловому хранению без изменения байтов книг. Обычная CLI работает с signature текущего кода/настроек. Версионирование объяснено в [PIPELINE](PIPELINE.md), чтение исторического JSON — в [DATA_MODEL](DATA_MODEL.md).

| Проверяемая величина | XPHB | XDMG | XMM |
| --- | ---: | ---: | ---: |
| Исходные части, включая credits | 12 | 12 | 5 |
| Обязательные книжные occurrences | 730 | 463 | 750 |
| Canonical entities | 1 997 | 1 325 | 1 131 |
| Supplemental domain components | 1 287 | 862 | 382 |
| Source-record appearances в этой книге | 1 997 | 1 321 | 1 131 |
| Исходные таблицы по местам | 53 | 159 | 16 |
| Исходные изображения по местам | 63 | 160 | 322 |

Все 29 частей точно восстанавливаются через `original_reference`, включая Appendices B/C DMG. Сохранены структура, порядок и нетекстовые metadata. 51 PHB statblock occurrence имеет entity source XMM; placement остаётся XPHB.

Inventory проверил 519 tracked data JSON, 54 968 исходных позиций значений, 10 154 reference/tag records и 1 871 уникальную обязательную цель для 1 943 появлений. Неразрешённых активных обязательных вставок и неизвестных книжных entry types нет. 12 классов XPHB имеют все 48 соответствующих subclasses этого snapshot; ожидания вычисляются из source index.

### Учёт source-defined материала

Все **5 665** записей core источников имеют decision:

| Решение | Число |
| --- | ---: |
| Materialized в собственной книге | 4 311 |
| Foundry overlays | 1 096 |
| Проверенные generated projections | 248 |
| Book/catalog structure | 6 |
| Неиспользуемые renderer category labels без правил | 3 |
| Web font registry без книжного содержимого | 1 |
| Unreviewed critical | **0** |

Три taxonomy records XPHB — Other/Potion/Scroll; font registry — Draconic. Это узкие объяснённые исключения в контексте PHB. Category label, необходимый DMG/MM, включён туда как dependency. Всего в трёх самодостаточных JSON 4 449 source-record appearances и 4 314 distinct record IDs: cross-book repetitions не являются неклассифицированной потерей или второй независимой книгой. Виртуальные items имеют доказанные base/template derivations.

Все числа относятся к указанному commit. В коде проверки не закрепляют универсальные количества spells/monsters/classes по памяти.

## Автоматические проверки

Текущий полный прогон: **75/75 PASS**, 0 failed/cancelled/skipped/todo. В счётчиках Node учитываются parent tests и subtests. Группы: 47 unit/fixture, 6 native smoke и 22 integration/regression checks. Команды и отчёт runner — в [руководстве разработчика](DEVELOPMENT.md).

Следующая матрица соответствует checklist ТЗ §9.3. Final regressions находятся в [corpus_regressions.mjs](../../tests/ingestion/book_assembly/helpers/corpus_regressions.mjs) и вызываются сквозным integration-тестом над заново собранными JSON.

| Пункт | Проверка | Свидетельство |
| --- | --- | --- |
| 1 | R01 | Все source classes/subclasses, точные class/source/level, progression и стартовые поля |
| 2 | R02 | Barbarian, полный Berserker и Frenzy уровня 3 |
| 3 | R03 | Структурированные prerequisites Agonizing Blast и поля всех optionalfeature XPHB |
| 4 | R04 | Все source spell/class summons, один canonical placement, полные формулы и правильные parents |
| 5 | R05 | Aeromancer copy/mod, индивидуальный/общий lore, точные shared blocks |
| 6 | R06 | Aboleth: механика, legendary/regional data, source/page |
| 7 | R07 | Adult Black Dragon: механика, реальные group effects, source/page |
| 8 | R08 | DMG items/groups/variants, attunement/charges, раскрытый itemEntry и generated provenance |
| 9 | R09 | Все главы/приложения, source tree/order, таблицы и изображения по исходным позициям |
| 10 | R10 | Нет активных mandatory refs; raw tags и cross-book attribution сохранены |
| 11 | R11 | Unknown book ref и новый entry type внутри настоящей fixture spell блокируют публикацию |
| 12 | R12 | Реальные fixture commits/gitlinks: новый каталог/file hash и прежний content hash при неизменных данных; dirty/mismatch/staged-only отвергаются |
| 13 | R13 | Reuse/validate-only без входов, byte-identical force exchange, corruption recovery и сохранность соседних версий |

S01 проверяет каноническую Draft 2020-12 schema и каждый wrapper независимым Ajv; `strictRequired: false` отключает эвристику required внутри anyOf с parent properties, а не сами required constraints. S02 независимо сканирует все tracked data JSON и требует decision/full raw либо узкое исключение для каждой core source record.

Unit fixtures проверяют строгую сериализацию, pages/IDs, ошибки/циклы, generated table footnotes/labels/styles/new fields и порядок faux groups, противоречивые origins/IDs, locks, symlinks и сбой exchange. Native smoke сравнивает Acid Splash и Ape с локальными raw, проверяет Aeromancer copy/mod, silent miss, required lookup и запрет сетевого JSON до запроса.

Source completeness validation при сборке читает физические upstream records. Standalone validator проверяет контракт и самодостаточность уже готовой книги. Manifest verifier дополнительно проверяет состав каталога, identity, размеры, оба хэша и агрегаты. Эти проверки дополняют друг друга; одна JSON Schema не доказывает полноту материала относительно исходников.

После реорганизации дополнительно проверены четыре файла в каждом final build, cleanup обычного workspace при успехе/ошибке и работа всех сохранённых CLI. Удалён отдельный устаревший prototype resolver вместе с его tests; выбор главы сохранён в `chapter_probe.test.mjs`, повторные placements/unknown page перенесены на production assembly. Полные книжные регрессии сохранены.

## Выборочный аудит JSON против исходников

Для актуальной сборки повторно прочитаны выбранные фрагменты, выполнены независимые stdlib Python обход/Pointer/source comparison без production validators для получения ожидаемых значений. Все 4 449 `source_records.raw` совпали с физическими исходными записями. Проверено наличие 51 608 верхних полей записей без `_copy` и 900 собственных полей copy recipes помимо `_copy`; пропавших ключей нет. Само наличие ключей не доказывает семантику всех native преобразований, поэтому важные случаи дополнительно сопоставлены по значениям.

Пути в таблице относятся к `external/5etools-src`; Pointer после `#` адресует source JSON. Номера и placements взяты из snapshot, не из печатной сверки. Всего проверено 16 выборок; связанные случаи объединены в строках.

| Выборка | Физический источник | Что сверено |
| --- | --- | --- |
| Barbarian / Berserker / Frenzy | `data/class/class-barbarian.json#/class/1`, `/subclass/18`, `/subclassFeature/75` | Таблицы, стартовые сведения, native features, source/class/subclass, Frenzy level 3; entity pages 50/54 сохранены |
| Agonizing Blast | `data/optionalfeatures.json#/optionalfeature/1` | Полный raw и structured prerequisite с Warlock level 2/условием выбора cantrip; page 155 |
| Summon Aberration / Aberrant Spirit | `data/spells/spells-xphb.json#/spell/332`, `data/bestiary/bestiary-xphb.json#/monster/0` | Все raw fields, higher-level text, formula AC/HP, actions и parent relation; page 322 |
| Aeromancer statblock / fluff | `data/bestiary/bestiary-xmm.json#/monster/0`, `data/bestiary/fluff-bestiary-xmm.json#/monsterFluff/1` | Статистика page 10; индивидуальный prependArr перед полным Aarakocra lore, parent images и shared paths; fluff page остаётся unknown |
| Aboleth / legendary group | `data/bestiary/bestiary-xmm.json#/monster/3`, `data/bestiary/legendarygroups.json#/legendaryGroup/1` | Все raw mechanic fields, actions/legendary и три regional effects; page 12 |
| Adult Black Dragon | `data/bestiary/bestiary-xmm.json#/monster/5` | Все raw mechanic fields и связанная group с тремя regional effects; page 39 |
| Bag of Holding | `data/items.json#/item/144` | Внешняя книжная вставка, полный текст/properties, rarity, weight, capacity и page 234 |
| Black Dragon Scale Mail | `data/items.json#/item/214` | Все raw fields кроме native-expanded entries; три description entries из `items-base.json → itemEntry: Dragon Scale Mail`, acid substitution, без активного `{#` |
| DMG lore glossary: Acererak | `data/book/book-xdmg.json#/bookData/0/data/8/entries/1` | Точное равенство source subtree в исходной позиции |
| DMG ability checks table | `data/book/book-xdmg.json#/bookData/0/data/1/entries/6/entries/4` | Все поля/строки/структура таблицы без изменений |
| Изображение введения DMG | `data/book/book-xdmg.json#/bookData/0/data/0/entries/0` | Полный image object и metadata сохранены; пиксели не открывались |

У Aboleth и Adult Black Dragon в этом snapshot **нет `lairActions`** в group; они не выдумываются на основании наличия логова. Это проверяется вместе с наличием действительных regional effects.

### Воспроизводимость и хэши

Содержательные digests всех трёх книг сохранились после реорганизации:

| Книга | `content_sha256` (`dnd-book-content-v1`) |
| --- | --- |
| XPHB | `6e270d157cee379de940dbe8fe847a546657e0e3424f8817b0103003243f8869` |
| XDMG | `6557b3f6f88c76bd3435237efb52ba599f5b101c9308b69d9725a399ebe29487` |
| XMM | `25e0b73f69c189404a13872092be1add7562970a2e79a81cafcf1885d3e080ee` |

File hashes и размеры конкретной версии находятся в её manifest. Они отличаются между resolver 0.6.1 и 0.6.2 из-за generator/provenance, хотя `book/chapters/domain` совпадают. На этапе документации код/книги не переписываются; свежая диагностическая сборка текущего build-id даёт те же четыре файла. Python- и Node-примеры из DATA_MODEL проверяются на этих готовых книгах.

## Предупреждения и границы результата

- У 270 / 346 / 341 дополнительных компонентов XPHB/XDMG/XMM нет точной собственной страницы. Сохраняется `null/unknown`, отдельно от известного anchor.
- 1 обычная внешняя ссылка DMG и 60 MM остаются tags без разворачивания чужих книг.
- XMM Gray Oozes содержит две одинаковые вставки Gray Ooze. Обе исходные позиции сохранены; Psychic Gray Ooze добавлена как компонент по собственной fluff copy связи с этой группой и совпадающей source page 151. Это source supplement, а не исправление/подмена исходного reference.
- Native theoretical item combinations не превращаются в новые книжные записи; source recipes и необходимые реальные варианты сохранены.

Критических блокеров и неклассифицированных source omissions на этом snapshot нет. Это полнота относительно локального репозитория, а не обещание полноты печатного издания. Полная постраничная сверка, OCR, чтение карт и скачивание изображений не проводились. Новый upstream, schema или code fingerprint требует новой проверки. Этот документ оценивает сборщик; проверки Markdown описаны в [тестах экспортёра](../../tests/ingestion/markdown_export/README.md). Chunking/RAG здесь не оцениваются.
