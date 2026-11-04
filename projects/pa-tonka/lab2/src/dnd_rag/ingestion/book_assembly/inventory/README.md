# Инвентаризация

`inventory.mjs` — CLI, вызываемый orchestration перед сборкой. `inventory_books.mjs` фиксирует позиции всех книжных узлов и обязательных refs. `inventory_sources.mjs` собирает source-defined records и dependency evidence. Штатные lookup/tag API находятся в соседнем `runtime/`.

```bash
npm --prefix tools/ingestion run inventory -- --output-root /tmp/dnd-diagnostics
```

Без `--output-root` standalone CLI пишет в игнорируемый `.cache/ingestion/diagnostics/5etools`. Обычный `resolve` передаёт собственный временный root и удаляет его. Реестры и report потребляет стадия `assembly/`; сам инвентарь не является resolved-книгой.
