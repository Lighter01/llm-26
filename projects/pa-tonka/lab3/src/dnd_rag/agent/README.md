# Собственный агент

`AgentService` связывает LangChain `create_agent`, общие MCP-инструменты, память и наблюдаемость. CLI и runner используют один интерфейс:

```python
reply = await service.ainvoke(session_id, user_text, turn_id=turn_id, on_event=on_event)
await service.aclose()
```

`aclose()` вызывается при завершении работы сервиса. Веса модели не загружаются заново на каждую реплику. Схема взаимодействий — в [ARCHITECTURE](../../../docs/user_docs/ARCHITECTURE.md#путь-одной-реплики), определения — в [глоссарии](../../../docs/user_docs/GLOSSARY.md).

## Состояние и лимиты

`InMemorySaver` хранит состояния LangGraph по `thread_id=session_id` в памяти процесса. Следующая реплика той же сессии получает историю и результаты tools; разные сессии изолированы. Дисковый журнал сохраняет исходные записи для аудита, но не восстанавливает checkpointer после перезапуска автоматически.

Лимиты `AgentConfig` действуют **на один вызов `ainvoke`**: 12 обращений к генеративной LLM, включая summary, 16 вызовов tools и 300 секунд агентного цикла. Следующая реплика получает новые счётчики. Завершение ресурсов и отправка журнала могут увеличить полное время вызова.

Контекст ограничен токенами полного запроса; отдельного лимита пользовательского текста в символах/байтах нет. При пороге 9 500 сокращаются старые завершённые взаимодействия. Последний запрос и его tool calls/results сохраняются целиком. Если они всё ещё не помещаются, возвращается ошибка `context_budget`; для физического окна — `context_overflow`. Подробности и пример причины переполнения — в [разделе памяти](../../../docs/user_docs/ARCHITECTURE.md#как-заменяется-история).

## Результат и наблюдаемость

`AgentReply` содержит текст, статус, измерения, источники и trace ID. Если генерация остановлена по лимиту длины, частичный текст сохраняется, `status="incomplete"`, `error["code"]="generation_truncated"`. При неизвестном полном расходе токеновые итоги внутри `usage` равны `None`, а известные генерации остаются в журнале.

`ObservationRecorder` сохраняет полный JSONL и отправляет вложенные записи LLM/tools/retrieval/summary в Langfuse. Generation содержит usage вызова; дополнительный span `raw-model-response` хранит исходный API-ответ и reasoning, не начисляя те же токены второй раз. Без ключей Langfuse локальный журнал остаётся доступен, `trace_id` равен `None`; штатный launcher требует настроенную наблюдаемость.

При прерывании незавершённые tool calls закрываются явными ошибками; уже полученные параллельные результаты сохраняются при обновлении checkpoint. Пустое или оборванное summary не заменяет память, но потраченные токены учитываются.

## Карта модуля

| Файл | Ответственность |
| --- | --- |
| [service.py](service.py) | `AgentService`, граф, ограничения реплики и события. |
| [config.py](config.py) | `AgentConfig` и общий `LLMProfile`; отдельного дублирующего профиля нет. |
| [contracts.py](contracts.py) | Сериализуемые `AgentReply`, `ContextStats`, `AgentEvent`. |
| [memory.py](memory.py) | `ContextBudget`, штатный `SummarizationMiddleware` и полный native count. |
| [observability.py](observability.py) | `ObservationRecorder`, JSONL, trace URL и отправка Langfuse. |
| [citations.py](citations.py) | `CitationRegistry`, `CitationRef`, `CitationValidation`: номера только фактических hits текущего диалога; summary реестр не очищает. |
| [prompts/](prompts/README.md) | Общая предметная инструкция и инструкция суммаризации. |
