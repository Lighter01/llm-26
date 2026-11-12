# Архитектура

Канонические XPHB/XDMG/XMM Markdown и source_map → точные Unicode half-open spans → EmbeddingGemma 2 GPU-worker → собственный Qdrant. QueryEncoder работает на CPU и сохраняется между запросами. Retriever возвращает исходный текст, scores, index/build IDs, sections, честные page attribution и hashes.

Рабочий RagConfig не зависит от датасета, оценивания, LLM и интерфейса. R3/R9 меняют embedding input и build identity, не точность привязки к исходнику. Index manifest содержит весь набор chunks для независимого Recall/MRR. Отсутствие gold не препятствует поиску.

RuntimeSession владеет lock и дочерними process groups. Смерть parent не освобождает унаследованную блокировку, пока жив child; cleanup не завершает посторонние процессы. Неопределённая ошибка endpoint не означает свободный порт. Qdrant изолирован портами 6343/6344 и data/qdrant; ready collection проверяется по паспорту, payloads, количеству и ownership.

Математика retrieval-оценивания сохранена: пересечение ≥50% меньшего span, hash equality, P/R@1/5/10, MRR@10; короткая выдача не меняет знаменатель Precision. Локальные метрики и live-пробы относятся к lab3 только после нового запуска.

## Модель и подсчёт

NativeLLM переиспользует ChatOpenAI и родной GGUF tokenizer. HTTP-hook видит итоговый wire body после сериализации OpenAI: system, messages, schemas, calls/results, template и reasoning поля. Перед отправкой body без изменения передаётся native input_tokens. Guard проверяет `input + completion reserve + safety <= server window`; после ответа проверяет parity с usage. Messages-only счётчик и tiktoken не используются как замена полной проверки.

Предварительный body для middleware строится тем же ChatOpenAI serializer. Счётчик физического окна остаётся последней защитой в самом transport. Отдельный порог приложения 11000 нужен для последующего сокращения; он не равен окну сервера 16384. Off отправляет enable_thinking=false/effort=none/budget0, budgeted — true/budget512 без none; CLI сервера получает тот же профиль.

## Наблюдаемость и общий транспорт

Один StreamableHTTP MCP публикует рабочие инструменты обоим агентам. Retrieval остаётся чистым и не зависит от Langfuse. ObservationRecorder создаёт trace на turn с session/user/tags; tool и вложенный retrieval используют тот же фактический результат. Полный независимый JSONL сохраняется в `.runtime/sessions/<session>/turns.jsonl`; summary впоследствии не удаляет исходный журнал.

Langfuse SDK5.2.0 отправляет данные в локальный Compose4.79.0 и вызывает flush перед выходом. Для собственного агента подключается официальный LangChain CallbackHandler. Codex exporter восстанавливает transcript по rollout; его generation input не обещается точной копией wire payload после native compaction. Полнота generation/usage/tools и последней реплики проверяется сквозным smoke; одно открытие web UI этого не доказывает.

## Два агентных адаптера

Собственный AgentService использует LangChain create_agent, native tools, checkpointer/thread_id и middleware лимитов12 model/16 tool calls/300s на реплику. Tool errors доступны модели для исправления; timeout/step_limit/context_budget — явные статусы с trace. Native HTTP guard остаётся физической защитой от переполнения. Полноценное summary подключается отдельной стадией.

CodexRunner вызывает exec и exec resume по точному ID, без личного config и эталонов, из пустого /tmp cwd. Исходный rollout сохраняется независимо от compaction. Явный model catalog выбирает direct tools и16K; stock base instruction и алгоритм local compaction сохраняются. Из-за фактического несовпадения форматов Codex0.167 и llama11046 используется тонкий proxy8081→8080: additional_tools/namespace переводятся в обычные Responses functions и обратно. Оба клиента используют те же weights, MCP game tools и профиль генерации; original/effective payload и count/usage доступны для аудита. Сравнение учитывает внутренний prompt и счётчик Codex как свойство готового агента.

Рабочий общий порог установлен11000 по smoke: при исходных8192 служебный Codex prefix5314 + выдача8252 вызывали повторное сокращение до ответа. Оба агента используют11000 при том же окне16384, reserve2048/safety256. Внутренний Codex счётчик отличается от native wire count; последнее число сохраняется отдельно.
