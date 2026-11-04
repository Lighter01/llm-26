# Техническая документация ingestion

Документация ingestion XPHB/XDMG/XMM и экспорта готовых книг в Markdown. Книга имеет schema 1.0.0, manifest — 2.0.0, resolver — 0.6.2. [README исходников](../../src/dnd_rag/ingestion/README.md) содержит установку, пользовательские команды, обновление submodule и навигацию по коду.

| Документ | Для чего читать |
| --- | --- |
| [ARCHITECTURE](ARCHITECTURE.md) | Границы компонентов, выбор native Node runtime, карта модулей и поток данных |
| [DATA_MODEL](DATA_MODEL.md) | Самодостаточная книга, wrappers/domain, identities, origins/pages, manifest, хэши и контракт потребителя |
| [PIPELINE](PIPELINE.md) | Inventory, native resolution, enrichment, полный source audit, сериализация и атомарный force |
| [DEVELOPMENT](DEVELOPMENT.md) | Обновление upstream, тестовая инфраструктура, detailed diagnostics, новые типы и устранение ошибок |
| [VALIDATION](VALIDATION.md) | Проверенный snapshot, counts, требования/регрессии, 16 выборок ручного аудита и ограничения PASS |
| [MARKDOWN_REPRESENTATION](MARKDOWN_REPRESENTATION.md) | Правила представления книг, примеры и координаты карты |
| [MARKDOWN_EXPORT_VALIDATION](MARKDOWN_EXPORT_VALIDATION.md) | Готовые файлы, команды, фактические числа, примеры и ограничения проверки Markdown |
| [MARKDOWN_EXPORT_CORRECTIONS_AUDIT](MARKDOWN_EXPORT_CORRECTIONS_AUDIT.md) | Диагностический baseline перед исправлениями: воспроизведение ошибок, их причины и upstream-сопоставления |
| [Markdown export](../../src/dnd_rag/ingestion/markdown_export/README.md) / [tests](../../tests/ingestion/markdown_export/README.md) | Функциональная структура Python-модуля, API/CLI, публикация и проверки |
| [examples](examples/README.md) | Проверяемый Python stdlib пример чтения книги/главы/вставки/дочерних компонентов |

Каноническая [JSON Schema](../../src/dnd_rag/ingestion/book_assembly/resolution/resolved-book.schema.json) остаётся в исходниках. В final dataset сохраняются книги и manifest; временные входы и opt-in diagnostics не являются дополнительным книжным корпусом.

Документы описывают runtime решения, source-specific наблюдения, модель происхождения, правила scope и evidence. Исторические версии готовых книг не удаляются. Markdown-экспортёр — отдельный потребитель resolved JSON. RAG pipeline остаётся будущей задачей.
