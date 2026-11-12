# Конфигурации

- `rag/`: рабочие retrieval-профили R3 и R9, не зависят от датасета.
- `llm/`: параметры llama-server, проверяются отдельно от retrieval.

Все относительные пути разрешаются от корня проекта. Переменные процесса перекрывают `.env`; явный административный `--config` перекрывает оба источника.

`baseline/` — изолированный Codex config и explicit model catalog с direct tools, stock base instruction и common context11000. `codex.toml` превращается в CLI overrides; не копируется в личный config пользователя.
