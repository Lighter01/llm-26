# Тесты retrieval

`test_config/identity` — выбор профиля, cwd/строгая схема и fingerprints; `test_corpus/chunking/embedding` — точные spans и embedding input; `test_store/build/retrieval` — ownership, readiness/reuse, worker и ranked hits; `test_metrics` — независимый gold на синтетических spans, hash/dedup/короткая выдача; `test_runtime/launcher/preflight` — lock, реальные child processes и отсутствие воздействия на чужие процессы. `test_cli` — административный интерфейс; `test_llm` — изолированные низкоуровневые модельные helpers. `fixtures.py` — маленький независимый корпус; `integration/` — opt-in пробы моделей/сервисов.

`test_shutdown_signals.py` — настоящий SIGTERM во время работы, SIGINT/SIGTERM между Popen и регистрацией, восстановление handlers, освобождение lock и сохранность соседнего процесса. Необрабатываемый SIGKILL отдельно проверяется в `test_runtime.py`.
