# Проверки lab3

Предварительный рефакторинг: новые тесты выбора профиля из другого cwd, независимости от LLM/gold и одинаковых spans при разной build identity наблюдались в RED. После предварительного рефакторинга535 non-live tests passed/80deselected, Ruff clean и Node ingestion47/47. Это ранний gate; итоговая проверка всего приложения и матрицы приводится ниже.

Ни результаты lab2, ни исследовательские заметки не используются как доказательство. Перечисленные ниже пробы выполнены новым приложением lab3; итоговая матрица публикуется отдельно.

Живая коллекция lab3 построена и повторно использована; source corpus не пересобирался. Native llama build11046 на основном Nemotron прошёл Chat/Responses count↔usage parity в off и budgeted512; реальный tool call/result принят обоими режимами. Генерация budgeted содержит reasoning; off его не содержит. Это пробы модели, не измерение качества агента.

Ранний shared-stack gate: собственный агент и Codex прошли реальный search_rules и двухходовую историю, все turns/generations/tools/usage и последний Codex turn прочитаны через Langfuse v2. Opt-in shared-stack pytest на общем пороге11000 прошёл1/1 за30.19s; повторный exporter не добавил дублей. Для Codex потребовался additional_tools/namespace compatibility proxy и explicit direct-tool catalog. Исходный8192 дал search→compaction loop; это сохранённая неудачная техническая проба, не результат основного датасета.

Перед повторной основной матрицей:620 non-live tests passed,1 explicit saved-artifact skip,84 deselected; Ruff clean. Новый default9500 проверяется полным Codex/budgeted Orla после реального overflow11000. Source freeze включает YAML tool descriptions/MJS exporter; групповые citations проверяются по каждому номеру. Итоговые независимый review и artifact audit добавляются после четырёх полных запусков.
