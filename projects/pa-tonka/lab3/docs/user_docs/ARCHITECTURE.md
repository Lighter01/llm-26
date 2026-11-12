# Архитектура

Канонические XPHB/XDMG/XMM Markdown и source_map → точные Unicode half-open spans → EmbeddingGemma 2 GPU-worker → собственный Qdrant. QueryEncoder работает на CPU и сохраняется между запросами. Retriever возвращает исходный текст, scores, index/build IDs, sections, честные page attribution и hashes.

Рабочий RagConfig не зависит от датасета, оценивания, LLM и интерфейса. R3/R9 меняют embedding input и build identity, не точность привязки к исходнику. Index manifest содержит весь набор chunks для независимого Recall/MRR. Отсутствие gold не препятствует поиску.

RuntimeSession владеет lock и дочерними process groups. Смерть parent не освобождает унаследованную блокировку, пока жив child; cleanup не завершает посторонние процессы. Неопределённая ошибка endpoint не означает свободный порт. Qdrant изолирован портами 6343/6344 и data/qdrant; ready collection проверяется по паспорту, payloads, количеству и ownership.

Математика retrieval-оценивания сохранена: пересечение ≥50% меньшего span, hash equality, P/R@1/5/10, MRR@10; короткая выдача не меняет знаменатель Precision. Локальные метрики и live-пробы относятся к lab3 только после нового запуска.

## Модель и подсчёт

NativeLLM переиспользует ChatOpenAI и родной GGUF tokenizer. HTTP-hook видит итоговый wire body после сериализации OpenAI: system, messages, schemas, calls/results, template и reasoning поля. Перед отправкой body без изменения передаётся native input_tokens. Guard проверяет `input + completion reserve + safety <= server window`; после ответа проверяет parity с usage. Messages-only счётчик и tiktoken не используются как замена полной проверки.

Предварительный body для middleware строится тем же ChatOpenAI serializer. Счётчик физического окна остаётся последней защитой в самом transport. Отдельный порог приложения 9500 нужен для последующего сокращения; он не равен окну сервера 16384. Off отправляет enable_thinking=false/effort=none/budget0, budgeted — true/budget512 без none; CLI сервера получает тот же профиль.

## Наблюдаемость и общий транспорт

Один StreamableHTTP MCP публикует рабочие инструменты обоим агентам. Retrieval остаётся чистым и не зависит от Langfuse. ObservationRecorder создаёт trace на turn с session/user/tags; tool и вложенный retrieval используют тот же фактический результат. Полный независимый JSONL сохраняется в `.runtime/sessions/<session>/turns.jsonl`; summary впоследствии не удаляет исходный журнал.

Langfuse SDK5.2.0 отправляет данные в локальный Compose4.79.0 и вызывает flush перед выходом. Для собственного агента подключается официальный LangChain CallbackHandler. Codex exporter восстанавливает transcript по rollout; его generation input не обещается точной копией wire payload после native compaction. Полнота generation/usage/tools и последней реплики проверяется сквозным smoke; одно открытие web UI этого не доказывает.

## Два агентных адаптера

Собственный AgentService использует LangChain create_agent, native tools, checkpointer/thread_id и middleware лимитов12 model/16 tool calls/300s на реплику. Tool errors доступны модели для исправления; timeout/step_limit/context_budget — явные статусы с trace. Native HTTP guard остаётся физической защитой от переполнения. Память сокращает полный предыдущий prefix через SummarizationMiddleware.

CodexRunner вызывает exec и exec resume по точному ID, без личного config и эталонов, из пустого /tmp cwd. Исходный rollout сохраняется независимо от compaction. Явный model catalog выбирает direct tools и16K; stock base instruction и алгоритм local compaction сохраняются. Из-за фактического несовпадения форматов Codex0.167 и llama11046 используется тонкий proxy8081→8080: additional_tools/namespace переводятся в обычные Responses functions и обратно. Оба клиента используют те же weights, MCP game tools и профиль генерации; original/effective payload и count/usage доступны для аудита. Сравнение учитывает внутренний prompt и счётчик Codex как свойство готового агента.

Рабочий общий порог установлен9500 после длинного regression probe: при исходных8192 служебный Codex prefix5314 + выдача8252 вызывали повторное сокращение до ответа. Порог11000 прошёл ранний smoke, но в Orla дал полный input14686 + output2048 > window16384; диагностический прогон сохранён, итоговая матрица повторяется на общем9500. Оба агента используют9500 при том же окне16384, reserve2048/safety256. Внутренний Codex счётчик отличается от native wire count; последнее число сохраняется отдельно.

## Подготовленные игровые сущности

Каталог отделён от retrieval: guarded local 5etools → нормализация503 XMM monsters и legendary groups → concrete approved item variants →24 XDMG magic tables, individual/hoard и бюджетная таблица2024. Нет сетевого игрового API. Хэши всех семи фактических JSON inputs и четырёх output files связываются с SHA upstream. Каталоги не изменяются при запросе агента. Item groups и generic entries раскрываются до конкретных предметов; отсутствие варианта не превращается в пустую награду.

## Пять инструментов

search_rules возвращает исходные фрагменты; lookup_monsters — актуальные ограниченные XMM stat blocks; evaluate_encounter оценивает точный состав; build_encounter подбирает ограниченный состав, сохраняя все обязательные количества; generate_loot бросает реальные деньги/предметы XDMG. Арифметика и случайность находятся в Python, агент выбирает последовательность вызовов и объясняет их результаты. Для группы добыча individual умножает один бросок; для hoard нужны CR владельца, уровень партии и тема. Полный список параметров и технические границы опубликованы в [game](../../src/dnd_rag/game/README.md).

## Память и компактизация

Собственный агент применяет LangChain SummarizationMiddleware при полном native input выше11000: порог включает system и пять tool schemas. Summary получает весь заменяемый prefix вместе с предыдущим summary; недавний suffix ориентирован на2048 tokens. Последний пользовательский запрос и все его вызовы/результаты защищены как одна операция. Пары tool call/result не разрываются. После прерванной операции отсутствующий результат закрывается явным ToolMessage error, без утверждения об исполнении.

Summary reserve1024 находится внутри общего completion reserve2048, safety256 остаётся отдельно. Payload самого summary проверяется по физическому окну16384. В установленном LangChain overflow-retry умеет удалять середину даже при trim_tokens_to_summarize=None; собственный summarizer отключает этот путь. Полный prefix либо отправляется целиком, либо возникает диагностическая ошибка. После summary повторно проверяется полный следующий body. Если текущая защищённая операция не помещается, приложение предлагает уменьшить выдачу или начать новый диалог; последние15 сообщений не подставляются скрыто.

Structured English summary сохраняет party, ограничения, обязательных существ, принятые составы, фактическую добычу, источники и открытые вопросы. Summary+recent позволяет продолжать обсуждение с исходными формулировками последних действий. Простое удаление старых сообщений теряло бы первые результаты бросков; отдельный fact store потребовал бы второй недоказанной модели извлечения и синхронизации. Summary также может потерять факт: гарантия касается полного входа и явных ошибок, а семантическую сохранность проверяет длинный сценарий. Исходный JSONL остаётся целиком; summary usage и Langfuse span относятся к вызвавшему его turn. Codex сохраняет собственную native compaction.

Summary отдельно сохраняет явно запрошенные сюжетные факты; конфликт между пользовательским требованием и предположением assistant остаётся открытым вопросом. Ответ summary с finish_reason=length/max_tokens не принимается как новая память: исходная история остаётся, статус summary_truncated объясняет причину.

## Общий запуск и терминал

application_stack сначала подтверждает readiness Qdrant/Langfuse, готовит pinned game catalog и index/retriever, дожидается завершения GPU-worker и только затем запускает GGUF. После readiness модели поднимаются loopback MCP8765 и Responses compatibility proxy8081; интерфейс получает готовый AgentService. RuntimeSession удерживает lock и владеет model process group. Uvicorn-потоки останавливаются в finally, чужие серверы не подхватываются. Docker/data остаются после выхода.

Rich/prompt_toolkit CLI использует тот же async service, history/completion и реальные AgentEvent. patch_stdout сохраняет ANSI Rich; обычные команды не разбирают терминальный текст для измерений. Runner работает через AgentReply и raw records. /status показывает последнее полное измерение input и отдельное server window; во время генерации счётчик не выдумывается.

## Проверяемые номера источников

MCP берёт session scope из программного X-DND-Session-Id; модель не задаёт его в аргументах. CitationRegistry сохраняет monotonic номера в `.runtime/citations/<session>.json` по паре index_id/chunk_id. Повторный поиск оставляет прежний номер, новый диалог начинает собственную нумерацию, summary не очищает registry. В tool payload добавляется компактная карта number→source_id/chunk_id; исходный текст уже находится в hits и не дублируется.

В конце ответа валидатор разрешает [n] только из фактических search results этого scope. AgentReply возвращает разрешённые sources с точным текстом, spans, hash и исходной attribution; неизвестные номера остаются предупреждением, без придуманной замены. Это проверка допустимости источника, а не доказательство, что он поддерживает каждое утверждение. CLI показывает компактный source block. При отсутствии transport scope поиск остаётся доступен, но source numbers не выдаются.

Полный raw ответ chat API, включая доступный reasoning_content, сохраняется рядом с generation и в Langfuse span raw-model-response с исходным response_id. Usage остаётся на generation, чтобы не считать его дважды. Отсутствующий отдельный reasoning token count не выдумывается.
