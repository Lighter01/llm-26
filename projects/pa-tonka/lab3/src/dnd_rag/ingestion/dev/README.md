# Диагностические инструменты ingestion

Эти инструменты запускаются явно и не требуются обычной команде `resolve`. Они используют тот же чистый pinned submodule и не изменяют его.

- `reconnaissance.mjs`, `source_review.mjs`, `smoke_runtime.mjs` — обзор текущей структуры upstream и представительные native API probes. Полезны после смены upstream для проверки его совместимости.
- `chapter_probe.mjs` — выбранная глава через **production assembler**. Сохранён CLI alias `prototype`; отдельный устаревший stage-2 resolver удалён. Диагностика ограничена spell/monster chapters и не объявляет полную книгу.

```bash
npm --prefix tools/ingestion run recon -- --report /tmp/dnd-recon.json
npm --prefix tools/ingestion run prototype -- --book XPHB --chapter 7 --output-root /tmp/dnd-probe
npm --prefix tools/ingestion run prototype -- --book XPHB --chapter 9 --output-root /tmp/dnd-probe
```

`recon` сохраняет `--upstream PATH`, `--report PATH`, `--help`. `prototype` сохраняет `--upstream PATH`, `--output-root PATH`, `--book ID`, `--chapter INDEX`, `--help`; индексы с нуля, по умолчанию XPHB/7. При отсутствии явного пути результаты идут в `.cache/ingestion/diagnostics/5etools`.

Отдельные production-стадии также доступны для диагностики:

```bash
npm --prefix tools/ingestion run inventory
npm --prefix tools/ingestion run assemble
npm --prefix tools/ingestion run enrich
```

Они используют developer storage `.cache/ingestion/diagnostics/5etools` по умолчанию. `--output-root PATH` меняет место вывода; `--inventory PATH`, `--assembly PATH` задают явные входы там, где применимы. Параметры доступны через `--help`. Для подробностей **полной** сборки вместо ручного запуска стадий:

```bash
npm --prefix tools/ingestion run resolve -- --force \
  --diagnostics-root .cache/ingestion/diagnostics/5etools
```

Разработчик управляет сроком хранения явно запрошенной диагностики. Обычный `resolve` создаёт собственные временные входы и удаляет их автоматически.
