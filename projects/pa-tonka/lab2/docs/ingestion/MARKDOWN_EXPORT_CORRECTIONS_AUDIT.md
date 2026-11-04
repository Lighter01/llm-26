# Диагностический baseline Markdown-экспорта

Дата baseline: 2026-11-03. Документ фиксирует инвентаризацию, воспроизведение и диагностику по шагам 1–2 раздела 9 ТЗ исправлений, до изменения реализации. Фрагменты, численности, контрольные суммы и позиции кода ниже относятся к этому базовому варианту. Актуальные правила и результаты проверки опубликованных файлов приведены в [MARKDOWN_EXPORT_VALIDATION](MARKDOWN_EXPORT_VALIDATION.md).

**Baseline имеет подтверждённые содержательные ошибки.** Успешные тесты и точность координат карты не подтверждают правильность числовых правил, выбора печатного содержимого и печатных страниц.

## Входы и воспроизводимый baseline

Проверен единственный существующий build:

```text
data/resolved/5etools/8790755429c346d20020eed7826d312d484c393f/
  60d007f6a1c747e87aebb75bdb340996700e7e95e9af3ab8adb75b79413f3c81/
```

Manifest 2.0.0 содержит успешную проверку сборки; книги имеют schema 1.0.0, resolver 0.6.2, upstream 5e.tools 2.39.0. `read_build` заново проверил размеры, file SHA-256, состав книг и snapshot. Отдельно вызваны существующие чистые функции `validateResolvedBook` и `contentSha256` для всех трёх книг: схема, граф и content hash соответствуют manifest. Сборщик и загрузчики данных не запускались.

| Книга | Части | Исходные вставки | Canonical entities | Domain components | Relationships | Headings/maps | GFM-таблицы | Statblocks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| XPHB | 12 | 730 | 1997 | 1287 | 1909 | 2963 | 229 | 66 |
| XDMG | 12 | 463 | 1325 | 862 | 2304 | 2329 | 260 | 2 |
| XMM | 5 | 750 | 1131 | 382 | 1268 | 709 | 632 | 504 |

Это размеры проверенного snapshot, а не требования к будущим версиям данных. 6001 запись карты прошла независимую проверку Markdown AST, YAML, полных границ, вложенности, Unicode/LF и координат относительно body без YAML. Семантика печатных страниц проверяется отдельно ниже.

Baseline существующих тестов: **271 passed**, 236 unit и 35 integration, 40.51 секунды. Среда: Python 3.13.1, pytest 9.1.1, markdown-it-py 4.2.0, PyYAML 5.4.1. Ruff 0.15.20: lint успешен, все 46 файлов уже отформатированы. Два отдельных запуска CLI с `PYTHONHASHSEED=1` и `73` создали ровно четыре файла; все байты совпали между собой, с `render_build` и с опубликованным корпусом.

Контрольные суммы существующих выходов:

| Файл | Байты | SHA-256 |
| --- | ---: | --- |
| xphb.md | 1525186 | `ab892c75645a0ada0491ca750d8d2b39b0c98a2b4c2ff2e9bd010c0dfda5b5b3` |
| xdmg.md | 1492553 | `fb2a270aa6fc89e943e0039198a92d15cab4e352e0816eb876dab9fa93eba155` |
| xmm.md | 1147012 | `6bafb4965b18367d0ea80be8d4ca45cb5a7dfbaffaaa6c8a5dd3e7c9569e1d1b` |
| source_map.jsonl | 1491398 | `6cf404bd01879be90e296561ecf4b8832bcc70b89b4208d71749277bd765248f` |

## Сопоставление со штатным renderer

Три пользовательские выгрузки глав в доступном контексте и файлах проекта не обнаружены. Эталонные фрагменты получены локально настоящим renderer закреплённого submodule, без его изменения и без runtime-зависимости Python от JS.

Изучен фактический путь книжного экспорта: `BookUtil` в `external/5etools-src/js/bookutils.js:417–445` вызывает `Renderer.utils.preload.pGetPreloaded`, затем `RendererMarkdown.get().render`. Локальные пробы использовали уже готовые payloads либо исходные небольшие книжные поддеревья, не запускали native загрузку всего корпуса и не считаются полной копией браузерного экспорта.

Выполнены пробы scaled-тегов, шести spell cards, обзора классов, Barbarian features, исходного Explosives и пяти facilities. Использованы реальные методы `Renderer.parseScaleDice`, `Renderer.stripTags`, `_renderEntriesSubtypes`, `RendererMarkdown.spell.getCompactRenderedString` и facility adapter. Upstream подтверждает оформление и grammar, но не служит абсолютным эталоном полноты или принадлежности материалов выбранной книге.

## 1. Числовые правила scaled-тегов

В активных представлениях найдено 70 употреблений в 68 заклинаниях XPHB: 64 `scaledamage`, 6 `scaledice`, все с тремя аргументами. **63 значения в 61 заклинании неверны**; семь совпадают с правильными, поскольку base равен increment. Для каждого из 70 случаев результаты настоящих upstream `stripTags`, Markdown renderer и `parseScaleDice` сопоставлены с исходным тегом. Затем полное текущее предложение найдено именно в разделе соответствующего заклинания.

| Заклинание | Исходный тег | Сейчас | Upstream display |
| --- | --- | --- | --- |
| Fireball | `{@scaledamage 8d6\|3-9\|1d6}` | 8d6 | 1d6 |
| Burning Hands | `{@scaledamage 3d6\|1-9\|1d6}` | 3d6 | 1d6 |
| Lightning Bolt | `{@scaledamage 8d6\|3-9\|1d6}` | 8d6 | 1d6 |
| Thunderwave | `{@scaledamage 2d8\|1-9\|1d8}` | 2d8 | 1d8 |
| Heal | `{@scaledice 70\|6-9\|10}` | 70 | 10 |
| Cure Wounds | `{@scaledice 2d8\|1-9\|2d8}` | 2d8 | 2d8 |
| Healing Word | `{@scaledice 2d4\|1-9\|2d4}` | 2d4 | 2d4 |

Fireball находится в resolved `/chapters/7/content/entries/10/entries/14/data`. Его текущий текст: `The damage increases by 8d6 for each spell slot level above 3.` Upstream отображает в этом предложении `1d6`.

Причина: `rendering/inline.py:131–137`, `InlineRenderer.tag`, объединяет обычные dice и scaled tags. Для scaled выбирается четвёртый аргумент, а при его отсутствии первый. Комментарий в этой ветке также неверно описывает grammar. Фактический контракт `js/render.js:3020–3063,6040–6044`:

```text
baseRoll | progression | addPerProgress | renderMode | displayText
```

Печатается пятый аргумент либо increment, а base сохраняется для интерактивного броска. Четвёртый аргумент — режим, например `psi`. Во всём upstream найдены 197 употреблений в 11 JSON-файлах: 164 с тремя аргументами, 32 с четырьмя (`psi`), одно с пятью (`psi` и display text, renderdemo). Встречаются составные base rolls с `;` и числовой прирост. Текущий Python renderer печатает `psi` вместо increment или display text для таких четырёх-/пятиаргументных проб.

`external/5etools-src/test/test-tags.js:199–225` дополнительно проверяет 3–5 аргументов, диапазон уровней 1–9 с минимум двумя значениями и допустимый mode. Текущий обработчик не диагностирует недостаточные аргументы, неверную progression и неизвестный mode. Будущее исправление должно разделить grammar и display, сохраняя действующее поведение обычных dice/damage и summon formulas.

## 2. Spell Access как ошибочный книжный текст

Во всех 391 spell payload текущий renderer печатает `Spell Lists and Subclass Access`. Также напечатаны 168 строк Species Access, 131 Background Access, 367 Feat Access, 79 Feature Access и 90 Reward Access: всего 1226 строк справочных индексов.

Причина: `Payloads.spell`, `rendering/payloads.py:754–763`, передаёт эти поля универсальному `Values.structure` (`values.py:257`). Вложенные словари превращаются в `Name`, `Base Source`, `Sub Subclass` и другие каталожные labels. Это не исходный авторский текст заклинания: `DataUtil.spell._mutEntity` (`js/utils.js:6757–6773`) дополняет payload глобальным generated source lookup. В проверенных сырых записях Fireball, Burning Hands, Cure Wounds и Heal поле `classes` отсутствует.

Штатный spell renderer (`js/render-markdown.js:1446–1449`) выводит компактный `fromClassList`; для Fireball получено `**Classes:** Sorcerer, Wizard`. Однако копирование этой функции недостаточно: в 79 spells среди основных классов есть Artificer из EFA. Все main-class stubs текущего корпуса содержат `name/source`: 987 XPHB и 79 EFA. Например, native compact Cure Wounds включает Artificer вместе с пятью классами PHB. `Parser.spClassesToCurrentAndLegacy` (`js/parser.js:2658`) исключает лишь две старые UA-версии Artificer, не фильтрует по выбранной книге/редакции. Нужна отдельная проверка source/identity в книжном контексте; настоящие prerequisites и granted/additional spells остаются механикой.

## 3. Заголовки и inline labels

`Entries.label` (`entries.py:63–74`) делает heading при `structural=True` до H6. `Entries._node` (`entries.py:132–172`) направляет туда именованные `section`, `entries` и другие блоки без различения краткого обзора, feature rule и самостоятельного подраздела. Контекст анонимных обёрток не задаёт семантику label. В результате каждый из 12 классов имеет heading в кратком обзоре и второй heading у полного описания; правила Damage Resistance/Rage Damage внутри Rage также становятся отдельными разделами.

В реальной upstream-пробе обзора все 12 имён — `***Class.***` labels, единственный heading — глава. В пробе Barbarian `Level 1: Rage` остаётся heading, а `***Damage Resistance.***`, `***Rage Damage.***` и остальные внутренние правила — labels. `_renderEntriesSubtypes` (`js/render-markdown.js:39–67`) учитывает `meta.depth`, включая анонимные containers. Его числовой порог нельзя перенести в нашу иерархию без проверки: классы, подклассы, разновидности монстров и настоящие глубокие разделы должны сохранять headings.

Arcane Study Charm/Craft Options внутри facility также требуют контекстного оформления. Сам upstream в этой пробе создаёт для них headings, поэтому здесь он не доказывает окончательную семантику; требование inline labels задаёт ТЗ.

## 4. Domain placement и необходимость печати

`Domain.__init__/_source` индексирует parent/anchor; `Engine.after_source` (`engine.py:479`) и `extra_children` (`:220`) передают компоненты в `supplement` (`:388`). Проверки существующего представления есть для definitions, loot, deck/card и shared fluff. Для обычных item и reward общий fallback (`:455–474`) вызывает `native` без доказательства, что книжное содержимое отсутствует. Доказанное placement ошибочно становится достаточным основанием новой печати.

`Domain.audit` (`domain.py:232–252`) требует решения по каждому компоненту, а не отдельного напечатанного раздела. Этот контракт корректен. Текущие решения для всех 2531 компонентов:

| Книга | rendered | rendered_in_parent | metadata_only | already_represented | template_expanded | native_derivation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| XPHB | 351 | 741 | 188 | 7 | 0 | 0 |
| XDMG | 308 | 132 | 355 | 54 | 7 | 6 |
| XMM | 376 | 3 | 1 | 2 | 0 | 0 |

### Explosives

Книжное поддерево `data/book/book-xdmg.json`, source pointer `/bookData/0/data/2/entries/14/entries/3`, содержит таблицу из семи строк и следующие за ней правила Bomb, Dynamite, Grenades/Launcher, Fragmentation, Smoke и Gunpowder. Текущий renderer добавляет после таблицы все семь каталожных карточек по `defining_table_reference`, затем печатает книжные правила. Native upstream-проба этого поддерева показывает таблицу и книжные правила.

Bomb action paragraph встречается дважды. Общий grenade-launch paragraph — четырежды; fragmentation damage и smoke effect — дважды. Для Bomb и grenade правил подтверждено точное совпадение отображаемых абзацев; cost/weight имеются в таблице. Например, Bomb: 100 GP = native value 10000 CP, вес 1 lb. Покрытие prose не заменяет проверки остальных игровых полей.

У Dynamite первая фраза карточки — исходное `An an action`, а в книге `As an action`; два остальных абзаца совпадают и повторены. У Gunpowder карточки horn/keg специализируют общее книжное правило с двумя ветвями: radius 10 ft., DC 12, 10 (3d6) либо 24 (7d6) Fire damage. Это не структурно одинаковые тексты. Перед исключением карточек нужна проверяемая проекция текста и полей либо диагностика неоднозначности; fuzzy dedup и исправление upstream typo недопустимы.

Отношение `defining_table_reference` имеют 219 компонентов XPHB и 275 XDMG. Это не число лишних карточек: другие компоненты действительно дополняют таблицы отсутствующими описаниями. Массовое отключение relation потеряет материал.

### Facilities и rewards

Все пять `facility_reward` компонентов повторяют отображаемый абзац внутри родительской facility: Arcane Study/Identify, Observatory/Contact Other Plane, Reliquary/Greater Restoration, Sanctuary/Healing Word, Sanctum/Heal. Каждый соответствующий эффект сейчас напечатан дважды. Facility уже содержит условие Long Rest, длительность 7 дней/до использования, запрет повторного получения и условия применения spell. Reward дополнительно печатает `Additional Spells`, `Related Facilities`, `Type` и тот же эффект.

Source facility wrappers расположены в `/bookData/0/data/7/entries/10/entries/{3,16,18,20,21}`. Native-пробы всех пяти facilities показывают эффект один раз. Для будущего `already_represented` необходимо доказать покрытие не только entries, но и `additionalSpells` (в текущих payloads innate, одно применение), типа и остальных существенных полей. Изменённое spell/число применений нельзя пропустить по одному совпадению абзаца или relation.

### Каталожные language records в MM appendix

Bullywug и Gnoll внутри Monster Conversions оказались `language` components, привязанными к **creature** links таблицы. В payload только name/source/page, `typicalSpeakers`, `__prop`, без rules entries. Anchor находится на page 374, source pointers заканчиваются на `/entries/2/entries/1/rows/{6,23}/0`. Происхождение карточек: `data/languages.json /language/{15,74}`, pages 64/141. Fallback создаёт из каталожных сведений самостоятельные книжные разделы и вносит эти страницы в appendix. Здесь нужно классифицировать роль metadata по payload, typed reference и placement, не менять assembler.

## 5. Печатные страницы: leaf evidence и агрегация

`Domain.page` (`domain.py:186–193`) считает `data_origin` достаточным evidence, если совпадает source и attribution равна explicit. `Engine.native` (`:144–168`) использует это перед placement fallback. Совпадение книги карточки не доказывает страницу её текущего включения. `Entries._node` также принимает `node.page` именованного обзора за его физическое место. `Document.finish` (`document.py:78–100`) объединяет все дочерние pages без классификации их роли. Неверные leaf pages поэтому загрязняют ancestors; исправления только min/max родителя недостаточно.

| Раздел | Текущая карта | Границы подтверждённых собственных книжных узлов |
| --- | --- | --- |
| PHB Chapter 1 | [7,376] | [7,31] |
| PHB Exploration | [19,376] | [19,22] |
| PHB Conditions | [29,376] | [29,31] |
| MM Monster Lists | [64,382] | [374,382] |
| MM Monster Conversions | [64,374] | [374] |

Все ориентиры ТЗ подтверждены входным деревом. Собственные source roots: PHB `/bookData/0/data/1`, его `/entries/15` и `/entries/18`; MM `/bookData/0/data/3` и его `/entries/2`. Например, Burning в PHB Hazards получает page 362 из карточки, хотя его placement origin наследует начало книжного Hazards на page 20. Обзор Barbarian получает `[50]/explicit`, но page 50 относится к полному классу; точная страница краткого обзора этим полем не подтверждена.

Просмотрены все 6001 записи. Screening по соседним началам глав выделил 96 пересечений границ. Для **95 записей** подтверждены цепочки внесения каталожных страниц: 87 PHB, 4 DMG, 4 MM, включая leaf и ancestor records. Они происходят из 34 событий добавления неверного evidence: 31 PHB, 1 DMG, 2 MM. Ещё один кандидат — собственный source inset на page 4 в начале MM с chapter page 5 — является особенностью исходного дерева, не ошибкой экспортёра. Границы соседних глав служат сигналом для проверки, не правилом удаления pages. Эти 95 — нижняя граница подтверждённых ошибок, не доказательство правильности остальных 5906 records.

Дополнительные подтверждённые причины: PHB class chapter расширяется до `[49,221]` из-за 11 каталожных musical instruments у Bard; DMG Creating Adventures расширяется до `[105,138]` из-за hoard `Challenge 11-16`, origin page 138 при anchor page 120. Источник страниц нужно классифицировать и в пределах одной книги, не только отбрасывать cross-book origin. Данных для точной страницы каждого фрагмента нет; допустимы достоверный partial, inherited start или unknown.

Ветки `Entries._node` для unnamed/suppressed names и insets (`entries.py:166,205–208`) также передают page без source guard. Подтверждённого cross-book сбоя в этих ветках текущий корпус не дал; это отдельный риск для отрицательного fixture, а не ещё одна заявленная воспроизведённая ошибка.

## 6. Все повторяющиеся полные heading paths

Подтверждены 22 группы, в каждой ровно две записи (44 occurrences):

| Книга и контекст | Последние имена пути | Классификация |
| --- | --- | --- |
| XPHB / Character Classes | Barbarian, Bard, Cleric, Druid, Fighter, Monk, Paladin, Ranger, Rogue, Sorcerer, Warlock, Wizard | 12 ложных overview headings + 12 полных классов |
| XDMG / Explosives | Bomb, Dynamite Stick, Fragmentation Grenade, Smoke Grenade | 4 пары: каталог + книжное правило |
| XDMG / соответствующая facility | Arcane Study Charm, Observatory Charm, Reliquary Charm, Sanctuary Charm, Sanctum Charm | 5 пар: facility text + reward |
| XMM / Gray Oozes | Gray Ooze | 2 настоящих исходных появления |

Gunpowder и Grenade Launcher показывают, что лишний текст возможен и при уникальном heading path. Принудительная уникальность не исправит выбор содержимого. Две Gray Ooze должны остаться; Psychic Gray Ooze — отдельное необходимое domain supplement, отсутствующее в исходных statblock slots.

## 7. Что обнаруживают и пропускают текущие тесты

`unit/rendering/test_inline.py:14` содержит единственный scaled case: base равен increment, а четвёртый аргумент ошибочно задан как display tag. Тест закрепляет неправильную grammar. Spell test в `test_payloads.py:84–123` проверяет другую модель `scalingLevelDice`, classes — только по подстроке Bard. Формулы полного корпуса (`integration/test_corpus.py:115–169`) относятся к dice/damage у monsters, не к scaling spells. Literal fragments вне tags не проверяют значения внутри tags.

Структурные tests проверяют соответствие headings и карты, но не различают overview/inline rule/section. Page tests покрывают форму attribution, агрегацию и cross-book Ape, но не same-book origin вне текущего placement и navigation target pages. Corpus component test (`test_corpus.py:84–110`) разрешает разные решения и требует reason/parent, не проверяя содержательную необходимость каждого `rendered`. Это не тест требования печатать каждую сущность.

Существующие graph/shared/deck/definition, source occurrence, механические и publication fault tests полезны. Новые проверки должны добавить независимые числовые spell oracles, source-aware compact classes, смысловые labels, покрытие item prose+table fields и facility reward fields, неоднозначность и классификацию page evidence. Глобальная дедупликация не является заменой.

Положительные baseline-регрессии повторно подтверждают 12 классов, все 48 подклассов, Barbarian progression/Frenzy, Agonizing Blast prerequisites, Summon Aberration, Blue Dragons/Kobolds с individual lore и statblocks, две исходные Gray Ooze и одну Psychic Gray Ooze. Их сохранность обязательна при дальнейших исправлениях.

## Проверочные команды и материалы

Команда запуска полного набора проверок через uv из корня `lab2`; результаты baseline выше относятся к исходному состоянию экспортёра до исправлений:

```bash
resolved_build=data/resolved/5etools/8790755429c346d20020eed7826d312d484c393f/60d007f6a1c747e87aebb75bdb340996700e7e95e9af3ab8adb75b79413f3c81
audit_dir=/tmp/dnd-markdown-corrections-audit
PYTHONDONTWRITEBYTECODE=1 uv run --group test python -m pytest \
  tests/ingestion/markdown_export -q --tb=short --input-build "$resolved_build" \
  -o cache_dir="$audit_dir/pytest-cache" --basetemp "$audit_dir/pytest" \
  --junitxml "$audit_dir/baseline-tests.xml"
```

В `/tmp/dnd-markdown-corrections-audit/` сохранены baseline fingerprints, JUnit, проверка входов, результаты двух CLI exports и независимого повторного сравнения. В `tags/`, `domain/`, `structure/` находятся локальные probe scripts, результаты настоящего upstream renderer, JSON pointers, полный список числовых расхождений, 2531 component decisions, 22 повторных пути и трассировка page evidence. Эти диагностические материалы не являются новым форматом данных, не нужны экспортёру и не размещены в проекте.

Проверка fingerprint охватывает существующие 150 файлов основного проекта, включая входы, выходы, exporter/tests и assembler; отдельно проверяются HEAD и Git status submodule. Эти fingerprints служат исходной точкой контроля последующих исправлений; состояние текущей реализации описано в документации экспортёра и проверке результата.
