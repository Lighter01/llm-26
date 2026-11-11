# Helpers тестов

`native_smoke.mjs` — дочерний процесс для настоящего upstream runtime. `corpus_regressions.mjs` — независимые source comparisons R01–R10/S01–S02: собственный обход JSON/Pointer, полные source recipes, all-record audit и Ajv. Его вызывает финальный integration-тест с явно сохранённой test diagnostics. Helpers не входят в production-пайплайн и не являются отдельными test suites.
