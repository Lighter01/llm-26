# RAG / локальная LLM

- `llm.py`: LLMClient использует ChatOpenAI Chat Completions, native apply-template/
  tokenize того же llama.cpp и общие thinking/template параметры. Модель здесь
  не запускается. LLMOutput сохраняет usage, finish_reason и native timings того же вызова.
- `runtime/llama.py` (соседний пакет): один запуск установленного llama.cpp server,
  явный профиль, readiness/model/context check, защита от занятого endpoint.
- `scripts/start_llama_server.py`: отдельный managed запуск с тем же launcher и lock.

Packing, Citation Registry и QA service добавляются в Task10. Публичные команды,
профиль и измерения — [CLI](../../../docs/user_docs/CLI.md),
[TECHNICAL_PROBES](../../../docs/rag/TECHNICAL_PROBES.md).
