# Проверка Markdown-корпуса

**Состояние корпуса:** проверены scaled-теги, компактные spell lists, headings/inline labels, отбор domain content и книжная атрибуция страниц. Карта использует классифицированные позиции текущей книги и сохраняет неполноту входных свидетельств. Три текстовых/числовых расхождения source/catalog имеют явную диагностику с выбором книжной версии. Эта проверка относится к resolved snapshot и не обещает полное постраничное восстановление печатной вёрстки. Исходные свидетельства проблем приведены в [диагностическом baseline](MARKDOWN_EXPORT_CORRECTIONS_AUDIT.md).

Корпус создаётся [самостоятельным экспортёром](../../src/dnd_rag/ingestion/markdown_export/README.md) из manifest 2.0.0 и resolved JSON schema 1.0.0. Проверенный snapshot 5e.tools — `c3d53956346388b222aaaaf4637776f563e201b8`, assembler signature — `60d007f6a1c747e87aebb75bdb340996700e7e95e9af3ab8adb75b79413f3c81`. Эти значения описывают данный корпус и не ограничивают совместимые входы экспортёра.

## Команды и файлы

Финальная генерация из корня `lab2`:

```bash
resolved_build=data/resolved/5etools/c3d53956346388b222aaaaf4637776f563e201b8/60d007f6a1c747e87aebb75bdb340996700e7e95e9af3ab8adb75b79413f3c81
PYTHONDONTWRITEBYTECODE=1 uv run python -m dnd_rag.ingestion.markdown_export \
  --input-build "$resolved_build" \
  --output-dir data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8 \
  --force
```

В output находятся ровно четыре файла:

- [xphb.md](../../data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8/xphb.md)
- [xdmg.md](../../data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8/xdmg.md)
- [xmm.md](../../data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8/xmm.md)
- [source_map.jsonl](../../data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8/source_map.jsonl)

| Файл | Байты | SHA-256 |
| --- | ---: | --- |
| xphb.md | 1240279 | `1f146cef5e362ca5e8ab5d89c89d6a681f01c0af3b1c311d46d00c20a04b0801` |
| xdmg.md | 1488013 | `ef5ceecdd785cfdbc92bace7d73f04f8df75fd2dc7d8dc737945b978631c5b45` |
| xmm.md | 1147926 | `09dd18c32513f67f87be47abcec7f463f2d8428ad6f9511c093f82f85fff6226` |
| source_map.jsonl | 1094302 | `385b102e47afaaf19d77fd4318622f9cc1889a538e73d5e059a375460a9b4577` |

Модуль состоит из публичных API/CLI, `common` (модели/строгий JSON), `rendering` (деревья, typed payloads, domain placement и карта), `publication` (manifest, проверка результата и безопасная запись). Тесты организованы в `unit/rendering`, `unit/publication`, `unit/test_api.py`, `integration`, `fixtures`, `helpers`. Полные деревья и команды установки test dependencies — в README модуля и [README тестов](../../tests/ingestion/markdown_export/README.md).

## Фактический объём

| Книга | Части H1 | Разделы карты | GFM-таблицы | Statblocks | Domain components | Известные номера страниц: min–max |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| XPHB | 12 | 2041 | 229 | 66 | 1287 | 2–377 |
| XDMG | 12 | 1796 | 260 | 2 | 992 | 5–379 |
| XMM | 5 | 699 | 632 | 504 | 382 | 2–382 |
| Всего | 29 | 4536 | 1121 | 572 | 2661 | — |

Min–max — границы известных печатных номеров, а не доказательство покрытия каждой страницы. У map records атрибуции распределены так:

| Книга | explicit | partial | inherited_section_start | unknown |
| --- | ---: | ---: | ---: | ---: |
| XPHB | 1242 | 701 | 98 | 0 |
| XDMG | 1234 | 403 | 148 | 11 |
| XMM | 49 | 600 | 50 | 0 |

Рендер завершается без критических ошибок. Есть 6 информационных сообщений `GROUPED_TABLE_HEADER` (XPHB: 1, XDMG: 5); spans и групповые подписи сохраняются. У 11 разделов XDMG нет печатной страницы: `null / unknown`. Эти сообщения не свидетельствуют о потере текста и не подменяют неизвестные страницы догадкой. `DOMAIN_SOURCE_CONFLICT` содержит три подтверждённых расхождения:

| Книжное правило | Книжная версия | Каталожная версия |
| --- | --- | --- |
| Burglar's Pack: Weight | 42 lb. | 47.5 lb. |
| Stabling per day: Cost | 5 SP | 5 CP |
| Dynamite Stick: вводная clause | As an action | An an action |

Вывод сохраняет книжные значения. Эти варианты не объявляются равными и не исправляются в JSON/upstream; обе версии доступны в diagnostics.

## Примеры готового Markdown

У Fireball основной урон — `8d6`, прирост — `1d6`, список классов компактен:

```markdown
**Classes:** Sorcerer, Wizard

The damage increases by 1d6 for each spell slot level above 3.
```

Для Heal прирост равен `10`. Cure Wounds содержит `**Classes:** Bard, Cleric, Druid, Paladin, Ranger` и прирост `2d8`. Проверены все 70 исходных scaled употреблений в 68 заклинаниях, включая числовой increment; полные предложения совпадают с grammar source. Все 391 spell cards имеют книжные main class lists без служебных Access-каталогов.

Blue Dragons: общий раздел содержит исходный Habitat **Desert**, затем идут четыре разновидности с individual lore перед своими statblocks и общий lair. Начало раздела:

```markdown
## Blue Dragons

*Dragons of Tyranny and Tempests*

- **Habitat:** Desert
- **Treasure:** Relics
```

Kobolds: общий lore не повторяется у разновидностей. В индивидуальном разделе:

```markdown
### Kobold Warrior

Kobold warriors use hit-and-run tactics to raid their enemies and defend their homes. To avoid danger, they frequently employ haphazard traps.

> **Kobold Warrior**
```

Goristro: таблица способностей берёт Score/Save из input, Mod вычисляет по score. Фрагмент единого blockquote:

```markdown
> | | STR | DEX | CON | INT | WIS | CHA |
> |:---|---:|---:|---:|---:|---:|---:|
> | Score | 25 | 11 | 25 | 6 | 13 | 14 |
> | Mod | +7 | +0 | +7 | -2 | +1 | +2 |
> | Save | +13 | +6 | +13 | -2 | +7 | +2 |
```

В том же блоке сохранены Initiative `+6 (16)`, Perception/Survival `+7`, Passive Perception `17`, Actions/Bonus Actions и исходные damage formulas.

Barbarian: progression table сохраняет все столбцы, уровни и значения:

```markdown
| Level | Proficiency Bonus | Class Features | Rages | Rage Damage | Weapon Mastery |
| --- | --- | --- | --- | --- | --- |
| 1 | +2 | Rage, Unarmored Defense, Weapon Mastery | 2 | +2 | 2 |
| 2 | +2 | Danger Sense, Reckless Attack | 2 | +2 | 2 |
```

Features и Berserker/Frenzy находятся у класса. Проверены все 48 подклассов данного input. Inline features сохраняют дополнительные исходные абзацы и недостающие структурированные поля канонического компонента; неполный текст, конфликтующие поля или неизвестная механика не считаются доказанным покрытием.

Каждый из 12 классов имеет один H2 полного описания; его обзорное упоминание перед полными описаниями остаётся inline label со своим текстом и списком путей. Rage и его подпункт представлены так:

```markdown
### Level 1: Rage

***Damage Resistance.*** You have Resistance to Bludgeoning, Piercing, and Slashing damage.
```

В Arcane Study исходные правила используют labels:

```markdown
***Arcane Study Charm.*** After spending a Long Rest in your Bastion, you gain a magical Charm ...

***Craft Options.*** When you issue the Craft order to this facility, choose one of the following options:
```

Эллипсис в первом фрагменте сокращает пример документации; готовая книга содержит весь текст: длительность 7 дней/до использования, Identify, условия применения и запрет повторного получения. Списки Craft сохранены. Отдельная reward-карточка не добавляет копию эффекта. То же проверено для Observatory, Reliquary, Sanctuary и Sanctum Charm, включая typed spell identity и ограниченный use.

Единственный повторный полный путь — XMM `Monsters A to Z / Gray Oozes / Gray Ooze`: два подтверждённых исходных occurrences. Все 12 class overview остаются labels; четыре Explosives и пять Charm не создают каталожных копий правил. Уникальность пути не является контрактом; совпадающие названия не удаляются автоматически.

В Explosives сохранены семь строк свойств и каждый полный исходный rule paragraph: Bomb, Dynamite, общее применение гранат, Fragmentation, Smoke и Gunpowder. Общее правило контейнеров содержит `10 (3d6)` для powder horn, `24 (7d6)` для keg, радиус 10 feet, DC 12 и half damage on success. Каталожные карточки не повторяют ни эти условия, ни grenade-launch paragraph.

Проверяемый отбор items/rewards/indexes охватывает 110 компонентов этого snapshot:

| Книга | already_represented | rendered: недостающий остаток | source_preferred | metadata_only |
| --- | ---: | ---: | ---: | ---: |
| XPHB | 51 | 30 | 2 | 0 |
| XDMG | 11 | 0 | 1 | 0 |
| XMM | 0 | 0 | 0 | 15 |

В `source_preferred` Burglar's Pack сохраняется его дополнительный Contents. Для 30 PHB property supplements дословно сохранены значения 16 Capacity, 8 Contents, 5 Light и 1 Poison; у Trinket сохраняется необходимая таблица после единственного книжного введения. Шесть tool kits используют исходные Ability/Weight/Utilize/Craft lists и общее книжное правило proficiency. Проекции полных именованных строк сохраняют style, значения и порядок; `entry` и одноэлементное `entries` сопоставляются как допустимые native forms.

Для решений об отборе items/rewards доступны field-level coverage, непокрытые fields, anchor и parent. Costs/weights подтверждаются defining row, именованным свойством или ценой в книжной подписи; type-expansions — связью и полным общим правилом. Facility rewards проверены отдельно по тексту, типу, parent reference и spell use. Все 15 XMM language components содержат только индекс типичных говорящих у creature-placement. Их каталожные поля не становятся текстом книги; языки statblocks и PHB language rules сохранены.

Все 2661 компонента имеют решение; 2551 решение вне этого отбора сохраняется. Групповой и individual lore, 48 подклассов, Frenzy/Agonizing Blast и необходимые дополнения, включая Psychic Gray Ooze, остаются в книжных местах.

Summon Aberration содержит связанный Aberrant Spirit. AC/HP остаются формулами, не вычисляются для произвольно выбранного spell slot:

```markdown
> **AC:** 11 + the spell's level — **Initiative:** +0 (10)
>
> **HP:** 40 + 10 for each spell level above 4
>
> **Speed:** 30 ft., Fly 30 ft. (hover; Beholderkin only)
```

Bag of Holding сохраняет свойства вне entries:

```markdown
**Weight:** 5 lb.

**Capacity:** 500 lb.; contents add no weight
```

Его исходный текст также содержит предел объёма `64 cubic feet`. У Black Dragon Scale Mail отдельно указаны Base AC `14`, AC Bonus `+1`, attunement и Acid resistance; правило Stealth берётся из готового `_fullEntries`. Регрессии сравнивают значения с JSON и независимо разобранным Markdown, не используют production-форматтеры как источник ожидаемых строк.

## Точные координаты source map

Реальная запись XMM:

```json
{"book_id":"XMM","file":"xmm.md","heading_path":["Monsters A to Z","Blue Dragons","Young Blue Dragon"],"line_start":3589,"line_end":3628,"start_char":145073,"end_char":146399,"printed_pages":[48],"page_attribution":"partial"}
```

После отделения YAML и одной пустой строки проверено точное равенство `body[145073:146399] == ''.join(lines[3588:3628])`, где `lines` сохраняет LF. Это 1326 Unicode code points и 40 строк; фрагмент начинается с `### Young Blue Dragon`. Координаты относятся **только к Markdown-body без YAML**. Проверка выполнена для всех 4536 записей, включая полные границы разделов, вложенность, siblings, terminal LF и Unicode. Исполняемый stdlib пример — в README экспортёра.

## Проверки и границы результата

Полный прогон использует pytest, markdown-it-py и PyYAML из группы `test`; production — stdlib. uv подготавливает окружение проекта и подключает тестовые зависимости. Команда полного прогона из корня `lab2`:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --group test python -m pytest \
  tests/ingestion/markdown_export -q --tb=short \
  -o cache_dir=/tmp/dnd-spell-italics/pytest-cache \
  --basetemp /tmp/dnd-spell-italics/full-tests \
  --input-build "$resolved_build" \
  --junitxml /tmp/dnd-spell-italics/tests.xml
```

Результат проверенного прогона: **436 passed** — 359 unit и 77 integration, без failures/errors/skipped/xfail; время прогона 35.13 s. Два проверочных CLI exports в `/tmp` при разных hash seeds завершились с кодом 0 и дали побайтно те же четыре файла, что API и опубликованный корпус. `uv run --group lint ruff check` и `uv run --group lint ruff format --check` проходят для всех 54 Python-файлов экспортёра и его тестов. Форматирование и порядок импортов заданы в `pyproject.toml`; Ruff устанавливается отдельно от runtime в группе `lint`.

Независимые parsers проверяют YAML/Markdown AST, главы, таблицы и source map. Проверяются 1264 непосредственные damage/dice formulas, 1076 буквальных source table rows, все domain decisions и 243 individual lore sections / 274 буквальных абзацев перед их statblocks. Полный список регрессий — в README тестов. Курсив spell references проверяется на вложенных tags, aliases, plain-заголовках и семи полных абзацах PHB/DMG; те же регрессии проходят на сохранённом историческом build. Negative tests охватывают manifest/пути/хэши/JSON, неизвестную разметку и поля, некорректные scaled grammar/class indexes, неполные canonical representations, неоднозначные rows/owners/order, нарушенную кратность, ложные list/container projections и неизвестные вложенные поля. Source/catalog conflicts проверяются как явный выбор первичного текста, а новые игровые поля сохраняются; Page fixtures дополнительно проверяют foreign/reference/ambiguous origins, повторные occurrences, независимый section start, native siblings и compact evidence; fault injection — запись, замену, rollback, cleanup и interruption. API/CLI проверяются в отдельных процессах.

Повторная генерация и перенос только четырёх входов дают побайтно одинаковые выходы при разных hash seeds. Проверено отсутствие сетевого доступа и чтения upstream/сборщика во время рендера. Все 41 защищённый файл входов/сборщика, HEAD и tracked Git state submodule остаются неизменными.

Независимая сверка полного корпуса подтверждает исходную прозу каждой части, обоснованное отсутствие каталожных копий и дословную сохранность непокрытых игровых полей. Книжный текст дополняется только непокрытыми каталожными полями и правилами в их подтверждённом месте. Iron Spike представлен однотипным набором: совпадает полное правило, 10 × 0.5 lb. = 5 lb., 10 × 10 CP = 100 CP; Contents содержит тот же typed UID. Дополнительные unit fields требуют отдельного вывода. Все 1121 таблиц совпадают по ячейкам. AST всех трёх книг совпадает по всем узлам, кроме emphasis; видимый текст, включая 572 statblocks, совпадает полностью. Headings/maps описывают структурные разделы; координаты пересчитаны из готового body.

Page evidence проверяется отдельно от текстового представления. Приоритет имеют собственный книжный узел и фактический wrapper placement; same-book native origin используется только как локальное определение при согласованном source, однозначном lookup и совместимом книжном контексте. Context limits служат проверке origin, не источником вымышленных end pages. Для каждого occurrence используется его собственное место, а не canonical anchor первой вставки.

| Раздел | printed_pages | Attribution |
| --- | --- | --- |
| XPHB Chapter 1: Playing the Game | `[7,31]` | partial |
| XPHB Exploration | `[19,22]` | partial |
| XPHB Conditions | `[29,31]` | partial |
| XPHB Chapter 3: Character Classes | `[49,175]` | partial |
| XDMG Chapter 4: Creating Adventures | `[105,125]` | partial |
| XMM Monster Lists | `[374,382]` | explicit |
| XMM Monster Conversions | `[374]` | explicit |

Ранний Stunned использует `[29] / inherited_section_start`, а его самостоятельное включение в Rules Glossary — `[376] / partial`. Ранний Suffocation наследует начало Hazards `[20]`; страница его справочного определения не выдаётся за место в первой главе. Overview классов не получает собственные target pages: для этого контекста подтверждено начало главы 49. Локальные native pages сохраняются: например, Fireball 274 и Young Blue Dragon 48.

Не все необходимые материалы имеют собственную точную страницу. Для PHB Ape подтверждён только PHB section start 346; foreign XMM origin не используется. У individual lore может отсутствовать page; тогда известная страница statblock даёт partial evidence. Derived Lair Actions/Regional Effects не получают автоматически explicit page всей каталожной группы. При отсутствии собственных points остаётся inherited section start; без него — `null / unknown`.

Для всех 4536 records независимо проверены Unicode/LF-координаты готового body. Количество и пути headings, printed pages и attributions сохраняются при добавлении emphasis; все 2661 domain decisions и diagnostics совпадают. Source namespaces, reference targets, compact blocks и native context проверяются до агрегации. Начало раздела хранится отдельно от min/max его содержимого; inherited значения не становятся explicit. Непечатаемые navigation labels не добавляют страницу следующей группы предыдущему leaf.

Все records проверены на пересечение эвристических границ соседних глав и необычно широкие диапазоны. Единственный выход за такую границу подтверждён собственным source inset на page 4 при начале XMM How to Use a Monster на page 5; диапазон `[4,9]` сохраняется без искусственного ограничения. Четыре диапазона шириной от 100 страниц относятся к реальным крупным частям: Character Classes, Spells, Treasure и Monsters A to Z. Неподтверждённых cross-chapter origins при этой проверке не осталось. Границы min/max описывают известные позиции, а не непрерывное покрытие каждой печатной страницы.

В проекте сохраняются исходники, fixtures/тесты, документация, зависимости, готовый resolved build и четыре Markdown-артефакта. Прототипы, дубли выгрузок, промежуточные проверочные скрипты, старые отчёты и Python/pytest cache не нужны для работы модуля. JUnit вынесен в `/tmp`; постоянного report-формата у экспортёра нет.

Проверка относится к resolved snapshot, без PDF/OCR и постраничного сравнения. Две исходные Gray Ooze сохранены, Psychic Gray Ooze добавлен по canonical placement. Неизвестные структуры завершают экспорт с диагностикой. Публикация восстанавливает прежний корпус при обрабатываемых ошибках, но не обещает crash-atomicity при kill -9/потере питания; между двумя rename output кратковременно отсутствует. Индексация, чанкинг и RAG в этот этап не входят.
