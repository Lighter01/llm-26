# Игровые каталоги

`contracts.py` — SourceRef, Monster/MonsterCount, CatalogSnapshot и результаты encounter/loot. Один monster_id используется lookup и encounter-инструментами; SourceRef сохраняет книгу, фактический файл, страницу при наличии и происхождение варианта.

`prepare.py` компилирует JSON snapshot; `prepare_5etools.mjs` использует существующий guarded `openUpstreamRuntime` и upstream renderer для конкретных item variants. Обрабатываются string/object/choose creature types, fractional/object CR, legendary groups XMM, item groups и generic→specific variants. В loot попадают только XDMG2024 individual/hoard, 20 theme/rarity tables и4 rarity-by-level tables; 2014 tables исключаются. Каждый d100 диапазон покрыт ровно один раз, все ссылки разрешены, неподдержанная строка вызывает ошибку.

`catalog.py` проверяет version/hash manifest, загружает данные один раз и предоставляет lookup_monsters(query=None, habitat=None, creature_type=None, limit=5), limit1..10. resolve_monster принимает ID либо имя; отсутствие и неоднозначность различаются. Полные тексты всех503 записей одним tool call не передаются.

Команда: `uv run python -m dnd_rag prepare-game-data`. Пути читаются из `configs/game.yaml`, явные --source/--output перекрывают их и разрешаются от project root. Результат `data/game/5etools/<source-sha>/`: monsters/items/loot_tables/encounter_rules.json и manifest.json. Manifest содержит SHA upstream, schema/compiler version, input hashes, output hashes и counts; timestamp не мешает воспроизводимости. Файлы публикуются атомарно, manifest последним. Tool calls каталог не пересобирают.

На закреплённом c3d5395 сборка дала503 monsters,2297 конкретных/обычных items и24 magic tables; повторная сборка побитно совпала по manifest. Корпус Markdown/source_map и upstream не менялись.
