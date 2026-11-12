# Профили LLM

`local.yaml` — унаследованный административный профиль llama-server; он изолирован от retrieval. Новые off/budgeted профили добавляются вместе с native full-payload counter и проверкой локальной модели. Параметры размещения GPU/KV должны быть заданы явно.
