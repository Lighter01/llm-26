# Native smoke

`native.smoke.test.mjs` запускает отдельный native helper и проверяет spell, monster, `_copy/_mod`, silent preload miss, обязательный loader и запрет сети. Каждый JSON input должен принадлежать tracked pinned snapshot.

Запуск: `npm --prefix tools/ingestion run test:smoke`. Это короткая проверка совместимости runtime; полные книги проверяет integration.
