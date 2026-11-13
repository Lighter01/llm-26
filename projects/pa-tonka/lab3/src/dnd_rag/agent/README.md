# Агентные контракты

`config.py` — AgentConfig: порог контекста 9500, recent 2048, summary 1024, 12 model calls, 16 tool calls, 300 секунд на реплику и адрес общего MCP. Экспортирует общий LLMProfile без второго набора параметров.

`contracts.py` — сериализуемые AgentReply, ContextStats и AgentEvent для CLI/runner. Неизвестный input_tokens равен None, а не нулю. Статусы и события одинаковы для интерактивного интерфейса и runner.

`observability.py` — ObservationRecorder: per-turn session/user/tags, вложенные tool/retrieval observations, независимый JSONL без усечения, flush и trace URL. При отсутствии keys локальный journal сохраняется, trace_id остаётся None; это не полноценная измерительная конфигурация.

`service.py` — AgentService с create_agent, native tool calling и InMemorySaver/thread_id. Два session изолированы, тот же session сохраняет сообщения и tool results. Лимиты контролирует middleware; ошибки tools возвращаются модели для исправления. Каждая генерация проходит полный native count; память сокращает предыдущие взаимодействия, превышение бюджета защищённой текущей задачи даёт явный context_budget. Tool/generation/events и полный wire body сохраняются в journal; Langfuse CallbackHandler пишет реальные generations.

`prompts/` — общая предметная инструкция; CLI и runner используют один service. `ainvoke(session_id, user_text, turn_id=..., on_event=...)` возвращает AgentReply, `aclose()` flush/close. Веса не загружаются заново на реплику.

`memory.py` — ContextBudget и штатный SummarizationMiddleware с native full-payload counter, целыми interactions и summarizer без скрытого overflow trim. `prompts/summary.txt` задаёт разделы фактов; полный исходный journal сохраняется независимо от summary. Уже потреблённый usage записывается и для пустого/оборванного summary, хотя такое summary не заменяет память.

`citations.py` — persistable CitationRegistry/CitationRef и CitationValidation: dialog-scoped номера только фактических search hits, exact text/provenance без выдуманной страницы; summary не владеет registry. `observability.model_response` сохраняет полный доступный native ответ/reasoning отдельным span без повторного начисления usage.

Обрезанный финальный ответ возвращается как incomplete/generation_truncated с частичным текстом и потреблённым usage. При прерывании более поздней генерации полные totals остаютсяNone, известные ответы сохраняются в journal. Закрытие pending tools закрепляет также уже полученные параллельные результаты, чтобы checkpoint update не потерял фактический payout.
