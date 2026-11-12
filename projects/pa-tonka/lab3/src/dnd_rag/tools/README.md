# Общие MCP-инструменты

`server.py` создаёт официальный FastMCP1.30 StreamableHTTP server, bind127.0.0.1:8765/mcp. `ToolServices` получает готовый Retriever без загрузки модели на каждый вызов. `descriptions.yaml` хранит English tool descriptions.

На первой стадии опубликован только работающий `search_rules(query, limit=5)`, limit1..10. Возвращает полный исходный RetrievalResult: raw text, score/rank, устойчивые chunk/index/build IDs, book/section/pages attribution и hashes/Unicode ranges. Ошибка retrieval возвращает `error.code/message`, пустой hits — обычный результат. Остальные четыре функции добавляются с игровым каталогом; фиктивных placeholders нет.

Прямой запуск для диагностики: `uv run python -m dnd_rag.tools.server`. Он держит runtime lock до выхода. Основное приложение далее использует ту же фабрику в общей композиции.

После подготовки каталога сервер публикует ровно5 функций: search_rules, lookup_monsters, evaluate_encounter, build_encounter, generate_loot. Standalone startup вызывает ensure_game_catalog: готовый snapshot проверяется по manifest и input hashes, отсутствующий готовится до приёма запросов. Внутри tool calls компиляции нет. Lookup отдаёт ограниченные боевые stat blocks с нужными abilities и источником; технический lookup status различает matched/ambiguous/not_found. Все описания и JSON schemas English и одинаково доступны двум агентам. Подробные параметры и ограничения — [game](../game/README.md).

search_rules использует X-DND-Session-Id из реального HTTP request context для стабильной нумерации источников; scope не входит в model tool schema. Карта citations компактна, исходный текст не дублируется. Отсутствующий scope обозначается явно, не заменяется общей глобальной сессией.
