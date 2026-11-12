# Проверки lab3

Предварительный рефакторинг: новые тесты выбора профиля из другого cwd, независимости от LLM/gold и одинаковых spans при разной build identity наблюдались в RED. Non-live suite до финальных правок: 535 passed, 80 deselected. Финальный запуск: 535 passed, 80 deselected; Ruff чистый; Node ingestion 47/47.

Живое построение/reuse, модель, MCP и Langfuse требуют новых запусков; результаты lab2 здесь не используются как доказательство. Метрики качества нового датасета ещё не получены.

Живая коллекция lab3 построена и повторно использована; source corpus не пересобирался. Native llama build11046 на основном Nemotron прошёл Chat/Responses count↔usage parity в off и budgeted512; реальный tool call/result принят обоими режимами. Генерация budgeted содержит reasoning; off его не содержит. Это пробы модели, не измерение качества агента.

Ранний shared-stack gate: собственный агент и Codex прошли реальный search_rules и двухходовую историю, все turns/generations/tools/usage и последний Codex turn прочитаны через Langfuse v2. Opt-in shared-stack pytest на общем пороге11000 прошёл1/1 за30.19s; повторный exporter не добавил дублей. Для Codex потребовался additional_tools/namespace compatibility proxy и explicit direct-tool catalog. Исходный8192 дал search→compaction loop; это сохранённая неудачная техническая проба, не результат основного датасета.
