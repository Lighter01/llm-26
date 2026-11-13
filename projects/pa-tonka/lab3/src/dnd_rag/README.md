# Пакет dnd_rag

Локальный DM-помощник: самостоятельный RAG, диалоговый агент и общий MCP с игровыми инструментами. CLI и измерительный runner используют те же программные сервисы. Импорт настроек и контрактов не загружает модели.

| Файл / пакет | Ответственность |
| --- | --- |
| [\_\_main\_\_.py](__main__.py), [cli.py](cli.py) | Аргументы запуска и интерактивный Rich/prompt_toolkit чат. |
| [config.py](config.py), [contracts.py](contracts.py) | Строгие схемы, разрешение путей, общие результаты и `RagError`. |
| [agent/](agent/README.md) | `AgentService`, память, лимиты, traces, источники и reply/event contracts. |
| [tools/](tools/README.md) | StreamableHTTP MCP для обоих агентов. |
| [game/](game/README.md) | Проверенный каталог, расчёт встреч и фактические броски добычи. |
| [indexing/](indexing/README.md) | Корпус/source_map, чанки, GPU-эмбеддинги и Qdrant. |
| [retrieval.py](retrieval.py) | `Retriever.retrieve(question, limit)` → ранжированные исходные chunks. |
| [runtime/](runtime/README.md) | Общий lifecycle, lock, GPU-worker, LLM и protocol proxy Codex. |
| [experiments/](experiments/README.md) | Codex exec/resume, датасет, runner, scoring и артефакты. |
| [evaluation/](evaluation/README.md) | Независимые evidence-контракты и retrieval-метрики. |
| [ingestion/](ingestion/README.md) | Подготовка канонических книг. |

`runtime.index.prepare_retriever(config, settings, session)` подготавливает поиск один раз; последующие запросы переиспользуют CPU encoder. Retrieval не читает эталоны или старые результаты и не зависит от LLM/интерфейса.

Порядок запуска и подробная [карта кода](../../docs/user_docs/ARCHITECTURE.md#карта-кода) описаны в пользовательской архитектуре. Пакеты содержат локальные README со своими интерфейсами и ограничениями.
