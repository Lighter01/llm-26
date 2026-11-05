# RAG / локальная LLM

- `llm.py`: LLMClient использует ChatOpenAI Chat Completions, native apply-template/
  tokenize того же llama.cpp и общие thinking/template параметры. Модель здесь
  не запускается. LLMOutput сохраняет usage, finish_reason и native timings того же вызова.
- `runtime/llama.py` (соседний пакет): один запуск установленного llama.cpp server,
  явный профиль, readiness/model/context check, защита от занятого endpoint.
- `scripts/start_llama_server.py`: отдельный managed запуск с тем же launcher и lock.

- `context.py`: первые пять hits, полный prompt и точный лимит 6400; целые хвостовые
  чанки удаляются с пересчётом. PackedContext содержит фактические messages и frozen registry.
- `citations.py`: Markdown parser исключает код, escapes и разрешённые links/images;
  сохраняет номера и выдаёт Source только для использованных допустимых `[n]`.
- `service.py`: stateless RagService.ask возвращает AskTrace: публичный AskResult,
  тот же retrieval, messages/registry, raw answer, usage и серверные timings.
  Пустой retrieval обрабатывается без LLM; превышение бюджета — ошибка без генерации.

Публичные команды,
профиль и измерения — [CLI](../../../docs/user_docs/CLI.md),
[TECHNICAL_PROBES](../../../docs/rag/TECHNICAL_PROBES.md).
