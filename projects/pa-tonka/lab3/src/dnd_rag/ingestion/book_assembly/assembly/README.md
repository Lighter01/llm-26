# Главы и обязательные вставки

`assemble_books.mjs` — CLI сборки всех исходных глав. `assembly_content.mjs` вызывает native preload/dereferencing, закрывает silent misses и фиксирует origin. `assembly_inventory.mjs` читает проверенный inventory; `assembly_schema.mjs` сериализует loader data и проверяет активные обязательные refs.

Результат временный: assembled JSON, ещё без domain enrichment. Его проверяет `validation/validate_assembly.mjs`, затем читает `enrichment/`. Самостоятельный запуск: `npm --prefix tools/ingestion run assemble`; `--inventory PATH` и `--output-root PATH` позволяют явно выбрать вход/диагностику. Обычный пользователь запускает `resolve`, управляющий всей цепочкой.
