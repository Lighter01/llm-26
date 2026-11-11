# Интеграция и регрессии

`inventory`, `assembly`, `enrichment` проверяют настоящую цепочку стадий. `resolved.integration.test.mjs` собирает финальные книги и вызывает все corpus regressions, проверяет manifest/schema, reuse, validate-only, force и ошибки. `snapshot_update.integration.test.mjs` проверяет обновление реального fixture commit/gitlink, content hashes, dirty/mismatch/unknown inputs и очистку workspace.

Запуск: `npm --prefix tools/ingestion run test:integration`. Все выходы тестовые, в tmp. Реальный submodule используется только для чтения.
