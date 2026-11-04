# Общая инфраструктура сборщика

`book_schema.mjs` содержит строгую JSON-сериализацию, канонизацию, IDs и origins. `source_scan.mjs` читает JSON, выбирает книги по ID и обходит все поля дерева. `tree.mjs` собирает embedded wrappers, не заходя в их payloads. `artifact_store.mjs` проверяет пути и публикует промежуточные наборы атомарно. `project_paths.mjs` задаёт пути проекта, developer diagnostics и fingerprint кода.

Эти модули используются всеми стадиями [сборщика](../README.md). Исследовательское сканирование вынесено в `ingestion/dev/source_review.mjs`.
