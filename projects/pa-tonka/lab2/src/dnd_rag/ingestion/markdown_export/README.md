# Markdown export

Самостоятельный экспорт трёх готовых resolved-книг XPHB/XDMG/XMM в английский Markdown и общую карту разделов. Нужна стандартная библиотека Python ≥3.13. Экспортёр читает только manifest и три JSON выбранного build; Node, checkout 5e.tools, сеть, PDF/OCR и промежуточные выгрузки не используются.

## CLI

Из корня `lab2` через uv:

```bash
uv run python -m dnd_rag.ingestion.markdown_export --help

resolved_build=data/resolved/5etools/c3d53956346388b222aaaaf4637776f563e201b8/60d007f6a1c747e87aebb75bdb340996700e7e95e9af3ab8adb75b79413f3c81
uv run python -m dnd_rag.ingestion.markdown_export \
  --input-build "$resolved_build" \
  --output-dir data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8
```

uv подготавливает окружение проекта и устанавливает пакет по `pyproject.toml`; `PYTHONPATH`, ручная активация virtualenv и предварительный `uv sync` не нужны. `--input-build` обязателен; автоматического поиска сборки нет. Без `--output-dir` используется `data/markdown/5etools/<checkout_sha>` относительно рабочего каталога. Все книги экспортируются в порядке manifest. В output находятся ровно:

```text
xphb.md
xdmg.md
xmm.md
source_map.jsonl
```

Повтор без `--force` завершается `OUTPUT_EXISTS`, сохраняя байты и mtime файлов. Для повторной генерации добавьте `--force` к той же команде. Он заменяет существующие файлы экспортёра, включая повреждённый/неполный набор, и не пересобирает входы. Посторонние файлы, вложенные каталоги и symlinks отклоняются. Input, его родители/потомки, исходники пакета, `external` и текущий рабочий каталог процесса не могут быть output.

Код возврата: `0` — публикация, `1` — ошибка входов/рендера/публикации, `2` — аргументы, `130` — прерывание. Ошибки с контекстом и сообщения о таблицах, неизвестных страницах или оставшихся временных путях печатаются в stderr. Информационные сообщения не меняют успешный код возврата.

## API

Скрипт с вызовами API запускается как `uv run python path/to/script.py` из корня проекта.

```python
from pathlib import Path
from dnd_rag.ingestion.markdown_export import render_build, export_build

corpus = render_build(Path('/explicit/resolved/build'))
assert set(corpus.files) == {'xphb.md', 'xdmg.md', 'xmm.md', 'source_map.jsonl'}

# Запись с теми же проверками и правилами, что у CLI:
result = export_build(Path('/explicit/resolved/build'), Path('/explicit/output'), force=True)
print(result.status, result.output_dir)
```

`read_build(directory)` возвращает JSON-объекты в порядке manifest. Проверяются manifest 2.0.0, schema 1.0.0, успешный статус, набор книг, ID/snapshot, размеры и SHA-256 файлов. Пути книг относительны выбранному build и не выходят за него; manifest — обычный файл. Duplicate keys, нечисловые константы, бесконечности, невалидный UTF-8 и непарные Unicode surrogates отклоняются. Конкретные upstream SHA и resolver version не определяют совместимость.

`render_book(book)` возвращает `RenderedBook`: Markdown с YAML, отдельный body, source map и диагностику. `render_build(directory)` возвращает `RenderedCorpus`: книги и словарь четырёх UTF-8 файлов без записи на диск. `export_build(input_build, output_dir=None, force=False)` возвращает `PublishedCorpus`: output path, `created`/`replaced`, corpus и предупреждения очистки. Ошибки имеют тип `ExportError`, код и доступный контекст книги/раздела/источника.

## Устройство

```text
markdown_export/
├── __init__.py              # публичный API
├── __main__.py              # аргументы CLI и диагностика
├── api.py                   # render_book/render_build
├── common/
│   ├── model.py             # результаты, ошибки, diagnostics, constants, pointers
│   └── json_io.py           # строгий UTF-8 JSON
├── rendering/
│   ├── engine.py            # обход книги, canonical placement, групповой lore
│   ├── domain.py            # source/identity/relationship indices и аудит охвата
│   ├── pages.py             # книжные позиции, native origins и page context
│   ├── representation.py    # локальная эквивалентность и покрытие игрового текста
│   ├── selection.py         # книжное покрытие и недостающие поля item/reward
│   ├── document.py          # Markdown-body и координаты headings одним проходом
│   ├── entries.py           # AST, списки, таблицы, quotes/insets
│   ├── inline.py            # вложенная грамматика tags
│   ├── payloads.py          # typed adapters игровых семейств
│   └── values.py            # prerequisites, choices, speeds и другие значения
└── publication/
    ├── inputs.py            # manifest и три готовых входа
    ├── validation.py        # проверка четырёх выходов
    └── store.py             # staging, lock, directory replacement, rollback
```

`api.py` объединяет чтение и рендеринг; `publication/store.py` добавляет запись. `rendering` не обращается к файловой системе. Общий интерфейс renderer передаётся AST и typed adapters, поэтому оформление entries и игровых полей согласовано без отдельной иерархии классов для каждого prop. Обход видимых узлов для проверки покрытия находится в `representation.py`; строки и leaf headers таблиц используют одну обработку spans в `entries.py`.

Все части проходят в книжном порядке, включая текст приложений и credits. Исходные повторные вставки сохраняются; book_insertion не печатается повторно из domain. Дополнения размещаются по canonical parent/anchor и relationships. Features сопоставляются по typed identity с class/source/level. Общий fluff подавляется только по проверенным shared paths. Локальные доказательства эквивалентности сохраняют числовые значения, порядок, повторы и структуру; проекции колод/treasure проверяют соответствия строк в родительской таблице. Глобальной дедупликации по именам или тексту нет.

Книжное дерево задаёт основной текст. `selection.py` проверяет дополнительный item/reward перед форматированием: typed anchor и его локальный владелец, упорядоченные entries, свойства таблицы/именованного списка и структурированные поля. Полное покрытие даёт `already_represented`; при частичном покрытии печатаются только недостающие поля/entries. Самостоятельные дочерние компоненты сохраняются и при подавлении каталожного родителя. Таблица, отсутствующая в исходном разделе, следует после его книжного введения.

Именованные списки допускают проверяемую проекцию полных строк с `entry` или одноэлементным `entries`; дополнительные строки источника остаются на месте. Общие type-расширения items требуют подтверждённой связи и полного текста в окружающем книжном разделе. Варианты контейнера проверяются по целому правилу с явно подписанными alternatives. Для facility/reward независимо проверяются текст, тип награды, parent reference, typed spell identity и одно использование. Каталожный индекс `typicalSpeakers` у creature-placement относится к metadata; настоящие language rules и языки statblocks сохраняются.

`source_preferred` отмечает расхождение дополнительного item-каталога с книжным полем или вводной clause. Сохраняется книжное значение, а `DOMAIN_SOURCE_CONFLICT` содержит обе версии; это решение не утверждает их эквивалентность. Поля без доказанного покрытия остаются дополнениями. Неоднозначные владельцы, строки, порядок или кратность дают `AMBIGUOUS_DOMAIN_COVERAGE`. Diagnostics содержат coverage, remaining fields и source anchor; постоянный промежуточный формат не создаётся.

Однотипный bundle может покрывать отдельный item: требуются явный typed UID, положительное количество в напечатанном Contents, полностью совпадающие представленные правила и пропорциональные книжные Weight/Price. Неподтверждённые unit fields остаются дополнением.

Inline features сохраняют дополнительные исходные абзацы и дополняются недостающими игровыми полями канонического компонента. Его текст должен присутствовать в inline view в исходном порядке; конфликт полей или неполный текст останавливает экспорт. Проверка известных payload fields выполняется также для компонентов, покрытых shared lore или готовой template/derivation.

Роль именованного блока определяется entry context, отдельно от Markdown level. Безымянные `entries` увеличивают вложенность; внутри обзоров и игровых rules именованные подпункты получают `***Label.***`. Явные `section` открывают новый структурный контекст на любой глубине; typed class/subclass/feature/monster сохраняют свои headings. Labels присоединяются к первому текстовому абзацу, а перед списком, таблицей или source-anchor supplementation печатаются отдельно. Поля, source traversal и размещение domain content от этого не меняются.

Scaled-теги разбираются отдельно от обычных dice/damage: `base | progression | increment | mode | display`. Печатается display либо increment; mode может отсутствовать или быть `psi`. Проверяются число аргументов и progression из минимум двух уровней в диапазоне 1–9. Вложенные display tags сохраняют обычное оформление. Некорректная grammar даёт `INVALID_SCALED_TAG`.

У spells выводится компактный `Classes` из основных `fromClassList` identities, присутствующих среди классов книги. Если книга не содержит class payloads, изолированная карточка использует классы с source самого заклинания. `definedInSource` ограничивает дополнения источником выбранной книги. Subclass/variant access и обратные индексы feats/species/backgrounds/rewards/features относятся к каталожным metadata; настоящие игровые entries, prerequisites и additional spells в class/feature payloads сохраняются.

Каждый domain component получает явное решение: `rendered`, `rendered_in_parent`, `already_represented`, `metadata_only`, `source_preferred`, `template_expanded` или `native_derivation`. Неучтённое содержимое, неизвестные types/fields/tags останавливают экспорт. Изображения и технический provenance не становятся текстом. Правила оформления и примеры описаны в [MARKDOWN_REPRESENTATION](../../../../docs/ingestion/MARKDOWN_REPRESENTATION.md).

## Source map

Одна запись соответствует одному структурному heading. Название книги находится в единственном YAML front matter; H1 обозначает главу/самостоятельную часть. Статблок монстра — blockquote внутри раздела; Traits/Actions/HP и имена атак оформлены жирными labels и не создают записей карты.

**Координаты относятся к Markdown-body без YAML и разделительной пустой строки.** Строки — 1-based inclusive, с разделителем только LF (`\n`). Символы — 0-based Unicode code points, полуоткрытый `[start_char,end_char)`, включая конечный LF. Unicode U+2028/U+2029/U+0085 не добавляют строки в этом контракте. Родитель охватывает детей; раздел заканчивается у следующего heading того же/меньшего уровня либо в конце body. Совпадающие названия различайте по файлу и координатам.

Пример чтения опубликованных файлов стандартной библиотекой:

```python
import json
from pathlib import Path

root = Path('data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8')
record = json.loads((root / 'source_map.jsonl').read_bytes().decode('utf-8').split('\n')[0])
markdown = (root / record['file']).read_bytes().decode('utf-8')
body = markdown.split('\n---\n\n', 1)[1]  # Без strip или нормализации.
fragment = body[record['start_char']:record['end_char']]
lines = [line + '\n' for line in body.split('\n')[:-1]]
assert fragment == ''.join(lines[record['line_start'] - 1:record['line_end']])
```

Страницы — `[p]`, `[start,end]` или `null`. `pages.py` классифицирует evidence до передачи в `Document`. Приоритет имеет собственная страница книжного узла или фактического wrapper placement. Same-book `data_origin` допускается как страница локального определения только при совместимости с книжной позицией, source и однозначным lookup. Используется текущий occurrence, включая повторную вставку той же сущности в другом разделе. Foreign origins и target pages ссылочных подписей не становятся страницами появления.

Ближайшие следующие книжные ориентиры и совместимые native siblings ограничивают контекст проверки origin. Эти границы не записываются как предполагаемые страницы конца раздела. Собственные source pages, в том числе inset перед страницей начала главы, не ограничиваются искусственным диапазоном.

| Attribution | Evidence |
| --- | --- |
| `explicit` | Есть подтверждённые собственные позиции, без выявленной неполноты |
| `partial` | Известны позиции только части материала или неизвестно начало heading |
| `inherited_section_start` | Собственной позиции нет; известно начало ближайшего книжного контекста |
| `unknown` | Нет ни собственной позиции, ни подтверждённого начала |

Начало контекста хранится отдельно от накопленных страниц. Ancestors объединяют только подтверждённые собственные points; inherited fallback не превращается в explicit evidence. Compact lists, quotes и table cells передают классифицированные points содержащему разделу. Непечатаемые navigation labels и metadata не добавляют своих страниц предыдущему leaf. Подразделы, созданные adapter из полей группы, не получают автоматически точную страницу всей каталожной группы.

Карта указывает подтверждённые позиции и не восстанавливает полную постраничную вёрстку. Примеры и ограничения входных свидетельств приведены в [проверке результата](../../../../docs/ingestion/MARKDOWN_EXPORT_VALIDATION.md).

## Публикация и проверка

До записи проверяются UTF-8/LF, книжные метаданные, отсутствие активной разметки и служебных артефактов, все headings/maps, полные body-relative диапазоны, вложенность, страницы и JSONL order. Renderer проверяет все исходные вставки и domain components. Четыре файла записываются в соседний temporary directory, синхронизируются и повторно проверяются с диска.

При замене старый каталог переносится в соседний backup, затем готовый каталог переименовывается в output. Ошибка до commit восстанавливает backup. Соседний `.имя.export.lock` исключает одновременных writers. После штатного завершения stage/backup/lock удаляются. При неудачной очистке сообщения сохраняют пути и при основном исключении. `ROLLBACK_FAILED` указывает на сохранённый исходный backup; прерывание после уже выполненного commit явно сообщает, что новый валидный корпус опубликован.

Между двумя переименованиями output короткое время отсутствует; читатель может повторить открытие. Схема переносима и не обещает crash-atomicity при потере питания/kill -9. При оставшихся backup/lock сначала проверьте отсутствие работающего экспортёра и сохранность корпуса, восстановите backup при необходимости, затем удалите оставшиеся lock/stage. Чужой или stale lock автоматически не удаляется.

[Автотесты](../../../../tests/ingestion/markdown_export/README.md) используют независимые CommonMark/GFM и YAML parsers, synthetic fixtures, реальные resolved книги, fault injection и отдельные процессы. JUnit можно сохранить явной опцией `--junitxml /tmp/dnd-markdown-tests.xml`; постоянных отчётов экспортёр не создаёт. Числа, примеры и ограничения проверенного корпуса приведены в [проверке результата](../../../../docs/ingestion/MARKDOWN_EXPORT_VALIDATION.md).

Стиль Python и проверки импортов задаёт Ruff в `pyproject.toml`: 100 символов на строку и одинарные кавычки. Его область ограничена экспортёром и его тестами; это инструмент разработки из группы `lint`, без runtime-зависимости. [Команды проверки](../../../../tests/ingestion/markdown_export/README.md) приведены рядом с командами тестов.
