# DM-помощник — лабораторная 3

Локальное приложение для работы Dungeon Master с правилами D&D 2024/2025. Работают автономное retrieval-ядро, пять общих MCP-инструментов, программный LangChain AgentService и Codex exec/resume с локальным Langfuse. Работают игровой каталог, память с native budgets и единый интерактивный запуск. Нумерованные retrieval sources сохраняются между поисками и summary. Runner исполняет общий фиксированный dataset и сохраняет формальные scores и отдельную worksheet смысловой оценки.

## Быстрый старт

Нужны Python 3.13+, uv 0.11.6, Docker Compose, Node.js 22+ для подготовки книг. Скопируйте `.env.example` в `.env` и задайте пути окружения.

```bash
uv sync --group test --group lint
npm --prefix tools/ingestion ci
uv run python -m dnd_rag build-index
uv run python -m dnd_rag inspect-index
uv run python -m dnd_rag run --interface cli --llm-profile configs/llm/off.yaml
```

Перед чатом настройте локальный [Langfuse](infra/README.md) и [Codex baseline](configs/baseline/README.md). Launcher проверяет сервисы, готовит каталоги и индекс, затем запускает модель и MCP. В чате доступны `/help`, `/new`, `/status`, `/exit`.

Индекс строится GPU worker с EmbeddingGemma 2; повторный совместимый запуск использует готовую коллекцию. Запросы кодируются на CPU. Qdrant 1.20.0 изолирован в Compose `dnd-rag-lab3`, порты 6343/6344, данные `data/qdrant`. Корпус и source_map сохраняются без пересборки. Подготовка после clone описана в [ingestion](docs/ingestion/README.md).

## Карта проекта

| Каталог | Ответственность |
|---|---|
| `src/dnd_rag` | Retrieval, индексация, управление процессами и ingestion |
| `configs/rag` | Самостоятельные R3/R9 |
| `configs/llm` | Профили локальной модели |
| `data` | Локальные входы и генерируемые данные |
| `external/5etools-src` | Закреплённый upstream, не изменяется |
| `tests` | Проверки ядра, подготовки книг и процессов |
| `tools/ingestion` | Node runtime подготовки книг |
| `docs` | [Пользовательское руководство](docs/user_docs/README.md), архитектура и ingestion |
| `scripts` | Административные вспомогательные команды |

## Проверки

```bash
uv run --group test python -m pytest -m 'not integration and not rag_models and not rag_qdrant and not rag_llama'
uv run --group lint ruff check src tests
npm --prefix tools/ingestion run test:unit
```

Live-пробы запускаются явно и не подменяются результатами предыдущей лабораторной. Команды и все параметры: [CLI](docs/user_docs/CLI.md).
