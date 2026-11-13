# Общие MCP-инструменты

[server.py](server.py) создаёт FastMCP 1.30 StreamableHTTP server на `127.0.0.1:8765/mcp`. `ToolServices` получает готовые Retriever и игровой каталог. [descriptions.yaml](descriptions.yaml) хранит английские описания; одни и те же пять функций доступны собственному агенту и Codex.

## Контракты вызовов

| Инструмент | Обязательные поля | Дополнительные поля / default |
| --- | --- | --- |
| `search_rules` | Непустой `query`. | `limit=5`, диапазон 1–10. |
| `lookup_monsters` | Нет: query/filters задают поиск. | `query`, `habitat`, `creature_type` — `None`; `limit=5`, 1–10. |
| `evaluate_encounter` | `party_size > 0`, `party_level` 1–20, непустой `monsters` с monster_id/count. | Нет. |
| `build_encounter` | `party_size > 0`, `party_level` 1–20, `difficulty=low/moderate/high`. | `habitat`, `creature_type`, `total_count` — `None`; `required_monsters=[]`. |
| `generate_loot` | `kind=individual/hoard`, допустимый `cr` 0–30, включая стандартные дроби. | `count=1`; для hoard обязательны `party_level` 1–20 и `treasure_theme=Arcana/Armaments/Implements/Relics`. |

Количество существ положительно; явный total_count сохраняется точно. Build перебирает не более 256 форм и 3 различных stat blocks; автоматический count — `1..min(12, 2 * party_size)`. `conflict` и `search_exhausted` не выдаются за успех. Hoard имеет одного владельца (`count=1`), CR встречи не суммируется. Алгоритмы и результаты — в [game](../game/README.md).

## Поиск и источники

`search_rules` возвращает полный исходный RetrievalResult: текст, rank/score, chunk/index/build IDs, книгу, разделы, атрибуцию страниц, хэши и Unicode-координаты. Ошибка поиска имеет `error.code/message`; пустой hits — допустимый результат.

HTTP-header `X-DND-Session-Id` задаёт scope нумерации; модель не передаёт его аргументом инструмента. Карта citations компактна, исходный текст не дублируется. При отсутствии scope номера не выдаются из общей глобальной сессии.

## Запуск

Диагностика: `uv run python -m dnd_rag.tools.server`, без параметров. Процесс удерживает проектный lock до выхода. Основное приложение использует ту же фабрику в `application_stack`.

Каталог подготавливается до приёма запросов: существующий snapshot проверяется по manifest/input hashes, отсутствующий компилируется. Внутри tool calls компиляции и повторной загрузки моделей нет. Lookup различает `matched`, `ambiguous`, `not_found`; составы используют общие IDs каталога.
