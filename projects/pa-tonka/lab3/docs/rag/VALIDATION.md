# Проверки lab3

Финальный non-live gate: **639 passed,84 deselected** за29.03s с явно заданными четырьмя DM_SAVED_RUNS; saved-matrix audit выполнен, не skipped. Ruff clean. Node ingestion47/47, Python ingestion integration77 passed на существующем resolved build без пересборки книг; отдельная проверка фактического dataset/evidence1passed/5deselected.

Все60executions/188turns/60isolatedsessions сохранены;536 semantic worksheet criteria заполнены как agent-assisted. Проверены common fingerprints, фактические profiles/sampling/nativecount↔usage, source registry/manifest и offline recompute. В каждой клетке все3long имели реальные compaction events.

Langfuse:606generations завершённых turns имеют точное совпадение usage с native. В4тайм-аутах сохранены83полученных generations; usage4незавершённых ответов неизвестен. Для каждой клетки API подтвердил47distinct Experiment item→trace links, run scores и scores последней реплики. Частичные traces не объявлены полными.

Post-fix live probe: реальный MCP lookup/build Mage с Any-habitat,2300XP/high для2×6; по2связанных turn собственного агента и Codex, точный resume, последний trace/readback и повторный export без дублей. Диагностика off/11000 исключена из основной матрицы9500. Ранее фактически проверены Chat/Responses off/budgeted512 parity, общий MCP, повторные summary, CLI PTY/new/status/exit и диагностические ошибки.

Измерения относятся к7954685; финальный код содержит последующие исправления границ/учёта, описанные в отчёте. Результаты lab2 и исследовательские заметки доказательствами не служат. [Отчёт](../../report/LAB3_REPORT.md), [машинные проверки](../../results/lab3/verification.json), [демонстрация](../user_docs/DEMO.md). Условный Streamlit отложен; основной CLI работает.
