# Адаптеры и измерения

`contracts.py` — AgentAdapter с одинаковым AgentReply для двух клиентов. `codex.py` — CodexRunner: exec/resume по конкретному ID, пустой cwd в /tmp, explicit config, timeout/cancellation cleanup, raw stdout/stderr и копия исходного rollout. Existing CODEX_HOME используется только для поиска собственного session; личные настройки не меняются.

После каждого turn вызывается закреплённый официальный exporter с max_history_chars=0/fail_on_error=true. Trace ID выводится детерминированно из session/turn; v2 readback требует generations/input/output/usage, последнюю реплику и ожидаемые фактические tools. Отсутствие trace — incomplete, отсутствие usage — None. Повторный export использует upstream sidecar dedup на исходном rollout.

Код адаптера не читает expected_output/evidence и не передаёт их агенту. Доступные Codex встроенные инструменты отфильтрованы на wire-границе до общих MCP game functions; собственные внутренние инструкции и compaction Codex сохранены.

`contracts.py` задаёт dataset/case/scores/run contracts. `dataset.py` независимо проверяет exact evidence до запуска. `runner.py` исполняет фиксированные turns с изолированными sessions и связывает их с event-based Langfuse Experiments. `scoring.py` проверяет реальные outputs/ограничения, сохраняет pending rubric и использует прежнюю retrieval математику. `artifacts.py` хранит JSONL/CSV, делает offline recompute и сравнение fingerprint. `commands.py` связывает эти функции с общим launcher; CLI не разбирает ANSI-ответы чата.

Freeze включает Python, prompts, YAML tool descriptions, MJS exporters, catalog/config/model identities. Ошибки MCP failed/error приводятся к общему error только в производных scored-артефактах; полный исходный payload не изменяется. Offline evaluator и review CSV имеют отдельные хэши.

Capture exec/exporter защищён от отмены communicate: timeout/cancellation завершают только собственную process group, сохраняют уже прочитанный stdout/stderr. Exact native session ID, closed original rollout и wire сохраняются до повторного проброса отмены. Rollout и полный export log архивируются до trace readback; ошибка Langfuse не уничтожает исходное доказательство. Failed/timed-out exporter сохраняет полный лог и не остаётся фоновым child.
