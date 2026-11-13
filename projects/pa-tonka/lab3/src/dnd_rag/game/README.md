# Игровые каталоги

`contracts.py` — SourceRef, Monster/MonsterCount, CatalogSnapshot и результаты encounter/loot. Один monster_id используется lookup и encounter-инструментами; SourceRef сохраняет книгу, фактический файл, страницу при наличии и происхождение варианта.

`prepare.py` компилирует JSON snapshot; `prepare_5etools.mjs` использует существующий guarded `openUpstreamRuntime` и upstream renderer для конкретных item variants. Обрабатываются string/object/choose creature types, fractional/object CR, legendary groups XMM, item groups и generic→specific variants. В loot попадают только XDMG2024 individual/hoard, 20 theme/rarity tables и4 rarity-by-level tables; 2014 tables исключаются. Каждый d100 диапазон покрыт ровно один раз, все ссылки разрешены, неподдержанная строка вызывает ошибку.

`catalog.py` проверяет version/hash manifest, загружает данные один раз и предоставляет lookup_monsters(query=None, habitat=None, creature_type=None, limit=5), limit1..10. Метка источника Any совместима с любой конкретной средой; filter any снимает habitat-ограничение, сохраняя type/required/count. resolve_monster принимает ID либо имя; отсутствие и неоднозначность различаются. Полные тексты всех503 записей одним tool call не передаются.

Команда: `uv run python -m dnd_rag prepare-game-data`. Пути читаются из `configs/game.yaml`, явные --source/--output перекрывают их и разрешаются от project root. Результат `data/game/5etools/<source-sha>/`: monsters/items/loot_tables/encounter_rules.json и manifest.json. Manifest содержит SHA upstream, schema/compiler version, input hashes, output hashes и counts; timestamp не мешает воспроизводимости. Файлы публикуются атомарно, manifest последним. Tool calls каталог не пересобирают.

На закреплённом c3d5395 сборка дала503 monsters,2297 конкретных/обычных items и24 magic tables; повторная сборка побитно совпала по manifest. Корпус Markdown/source_map и upstream не менялись.

## Расчёты и генерация

`encounters.py`: evaluate_encounter считает сумму XP по каталогу и бюджеты XDMG2024: low≤L, moderate при L<XP≤M, high при M<XP≤H, выше — above_high/exceeds_high. Множителей2014 нет. Все персонажи одного уровня1..20, party_size и количества положительны.

build_encounter использует ту же арифметику, сохраняет required counts без добавления копий тех же IDs и применяет habitat/type ко всему составу. По умолчанию перебирает не более256 различных форм, ≤3 stat blocks, auto count1..min(12,2*party_size); явный total_count задаёт точное количество. Формы разных количеств чередуются, выбирается ближайшая снизу стоимость внутри нужной категории. Алгоритм детерминирован. Неисчерпывающий поиск возвращает search_exhausted, конфликт заданных требований — conflict. Он не доказывает невозможность всех иных составов.

`loot.py`: generate_loot(kind, cr, count=1, party_level=None, treasure_theme=None). Individual — один денежный бросок×количество одинаковых существ. Hoard — один владелец с явным CR, денежный бросок и число предметов по CR, редкость по уровню партии, затем d100 по Arcana/Armaments/Implements/Relics и случайный конкретный допустимый вариант. Для hoard нужны party_level и treasure_theme, count=1; CR встречи не суммируется. Dice/RNG внедряется в тестах; продукт использует случайный источник без фиксированного seed. Возвращаются фактические coins/total_gp, имена/редкости/источники items, rolls и tables. Результат сохраняется агентом; воспоминание о добыче не является новым броском.
