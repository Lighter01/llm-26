# Управление локальным запуском

`index.py` отвечает за `ensure_index`, `prepare_retriever`, `reset_index`, запуск/reuse Qdrant и GPU build-worker. Worker полностью завершается перед возвратом; ready-reuse не загружает document encoder. `application.py` — точка композиции будущего общего запуска. `llama.py` и `llm.py` содержат изолированные примитивы локальной LLM и не импортируются retrieval-ядром.

`processes.py` предоставляет `RuntimeSession`: одна блокировка проекта, наследование lock descriptor дочерними процессами, группы процессов и cleanup только принадлежащих запуску процессов. `lock.py` реализует блокировку; `preflight.py` различает отказ соединения и неопределённую сетевую ошибку. При timeout нельзя считать endpoint свободным. Контейнеры и их данные после выхода сохраняются.

`codex_proxy.py` — узкий loopback compatibility adapter8081/v1/responses для установленного Codex0.167: его additional_tools/namespace формат несовместим с llama build11046. Схемы пяти MCP tools переносятся в root tools, имена преобразуются обратимо в histories/SSE; исходные сообщения и tool results сохраняются. Общий LLM profile задаёт thinking/output limit, native full-payload count проверяется с upstream usage. Original/effective bodies и ответы — `.runtime/codex-wire/<session>/wire.jsonl`. Агентный цикл и native compaction остаются внутри Codex.
