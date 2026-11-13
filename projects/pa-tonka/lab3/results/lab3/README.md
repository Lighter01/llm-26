# Измерения DM-помощника

Основные run IDs: `lab3-own-off-20261113-v2`, `lab3-own-budgeted-20261113-v2`, `lab3-codex-off-20261113-v2`, `lab3-codex-budgeted-20261113-v2`. Это один фиксированный набор из 15 задач/47 реплик, 60 task executions/188 turns в четырёх клетках. Дата в ID — московская, временные метки JSON — UTC.

Полные run directories сохраняются локально и игнорируются Git: run.json/provenance, полный manifest, turns/tool_calls JSONL, raw own journals/Codex rollouts/wire, Langfuse readbacks, citation registries, review.csv/notes и scored_turns/metrics. Результаты не перезаписываются; новый запуск требует нового ID. В Git включаются отдельные сводки и отчёт.

`smoke9-*` — предварительные маленькие прогоны; они не входят в основную матрицу. Смысловая оценка обозначается agent-assisted с evidence на каждый turn/criterion; это не human review. Локальный recompute использует raw результаты, независимые source spans и полный manifest, без нового поиска или LLM.

Команды запуска/оценивания: [CLI](../../docs/user_docs/CLI.md), методика: [EVALUATION](../../docs/user_docs/EVALUATION.md), результаты: [отчёт](../../report/LAB3_REPORT.md). На другом компьютере локальные raw directories нужно перенести либо воспроизвести командами; один comparison.csv не заменяет исходные артефакты.

`lab3-*-20261113-v1` — сохранённая диагностика на 11000: own/off завершён, Codex/off остановлен после переполнения окна в Orla; эти данные исключены из итоговой матрицы. Итоговая v2 использует общий 9500 и frozen `7954685`. `diagnostic-*` — отдельные регрессионные проверки, не дополнительные основные клетки.

`matrix.json` — полные итоговые метрики четырёх клеток, `comparison.csv/json` — компактное сравнение, `schema-summary.json` — actual wire schema hashes, `source-freeze-audit.json` — 48 runtime файлов frozen commit, `verification.json` — фактические проверки и trace/Experiment audits. Measured source `7954685` отличается от последующих release fixes; версия и ограничения указаны в отчёте.
