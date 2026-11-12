# Адаптеры и измерения

`contracts.py` — AgentAdapter с одинаковым AgentReply для двух клиентов. `codex.py` — CodexRunner: exec/resume по конкретному ID, пустой cwd в /tmp, explicit config, timeout/cancellation cleanup, raw stdout/stderr и копия исходного rollout. Existing CODEX_HOME используется только для поиска собственного session; личные настройки не меняются.

После каждого turn вызывается закреплённый официальный exporter с max_history_chars=0/fail_on_error=true. Trace ID выводится детерминированно из session/turn; v2 readback требует generations/input/output/usage, последнюю реплику и ожидаемые фактические tools. Отсутствие trace — incomplete, отсутствие usage — None. Повторный export использует upstream sidecar dedup на исходном rollout.

Набор/runner/scoring добавляются следующей стадией. Код адаптера не читает expected_output/evidence и не передаёт их агенту. Доступные Codex встроенные инструменты отфильтрованы на wire-границе до общих MCP game functions; собственные внутренние инструкции и compaction Codex сохранены.

`contracts.py` задаёт dataset/case/scores/run contracts. `dataset.py` независимо проверяет exact evidence до запуска. `runner.py` исполняет фиксированные turns с изолированными sessions и связывает их с event-based Langfuse Experiments. `scoring.py` проверяет реальные outputs/ограничения, сохраняет pending rubric и использует прежнюю retrieval математику. `artifacts.py` хранит JSONL/CSV, делает offline recompute и сравнение fingerprint. `commands.py` связывает эти функции с общим launcher; CLI не разбирает ANSI-ответы чата.
