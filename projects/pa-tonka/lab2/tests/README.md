# Тесты проекта

[Тесты ingestion](ingestion/README.md) состоят из трёх самостоятельных наборов:

- [book_assembly](ingestion/book_assembly/README.md): Node-тесты сборщика, `npm --prefix tools/ingestion test` из `lab2`.
- [markdown_export](ingestion/markdown_export/README.md): Python unit/integration, `uv run --group test python -m pytest tests/ingestion/markdown_export --input-build PATH`; uv подключает test dependencies, готовый build обязателен для integration.
- [question_validation](ingestion/question_validation/README.md): строгая схема, цитаты, координаты и публикация; `uv run --group test python -m pytest tests/ingestion/question_validation`, реальные книги не требуются.

Наборы следующих компонентов добавляются при их реализации.
