# Доменное обогащение

`enrich_books.mjs` — CLI; `enrichment_inputs.mjs` проверяет входы inventory/assembly. `enrichment_plan.mjs` строит конечный граф placements и dependencies; `enrichment_content.mjs` материализует native компоненты и помечает общий fluff.

Сюда относятся subclasses/features, prerequisites, summons, monster lore/groups, items/variants и остальные source-defined материалы. Проверку полноты и всех placement decisions выполняет `validation/validate_enrichment.mjs`. Enriched JSON временный: его использует `resolution/`, затем `resolve` удаляет рабочее хранилище. Developer CLI: `npm --prefix tools/ingestion run enrich`.
