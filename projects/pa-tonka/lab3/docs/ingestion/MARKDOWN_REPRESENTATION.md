# Представление книг в Markdown

[Экспортёр](../../src/dnd_rag/ingestion/markdown_export/README.md) создаёт по одному полному английскому Markdown на XPHB/XDMG/XMM и общий `source_map.jsonl`. Источник текста и механики — выбранный resolved build. Его исходные повторы сохраняются; изображения, OCR, raw recipes и технические metadata не выводятся.

Готовые файлы проверенного snapshot:

- [XPHB](../../data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8/xphb.md): Barbarian/subclasses, spells/summons, prerequisites, glossary и приложения.
- [XDMG](../../data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8/xdmg.md): items, Bastions, lore, tables/insets и текст Appendices B/C.
- [XMM](../../data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8/xmm.md): общие и индивидуальные описания, полные statblocks, lairs/regional effects.
- [Source map](../../data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8/source_map.jsonl): структурные headings всех трёх книг.

Команды создания файлов приведены в README экспортёра. Фактические числа, фрагменты готового Markdown и результаты проверок — в [MARKDOWN_EXPORT_VALIDATION](MARKDOWN_EXPORT_VALIDATION.md).

## Иерархия и книжное размещение

Название книги хранится в единственном YAML front matter. H1 обозначает главу, введение, приложение или другую самостоятельную часть. H2 и следующие уровни соответствуют реальным именованным подразделам. Название wrapper/card не создаёт второй одноимённый heading поверх существующего логического раздела.

Глубина `entries` считается отдельно от уровня Markdown и включает безымянные контейнеры. Первые два уровня обычных книжных `entries` могут задавать подразделы; более вложенные именованные пункты оформляются `***Label.***` перед своим текстом. Явный `section` всегда сохраняет структурную роль и начинает новый контекст вложенности, поэтому настоящий глубокий раздел не теряет heading. Типизированные классы, подклассы, features и разновидности монстров также сохраняют самостоятельные заголовки.

Тела игровых payloads (spells, features, facilities, items и других rules) начинаются в контексте подпунктов: внутреннее имя само по себе не создаёт раздел. Lore сохраняет книжную структуру. Явные `inline/inlineBlock` используют labels. Если первым элементом после подписи идёт таблица, список, prerequisite или дополнение по source anchor, подпись занимает отдельный абзац перед этим блоком; порядок и содержимое сохраняются. Inline labels не создают записей source map.

Исходные embedded_entity остаются в своих местах. Domain components добавляются у canonical parent/anchor; book_insertion из реестра повторно не печатается. Native features сопоставляются по типизированной identity, включая class/source/level. Общий fluff подавляется только по проверенным shared paths. Прочие повторные представления требуют локального доказательства полной структурной эквивалентности или соответствия roll/result в родительской таблице. Имена, числовые значения, порядок и принадлежность правил конкретному объекту сохраняются.

Наличие canonical placement задаёт место дополнения, но не обязанность печатать его полной карточкой. Для items проверяются собственные книжные entries, полные строки именованных списков и поля defining table; source-labelled item reference должен совпадать с identity карточки. Стоимость сопоставляется в CP с учётом валюты, вес — как точная дробь с сохранением qualifier, например `(full)`. Display alias и книжная цена в подписи помогают найти владельца, но не заменяют проверку его текста и свойств.

Покрытые entries/поля не повторяются; непокрытые остаются компактным дополнением. Нужные дочерние сущности сохраняются под ближайшим структурным разделом. Общий type-wrapper требует явной item-type связи и полного текста в окружающем книжном разделе. Дополнительная таблица Trinket следует после исходного введения. Для подписанных вариантов контейнера сравнивается весь текст после выбора явной damage alternative и замены container noun, включая DC, радиус и условия. Fuzzy matching не используется.

Однотипный набор представляет дочерний item только при явном UID/количестве в напечатанном Contents, полностью совпадающих представленных entries и подтверждённых пропорциональных Weight/Price. Дополнительные unit fields сохраняются; имя или похожий текст не доказывают покрытие.

Facility reward не печатается отдельно, если его полная последовательность правил и игровые поля подтверждены в facility. Тип награды, связь с parent и `additionalSpells` проверяются отдельно: один ограниченный use и тот же typed spell должны следовать из книжного текста. Изменённые uses, source, prerequisites или дополнительные правила остаются в выводе. Speaker-only language indexes при creature-placement являются каталожными metadata; язык statblock и реальные самостоятельные language rules сохраняются.

Решения с локальным покрытием содержат `coverage`, `remaining_fields`, `source_anchor` и parent в diagnostics. `source_preferred` сохраняет первичное книжное значение при конфликте вторичного item-каталога; предупреждение `DOMAIN_SOURCE_CONFLICT` хранит обе версии. Совпадение при этом не утверждается. Неоднозначный владелец/строка или нарушенные порядок/кратность останавливают экспорт с `AMBIGUOUS_DOMAIN_COVERAGE`.

У inline feature канонический текст проверяется как упорядоченная подпоследовательность; дополнительные исходные абзацы, например Cost, сохраняются. Отсутствующие игровые поля canonical component добавляются по известной схеме rule payloads. При конфликте значений или неизвестном поле экспорт останавливается с диагностикой. Typed identity сама по себе не доказывает полноту inline view.

Две исходные Gray Ooze в XMM остаются двумя вставками; Psychic Gray Ooze из domain добавляется рядом. Исправлений содержимого upstream по догадке нет.

## Lore и statblocks

Для Blue Dragons/Kobolds используется порядок: общий lore группы → подразделы разновидностей с individual lore и statblock → общие lairs/effects. Habitat берётся из текста fluff: Blue Dragons имеют **Desert**, независимо от taxonomy environment. Одиночный Goristro объединяет описание и характеристики в одном книжном разделе.

Statblock — единый blockquote. В нём сохраняются имя, size/type/alignment, AC/Initiative, HP/Speed, Score/Mod/Save для всех шести abilities, skills, защиты, gear, senses/passive, languages, CR/XP/PB и имеющиеся механические секции. Traits/Actions/Bonus Actions/Reactions/Legendary Actions, spellcasting и имена атак оформлены жирными labels без отдельных source-map headings.

Mod равен `floor((score - 10) / 2)`; Save берётся из явного save, иначе равен Mod. Initiative учитывает DEX, proficiency multiplier, явное значение и advantage/ disadvantage. Если passive отсутствует, используется Perception bonus, затем WIS modifier; формулы сохраняются символически. Например, у исходного Goristro Initiative `+6 (16)`, Perception/Survival `+7`, Passive Perception `17`.

Quotes, insets/readaloud оформляются blockquote с сохранением заголовка, авторства, абзацев и списков. Обычные абзацы не становятся blockquote. Буквальные Markdown символы внутри native prose не создают незапланированных headings.

## Классы, spells и items

Class progression — GFM-таблица с level/PB/features и всеми исходными колонками. Подкласс находится у класса; feature heading включает level. Уже раскрытый в native родителе Frenzy не выводится второй раз через domain. Agonizing Blast сохраняет структурированные prerequisites, включая Warlock level и условие cantrip. В обзоре классов все 12 имён — inline labels; полные описания имеют по одному H2. `Level 1: Rage` сохраняет H3, его Damage Resistance/Rage Damage и другие внутренние правила — labels. Arcane Study Charm и Craft Options внутри описания facility также являются labels, с сохранением эффектов и списков Craft.

Spells содержат casting time с notes/conditions, range, components/cost/consumption, duration, основной и higher-level текст. Summon размещается по связи с заклинанием. Компактный `Classes` содержит основные `fromClassList`, сопоставленные с типизированными именем/source классов этой книги. Если class payloads отсутствуют, используются основные классы с source заклинания. Записи с `definedInSource` учитываются только для источника выбранной книги. Subclass/variant access, feats/species/backgrounds/rewards/features в обратном spell index не являются книжным описанием и не печатаются. Это правило относится только к справочным полям spell adapter; prerequisites и granted/additional spells игровых особенностей сохраняются.

AC/HP и damage formulas не вычисляются для произвольного слота; `summonSpellLevel` становится `the spell's level` с сохранением самой формулы.

Items сохраняют type/rarity, weight, attunement, charges, capacity, защиты и другие игровые поля вне entries. Base AC и AC bonus подписываются раздельно. Описание использует готовое `_fullEntries`, если оно есть: у Black Dragon Scale Mail там находится правило Disadvantage на Dexterity (Stealth). Entries и fullEntries не конкатенируются в повторные описания.

## Таблицы и tags

Таблица представляется GFM, если это сохраняет её содержимое. Сохраняются все строки/столбцы, caption, intro/outro и сноски. Spans в leaf headers и ячейках разворачиваются с сохранением привязки последующих столбцов. Групповые labels выводятся строкой `Column groups` с исходными spans. Если span источника кажется странным, его не исправляют по предполагаемому виду печатной таблицы.

Inline tags разбираются с учётом вложенности и display labels. Dice/DC/hit/attack notation сохраняет игровые значения. Entity references остаются читаемыми именами; spell references оформляются курсивом с учётом внешнего и вложенного выделения. В заголовках и plain-режиме возвращается обычное имя. HTTP(S) links становятся Markdown links. Ссылки не вызывают загрузку других книг или раскрытие дополнительных карточек. Неизвестные types/fields/tags завершаются ошибкой с контекстом, вместо молчаливого удаления содержимого.

Для `scaledice/scaledamage` используется grammar `baseRoll | progression | addPerProgress | renderMode | displayText`. Печатается пятый аргумент, если он непустой, иначе величина прироста. Базовый бросок не подменяет прирост: Fireball печатает `1d6`, Heal — `10`. Четвёртый аргумент — необязательный mode `psi`; он не становится текстом книги. Допустимы 3–5 аргументов, числовые и dice increments, составные base rolls, comma/range progression из минимум двух различных уровней 1–9 и вложенные display tags. Некорректные арность, progression, пустые обязательные аргументы и неизвестный mode завершаются `INVALID_SCALED_TAG` с контекстом раздела. Обычные dice/damage и символические summon formulas сохраняют свои правила.

## Карта разделов

На каждый структурный heading создаётся одна запись одновременно с текстом. Координаты относятся **только к Markdown-body без YAML и разделительной пустой строки**: строки 1-based inclusive по LF, символы — Unicode indices `[start,end)`. Конечный LF входит в диапазон. Раздел заканчивается у следующего heading того же/меньшего уровня либо в конце body; parent охватывает детей.

Реальная запись полного XMM:

```json
{"book_id":"XMM","file":"xmm.md","heading_path":["Monsters A to Z","Blue Dragons","Young Blue Dragon"],"line_start":3589,"line_end":3628,"start_char":145073,"end_char":146399,"printed_pages":[48],"page_attribution":"partial"}
```

`partial` означает, что известна страница statblock, а страница individual lore неизвестна. Для PHB Ape используется placement PHB `[346] / inherited_section_start`; страница XMM origin не становится страницей PHB. Если источника номера нет, используется `null / unknown`, без вымышленной точности.

Source-map evidence относится к физическому месту в экспортируемой книге. Собственные страницы исходного узла или wrapper placement имеют приоритет. Native origin той же книги используется только для локального определения: проверяются source, отсутствие неоднозначного lookup и совместимость с текущим книжным контекстом. Следующие source landmarks и совместимые native siblings задают ограничения проверки; из них не вычисляются вымышленные end pages. Для каждого original occurrence используется его фактический placement.

Полностью ссылочные имена наподобие `{@class Barbarian|XPHB}` не превращают target page в место краткого обзора. Unnamed/suppressed entries, native children, quotes и table cells также проходят source/context checks. Непечатаемые metadata и navigation groups не дают отдельного page point. Собственные книжные страницы не обрезаются по предполагаемым границам главы.

Если собственных points нет, используется подтверждённое начало ближайшего книжного контекста с `inherited_section_start`; при его отсутствии — `unknown`. Наличие только части evidence даёт `partial`, включая неизвестное начало heading при известных дочерних страницах. `explicit` не обещает постраничного покрытия каждого абзаца. У derived subsections, например Lair Actions, нет автоматического explicit page от всей каталожной группы.

Агрегация ancestors объединяет допустимые собственные points и сохраняет признак неполноты. Fallback остаётся отдельным началом раздела и не меняется при добавлении страниц descendants. Поэтому страница inset перед heading не становится началом для следующих неизвестных подразделов. Диапазон — min/max подтверждённых points; унаследованные значения не расширяют его как будто они explicit.

Пример точного чтения диапазонов и описание API находятся в README экспортёра. [Автотесты](../../tests/ingestion/markdown_export/README.md) независимо разбирают YAML и Markdown AST, проверяют полные body-relative ranges, игровую механику, все исходные части/domain decisions и побайтовую воспроизводимость API/CLI. Это проверка относительно resolved snapshot, без постраничного сравнения с PDF и без создания indexing/RAG.
