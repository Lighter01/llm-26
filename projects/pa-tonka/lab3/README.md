# Исходная основа лабораторной 3

Полная исходная копия проекта второй лабораторной, включая исходники, тесты, документацию, отчёт, результаты и локальные материалы. Отчёт, графики, экспериментальные snapshots и их fingerprints относятся к lab2; это не новые измерения lab3. Параметры подключения в текущем коде уже отличаются от исторических входов отчёта.

Для будущего RAG выбрана **R3 / `g1_source_map_recursive`**: [конфиг](configs/experiments/g1_splitters/source_map_recursive.yaml), dense, source_map recursive до H4, размер 512 токенов, overlap 64, title=true, strip=false, размерность 768. Параметры совпадают со Study и сохранённым run.

Qdrant lab3 изолирован: Compose project `dnd-rag-lab3`, HTTP `127.0.0.1:6343`, gRPC `127.0.0.1:6344`, собственный bind mount `./data/qdrant:/qdrant/storage`. Хранилище lab2 не скопировано; контейнеры, коллекции и индекс lab3 ещё не создавались. Следующий агент подготовит окружение по новому пути, создаст коллекцию и выполнит адаптацию под MCP. Перенесённое Python-окружение не настроено для нового пути. Локальная агентская среда перенесена без изменения инструкций и навыков.

Ниже сохранено описание реализованного проекта lab2 и его результатов.

# D&D RAG

Локальная система поиска правил по трём книгам D&D: Player’s Handbook (2024), Dungeon Master’s Guide (2024), Monster Manual (2025). Python ≥3.13, uv, LangChain splitters, EmbeddingGemma 2, Qdrant в Docker.

Сервис ищет фрагменты правил в Qdrant и передаёт их локальной Nemotron для ответа с цитатами. Векторы фрагментов книг вычисляются на GPU, векторы вопросов — на CPU. Доступны FastAPI и интерфейс Streamlit. Выполнены 10 поисковых экспериментов и [финальный прогон по 20 вопросам](results/qa_final/qa_summary.json). Разработка и независимое ревью завершены. [Отчёт](report/LAB2_REPORT.md) готов; [agent-assisted рецензия QA20](results/qa_final/qa_review.csv) заполнена: 15 корректных, 4 частично корректных и 1 некорректный ответ. Команды повторяемых проверок и границы оценки приведены в документации.

Для демонстрации выбран плотный поиск: границы разделов берутся из `source_map` до H4, размер чанка — до 512 токенов, перекрытие — 64 токена. Путь заголовков передаётся эмбеддеру, исходные заголовки сохранены в тексте. Получено 5578 чанков. На 20 эталонных вопросах Evidence Coverage@5 = 0.9700, MRR@10 = 0.9750. Эти показатели оценивают поиск. В финальном QA-прогоне медиана времени ответа после первого запроса составила 2.71 с, максимум — 4.29 с; структурных предупреждений не было. [Сравнение 10 конфигураций](docs/rag/EXPERIMENTS.md) · [Приёмка, QA20 и материалы для отчёта](docs/rag/VALIDATION.md).

```bash
uv sync --group test --group lint
cp -n .env.example .env
uv run python -m dnd_rag demo \
  --config configs/experiments/g1_splitters/source_map_recursive.yaml --llm-profile configs/llm/local.yaml
# UI: http://127.0.0.1:8501; Ctrl+C останавливает demo.
uv run --group test python -m pytest -m 'not integration'
uv run --group lint ruff check src tests
```

Перед запуском укажите в `.env` путь к llama.cpp (`LLAMA_SERVER_BIN`) и файлу весов GGUF. Для построения нового индекса нужны GPU с поддержкой CUDA и работающий Docker; готовую совместимую коллекцию сервис использует повторно. Данные Qdrant хранятся внутри проекта в `data/qdrant/` через bind mount и исключены из Git. Демо открывает UI на порту 8501, API — на порту 8000. Для каждого эксперимента нужно новое имя каталога в `results/`. Команда полного набора тестов с явным путём к подготовленной сборке книг приведена в руководстве по CLI.

[Пользовательская документация](docs/user_docs/README.md) · [Архитектура](docs/user_docs/ARCHITECTURE.md) · [CLI/настройки](docs/user_docs/CLI.md) · [Конфиги](configs/experiments/README.md) · [Технические пробы](docs/rag/TECHNICAL_PROBES.md) · [Исходники](src/dnd_rag/README.md) · [Тесты](tests/README.md).

Готовая подготовка данных: [команды ingestion](src/dnd_rag/ingestion/README.md), [сборщик](src/dnd_rag/ingestion/book_assembly/README.md), [экспорт Markdown](src/dnd_rag/ingestion/markdown_export/README.md), [валидатор вопросов](src/dnd_rag/ingestion/question_validation/README.md), [техническая документация](docs/ingestion/README.md), [инструменты](tools/README.md).
