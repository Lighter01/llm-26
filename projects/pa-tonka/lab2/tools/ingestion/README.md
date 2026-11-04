# Изолированная Node-среда ingestion

`package.json` задаёт публичные npm-команды и закреплённые devDependencies: Node **24.22.2**, Ajv **8.20.0** для независимой проверки схемы. `package-lock.json` сохраняется под контролем версий. `node_modules/` игнорируется. Корневой Python-проект не превращается в npm workspace.

```bash
npm ci --prefix tools/ingestion --no-audit --no-fund
npm --prefix tools/ingestion run resolve
npm --prefix tools/ingestion test
```

Для установки нужен npm registry и разрешённые install scripts пакета Node. После установки сборка и тесты работают без сети; устанавливать зависимости внутри `external/5etools-src` не нужно.

`run_tests.mjs` рекурсивно обнаруживает тесты, запускает Node runner и проверяет итог/неизменность входов. `test_reporter.mjs` сохраняет ограниченный контекст test events без сериализации целых книг при assertion failure.

Все существующие aliases сохранены: `recon`, `prototype`, `inventory`, `assemble`, `enrich`, `resolve`, `test`, `test:unit`, `test:smoke`, `test:integration`. [CLI и хранение](../../src/dnd_rag/ingestion/README.md) · [Тестовые группы и отчёты](../../tests/ingestion/README.md).
