# Управление локальным запуском

`index.py` отвечает за `ensure_index`, `prepare_retriever`, `reset_index`, запуск/reuse Qdrant и GPU build-worker. Worker полностью завершается перед возвратом; ready-reuse не загружает document encoder. `application.py` — точка композиции будущего общего запуска. `llama.py` и `llm.py` содержат изолированные примитивы локальной LLM и не импортируются retrieval-ядром.

`processes.py` предоставляет `RuntimeSession`: одна блокировка проекта, наследование lock descriptor дочерними процессами, группы процессов и cleanup только принадлежащих запуску процессов. `lock.py` реализует блокировку; `preflight.py` различает отказ соединения и неопределённую сетевую ошибку. При timeout нельзя считать endpoint свободным. Контейнеры и их данные после выхода сохраняются.
