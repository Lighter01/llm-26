# Проверки экспериментальных адаптеров

`test_codex.py` — безопасный argv, точный resume ID, неизвестный usage, сохранение последней реплики, discovery существующего CODEX_HOME, полнота trace и отмена реального дочернего процесса. `test_codex_proxy.py` — дополнительный tools item и namespace schemas, сохранность всей истории/аргументов/results, обратное преобразование SSE function calls, reasoning boundaries и usage. Live Codex/LLM/MCP/Langfuse проверяются отдельно.

`test_dataset_runner.py` —60 fake executions/188 turns, изоляция, отсутствие gold в inputs, exact evidence и offline recompute. `test_scoring.py` — pending semantics, реальные loot results, required constraints, исправление аргументов и полный retrieval manifest. Raw/observability probes запускаются отдельно на живом stack.
