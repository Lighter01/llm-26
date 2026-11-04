# Финализация и сохранение

`resolve_books.mjs` — основная CLI и управление временными стадиями. `resolved_inputs.mjs` проверяет цепочку входов; `resolved_schema.mjs` формирует оболочку книги и выполняет standalone validation по канонической `resolved-book.schema.json` (Draft 2020-12, версия книги 1.0.0). `resolved_content.mjs` считает содержательный хэш; `resolved_manifest.mjs` проверяет контракт manifest 2.0.0 и четыре финальных файла. `resolved_store.mjs` и stdlib `atomic_exchange.py` обеспечивают locks, staging и атомарный `--force` на Linux.

```bash
npm --prefix tools/ingestion run resolve
npm --prefix tools/ingestion run resolve -- --validate-only
npm --prefix tools/ingestion run resolve -- --force
npm --prefix tools/ingestion run resolve -- --force --diagnostics-root /tmp/dnd-review
```

Последняя команда сохраняет detailed `report.json` и `placement-audit.jsonl` в `/tmp/dnd-review/<sha>/resolution/<signature>/` вместе с входами стадий 3–5 в соседних каталогах. В каталоге книги остаются только три JSON и manifest; сама схема никогда туда не копируется. Основные параметры — в [README](../README.md).
