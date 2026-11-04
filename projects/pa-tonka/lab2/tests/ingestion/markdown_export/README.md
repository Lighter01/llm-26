# Тесты Markdown export

Проверки [публичных API и CLI](../../../src/dnd_rag/ingestion/markdown_export/README.md) работают с готовыми resolved JSON. Сборщик не запускается; входы, `book_assembly` и upstream не изменяются. Fixtures и временные outputs создаются в pytest tmp. Рендер не зависит от сохранённых Markdown, прототипов или отчётов `.cache`.

## Запуск

Python ≥3.13; test dependencies — pytest, markdown-it-py, PyYAML. Production-экспортёр использует только stdlib.

```bash
uv run --group test python -m pytest tests/ingestion/markdown_export/unit
```

Форматирование, импорты и базовые статические проверки:

```bash
uv run --group lint ruff check tests/ingestion/markdown_export
uv run --group lint ruff format --check tests/ingestion/markdown_export
```

uv подготавливает окружение и устанавливает зависимости группы `test` или `lint` при запуске; отдельный `uv sync` и ручная активация virtualenv не нужны. Группа `lint` содержит только Ruff. Настройки в `pyproject.toml` охватывают экспортёр и его тесты; команды выше проверяют только тесты. Для применения форматирования используйте `uv run --group lint ruff format` с теми же путями без `--check`.

Полный прогон требует явную существующую сборку:

```bash
resolved_build=data/resolved/5etools/c3d53956346388b222aaaaf4637776f563e201b8/60d007f6a1c747e87aebb75bdb340996700e7e95e9af3ab8adb75b79413f3c81
uv run --group test python -m pytest tests/ingestion/markdown_export \
  --input-build "$resolved_build" \
  --junitxml /tmp/dnd-markdown-tests.xml
```

Для integration отдельно укажите `tests/ingestion/markdown_export/integration`. Можно также использовать markers `-m integration` / `-m 'not integration'`. Отсутствующий build вызывает ошибку; skip, поиск latest и пересборка не используются.

## Организация

```text
markdown_export/
├── conftest.py              # fixtures и явный --input-build
├── fixtures/                # synthetic examples и два processed spell payloads
├── helpers/
│   ├── fixtures.py          # создание/изменение только synthetic/copied inputs
│   ├── inspection.py        # Markdown/YAML/map и исходные текстовые фрагменты
│   └── runtime.py           # subprocess, snapshots и перенос четырёх входов
├── unit/
│   ├── test_api.py          # публичный API и ошибки book envelope
│   ├── rendering/           # AST/tags/values, mechanics, domain и source map
│   └── publication/         # manifest, validation, store failures и CLI
└── integration/
    ├── test_corpus.py       # все три книги и входные ожидания
    ├── test_regressions.py  # содержательные примеры ТЗ
    ├── test_headings.py     # overview/rule labels и настоящие source sections
    ├── test_selection.py    # книжные правила, table fields и metadata indexes
    ├── test_pages.py        # собственные позиции, origins и source ranges
    ├── test_spells.py       # все scaling sentences и книжные списки классов
    ├── test_reproducibility.py
    └── test_cli.py          # полный CLI: создание, force, сохранность при render failure
```

## Назначение и устойчивость проверок

Набор содержит **172 тестовых функций и 436 сценариев** после параметризации: 359 unit и 77 integration. Параметры описывают разные виды tags, shapes, ошибок чтения, графов размещения и состояний публикации. Они не являются отдельными тестами каждого поля каждой книги.

В unit-тестах маленькие контролируемые fixtures задают независимые примеры преобразований: например, известные Score/Mod/Save, компоненты заклинания или расположение ячеек таблицы. Точные строки и числа здесь проверяют результат рендера и арифметику. Это ожидаемые значения тестового примера, а не утверждения о содержимом произвольной реальной книги.

Интеграционные ожидания берутся из выбранного resolved build: состав вариантов монстров, Initiative/skills, AC/resistances/capacity, текст и число исходных вставок. Для plain prose сравниваются целые абзацы; для tagged prose — буквальные участки вне tags, включая числа и единицы. Семантику самих tags проверяют unit-тесты. Это позволяет независимо проверять сохранность материала без копирования production inline parser в тестовый код.

Scaled-теги имеют отдельные unit cases для base ≠ increment, числового прироста, `psi`, пятого display argument, вложенных tags и malformed grammar. Spell oracle проверяет полные предложения всех исходных scaled употреблений, подставляя display/increment из source grammar без вызова production formatter. Неизвестная форма source sentence останавливает эту проверку и требует расширения инспектора. Именованные регрессии задают независимые числовые ожидания для семи заклинаний. Отдельные проверки ссылок на заклинания охватывают aliases, вложенные italic/bold/link, режим plain и заголовки карты; семь книжных случаев PHB/DMG сравнивают полные исходные абзацы с ожидаемым курсивом. Все spell sections выбираются в контексте исходной главы, включая неоднозначное имя Light. Основные class identities сверяются с классами книги; Access dumps отсутствуют. `fixtures/spells.json` содержит два неизменённых processed payloads Fireball/Cure Wounds выбранного resolved snapshot с реальными обратными индексами; тесты работают с этими локальными копиями без upstream runtime.

Heading fixtures проверяют безымянные контейнеры, независимость entry depth от Markdown level, typed rule labels, настоящие глубокие `section`, sibling context и явные `inline/inlineBlock`. Сохраняются prerequisites, таблицы, списки, пустые тела пунктов, диагностика пустых подписей и порядок canonical content после подписи его anchor. Интеграционные проверки охватывают все class overviews и full class headings, Rage, facilities с Craft Options и все явные source sections трёх книг. Исходные повторные occurrences проверяются отдельно; уникальность путей карты не является обязательным контрактом.

Selection fixtures проверяют полное и частичное покрытие items, сохранность самостоятельных детей, отсутствие заимствования правил другого владельца, source/prop identity, дробный вес и валюты. Однотипный bundle проверяется по UID, полным rules, количеству и Weight/Price; непокрытый вес или дополнительные charges дочернего item сохраняются. Проекции контейнеров проверяют целые правила, включая изменённые DC/радиус/damage; проекции именованных списков сохраняют значения, порядок, style и дополнительные source rows. Неизвестные поля, в том числе внутри type-wrapper, остаются ошибкой. Facility reward проверяется отдельно по prose, типу, parent и spell use; изменённый spell source, число uses, recharge, prerequisite или новый абзац не скрываются за равенством prose. Source/catalog conflicts имеют отдельную диагностику и не считаются эквивалентностью. Ambiguous rows/owners/order и нарушенная кратность проверяются отрицательными fixtures. Интеграция сравнивает полные правила Explosives, все facility rewards и исходную прозу каждой части; speaker-only indexes отделены от настоящих language rules.

Page fixtures разделяют own placement, same-book local definition и reference origin. Проверяются foreign sources в unnamed/suppressed/compact nodes и native children, target pages обзора, два occurrences одной сущности, контекст native siblings, unknown/ambiguous evidence и page 0. Неоднозначная inline карточка не может использовать собственный raw page как inherited fallback. Lists/quotes/table cells сохраняют допустимые points; metadata, images и непечатаемые navigation groups не загрязняют предыдущий leaf. Отдельные document cases проверяют устойчивое начало, partial при неизвестном parent и агрегацию без продвижения inherited значений в explicit. Интеграция проверяет собственные source ranges PHB/DMG/MM, все ранние condition/hazard definitions, все class overviews и class scopes, локальные Fireball/Rage/Young Blue Dragon pages, hoard origin и реальный inset перед страницей начала главы. Source contexts различают одноимённые narrative headings, например Individual Treasure и Treasure Hoards.

Полный corpus test проверяет individual lore перед собственным statblock для всех подходящих сущностей. Представительные group regressions проверяют общее lore, иерархию вариантов и расположение lairs. Требование непустого текста применяется к текстовому glossary; изображения в приложениях не создают такого требования. Приёмочный map inspector имеет собственные негативные проверки, чтобы обнаруживать испорченные диапазоны независимо от production validator.

Проверки API и CLI разделены по контракту: API отвечает за результат/исключения, CLI — за аргументы, default paths, exit codes, stderr и сохранность файлов. Unit-проверки покрывают отказ без force и подробные filesystem failures на маленьких входах. Полный CLI проверяет три состояния реального корпуса: создание → повторный force → сохранение корпуса при ошибке рендера.

| Область | Проверки |
| --- | --- |
| `unit/test_api.py` | Некорректные scope/book/chapters/domain дают ExportError и понятный CLI exit |
| `unit/rendering/test_inline.py` | Nested tags/display labels, formatting, dice/DC/attacks, scaled grammar/increments/modes, курсив spell references и plain context, HTTP, неизвестная грамматика |
| `unit/rendering/test_entries.py` | Вложенные/нумерованные списки, quote/inset, images, table groups/spans/сноски и literal paragraph syntax |
| `unit/rendering/test_payloads.py`, `test_mechanics.py` | Score/Mod/Save/Initiative/Passive, spellcasting/summons, structured spell/item/feat fields, hover/material costs/consumption |
| `unit/rendering/test_domain.py`, `test_representation.py` | Anchors/parents/cycles, shared paths, typed identities, исходные дубли, structural equivalence, полнота inline canonical rules, deck/treasure row mappings |
| `unit/rendering/test_selection.py` | Покрытие item/reward fields, named lists, container variants, недостающие правила/дети, source conflicts и неоднозначность |
| `unit/rendering/test_document.py` | YAML, Unicode/LF, полные line/char ranges, siblings/parents, repeated titles и все page attributions |
| `unit/rendering/test_pages.py` | Own placement vs origin, source namespaces, native context, повторные occurrences, compact evidence, navigation и неопределённость |
| `unit/publication/test_build.py` | Manifest status/version/ID/schema/hash/size, строгий JSON, paths/symlinks и неизменность входов |
| `unit/publication/test_validation.py` | Четыре артефакта, корректный YAML, artifact markers, JSONL, полные map ranges и Unicode separators |
| `unit/publication/test_store.py`, `test_store_failures.py` | Create/force, changed inputs, lock, path ownership, ENOSPC, staged corruption, rename/rollback/cleanup failures, interruption до/после commit |
| `unit/publication/test_cli.py` | Help/default output/аргументы/exit codes, повтор и force, понятная диагностика без traceback |
| `integration/` | Все главы, AST, таблицы, statblocks, damage formulas, domain decisions, регрессии и воспроизводимость API/CLI |
| `integration/test_spells.py` | Все исходные scaling sentences, числовые spell regressions, компактные class lists, отсутствие обратных Access-каталогов и семь абзацев со spell italics |
| `integration/test_headings.py` | Class overview vs full class, Rage/facility inline labels, сохранность явных sections всех книг |
| `integration/test_selection.py` | Тексты/таблица Explosives без каталогов, все Charm effects, исходная проза 29 частей и speaker metadata |
| `integration/test_pages.py` | Книжные ranges, реальные leaf pages, class overview targets, class scopes, distant hoard origin и собственный inset |

Ожидания полного корпуса вычисляются из выбранных входов. Имена из ТЗ — репрезентативные проверки текущего snapshot; количества не зашиты как правила для произвольного будущего upstream. Ожидаемые значения не вычисляются production-форматтерами. Markdown разбирается CommonMark+GFM parser, YAML — PyYAML. Независимый map checker проверяет точные Unicode slices и полные границы каждого раздела с исключённым YAML; строки считаются только по LF.

Проверяются Blue Dragons/Kobolds: common lore → individual lore → full statblock; Goristro, Aarakocra Aeromancer, Aboleth, Adult Black Dragon; обе исходные Gray Ooze и Psychic Gray Ooze; Barbarian/subclasses/Frenzy, Agonizing Blast, Summon Aberration, PHB Ape placement, DMG items/Bastions/Lore Glossary/Appendices B/C. Дополнительно проверяются canonical prerequisites Blessed Warrior/Druidic Warrior, метамагия, individual lore перед statblock по всему корпусу, cast-time notes Plant Growth и special duration Rolling Stone.

Reproducibility запускает API в отдельных процессах с разными hash seeds и путями исходной/перенесённой сборки, копирует только четыре входных файла и сравнивает все выходные байты. CLI проверяется отдельными subprocess-тестами. Audit hook запрещает сеть, открытие upstream/сборщика и запись во входы. Fingerprints входов/кода сборщика и Git state upstream проверяются до/после. Fault injection проверяет сохранность предыдущего валидного корпуса, очистку временных путей, сохранённый backup при неудаче rollback и сообщения о неочищенных путях.

JUnit сохраняет фактические количества chapters/headings/tables, components, statblocks, damage formulas и буквальных исходных table rows. Сложные таблицы проверяются fixtures. Эти проверки не означают постраничное равенство печатным книгам и не обещают crash-atomicity при отключении питания; границы публикации описаны в README модуля.

Поведение дочерних CLI/API процессов проверяется subprocess-тестами. Проверка на копиях книг подтверждает, что корректные изменения значений Initiative/skills, AC и вместимости принимаются, а неверный вывод для тех же входов отклоняется.

Фактические результаты полного прогона, числа и ограничения корпуса приведены в [проверке результата](../../../docs/ingestion/MARKDOWN_EXPORT_VALIDATION.md). JUnit сохраняется только при явном `--junitxml`; прототипы, промежуточные выгрузки и старые отчёты не нужны для запуска тестов. Для проверки без создания Python cache используйте `PYTHONDONTWRITEBYTECODE=1`; pytest cache можно вынести за проект опцией `-o cache_dir=/tmp/dnd-markdown-pytest-cache`.
