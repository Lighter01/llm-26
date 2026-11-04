# Тесты проекта

[Тесты ingestion](ingestion/README.md) состоят из двух самостоятельных наборов:

- [book_assembly](ingestion/book_assembly/README.md): Node-тесты сборщика, `npm --prefix tools/ingestion test` из `lab2`.
- [markdown_export](ingestion/markdown_export/README.md): Python unit/integration, `uv run --group test python -m pytest tests/ingestion/markdown_export --input-build PATH`; uv подключает test dependencies, готовый build обязателен для integration.

Наборы следующих компонентов добавляются при их реализации.
