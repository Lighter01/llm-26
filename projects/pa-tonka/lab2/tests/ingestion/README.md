# Тесты ingestion

[markdown_export](markdown_export/README.md) — отдельный Python pytest-набор: unit/fixtures, регрессии на готовых книгах, full corpus и воспроизводимость. Для integration требуется явный `--input-build`; сборщик не запускается.

Тесты согласованы со сборщиком `src/dnd_rag/ingestion/book_assembly`. [book_assembly](book_assembly/README.md) разделён на unit, integration, smoke и helpers. Имена файлов отражают production-модули. Native runtime/CLI запускаются отдельными процессами; реальные данные берутся только из pinned clone.

```bash
npm --prefix tools/ingestion test
npm --prefix tools/ingestion run test:unit
npm --prefix tools/ingestion run test:smoke
npm --prefix tools/ingestion run test:integration
npm --prefix tools/ingestion test -- --report /tmp/ingestion-tests.json
```

Runner рекурсивно находит `*.test.mjs`. Группы не пересекаются, полный набор включает все файлы. Используются Node 24.22.2 и независимый Ajv Draft 2020-12. Пропуски, незавершённые tests и nonzero exit не могут получить PASS. Отчёт по умолчанию — `.cache/ingestion/tests/<sha>/<signature>/report.json`. До/после прогона проверяются pinned upstream и fingerprint кода/тестов.

Полный актуальный прогон: **75/75 PASS**, без failed/cancelled/skipped/todo. [Матрица требований, source audit и границы проверки](../../docs/ingestion/VALIDATION.md) описаны отдельно от команд запуска.

Fixtures и выходы находятся в системном tmp и удаляются через teardown. Тесты обновления snapshot имеют собственные локальные clone/commits/gitlinks; настоящий submodule не переключается. Проверяются четыре финальных файла, удаление временных стадий при успехе и ошибке, reuse/validate-only без входов, force, воспроизводимость, source completeness и независимая JSON Schema.

`book_assembly/unit/chapter_probe.test.mjs` проверяет выбор главы, `book_assembly/unit/assembly.test.mjs` — repeated placements и unknown page. Silent miss, source identity, вложенные refs, сериализация и публикация проверяются assembly/inventory/resolution тестами. `book_assembly/integration/inventory.integration.test.mjs` сверяет probe глав 7/9 с инвентарём; отдельные corpus regressions проверяют итоговые книги.
