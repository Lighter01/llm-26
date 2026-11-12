# Данные

`markdown/5etools/<revision>/` — канонические XPHB/XDMG/XMM и source_map; `resolved/` — подготовленные входы exporter; оба генерируются ingestion и не коммитятся. `qdrant/` — изолированное постоянное хранилище lab3. `tasks/` — фиксированный новый набор агентных задач. `game/` — будущие JSON-каталоги игровых инструментов. Генерируемые данные не редактируются вручную.

Игровой snapshot создаёт `uv run python -m dnd_rag prepare-game-data`; версия закреплена в SHA-каталоге, manifest проверяет все inputs/outputs. Это отдельная подготовка, не пересборка Markdown-корпуса.
