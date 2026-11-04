# Unit и fixtures

Файлы сгруппированы по именам production-компонентов: JSON/IDs/pages, Git preflight, source inventory, assembly, enrichment, schema/hashes и storage. `chapter_probe.test.mjs` проверяет selection совместимого developer CLI, `test_runner.test.mjs` — выбор вложенных файлов и честный статус отчёта.

Запуск: `npm --prefix tools/ingestion run test:unit`. Тесты используют собственные tmp/Git fixtures; inventory grammar проверяется на текущем native runtime без редактирования upstream.
