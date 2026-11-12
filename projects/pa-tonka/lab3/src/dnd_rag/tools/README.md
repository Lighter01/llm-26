# Общие MCP-инструменты

`server.py` создаёт официальный FastMCP1.30 StreamableHTTP server, bind127.0.0.1:8765/mcp. `ToolServices` получает готовый Retriever без загрузки модели на каждый вызов. `descriptions.yaml` хранит English tool descriptions.

На первой стадии опубликован только работающий `search_rules(query, limit=5)`, limit1..10. Возвращает полный исходный RetrievalResult: raw text, score/rank, устойчивые chunk/index/build IDs, book/section/pages attribution и hashes/Unicode ranges. Ошибка retrieval возвращает `error.code/message`, пустой hits — обычный результат. Остальные четыре функции добавляются с игровым каталогом; фиктивных placeholders нет.

Прямой запуск для диагностики: `uv run python -m dnd_rag.tools.server`. Он держит runtime lock до выхода. Основное приложение далее использует ту же фабрику в общей композиции.
