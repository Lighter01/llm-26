# Пример чтения resolved JSON

`read_book.py` — исполняемый пример к [модели данных](../DATA_MODEL.md), не часть сборщика и не Markdown-экспортёр. Использует только Python stdlib; запускается через uv из корня `lab2`.

```bash
uv run python docs/ingestion/examples/read_book.py /path/to/build --book XPHB --chapter 3
uv run python docs/ingestion/examples/read_book.py /path/to/build --book XDMG
uv run python docs/ingestion/examples/read_book.py /path/to/build --book XMM
```

Путь берётся из вывода `resolve` и задаёт конкретную версию. Проверяются размер и file hash, читаются одна книга, глава, wrapper и его origin. Для XPHB также читаются progression table и subclass relationships Barbarian. Без `--chapter` выбирается первая часть со вставками. Для части без вставок `embedded` будет null.

Для работы с готовым файлом сам 5e.tools и Node не нужны. Пример не выполняет полную schema/source validation и не воспроизводит content hash на Python. Для этих проверок используйте CLI или Node-пример в DATA_MODEL.
