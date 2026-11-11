# Runtime

- `lock.py`: ProjectLock — неблокирующий flock на стабильном `.runtime/project.lock`. Файл не удаляется, PID не подменяет OS lock.
- `processes.py`: RuntimeSession — держит lock, запускает свои process groups с наследуемым descriptor и ждёт завершения группы, включая потомков после выхода wrapper. TERM-ignoring остатки получают KILL. После выхода лидера владение проверяется по унаследованной FLOCK-записи в Linux /proc, а не по одному старому PGID/пути lock. Смерть родителя не освобождает защиту, пока descriptor остаётся у живого ребёнка.
- `preflight.py`: общая нормализация native LLM URL и распознавание подтверждённого ECONNREFUSED сквозь httpx/httpcore/Qdrant wrappers. Timeout/DNS/protocol/неопределённая ошибка не означают отсутствие сервиса.
- `application.py`: mode-specific Qdrant preflight, `ensure_index` и `reset_index`. Ready-путь не импортирует document encoder. Полная сборка — отдельный GPU worker, сериализованный запрос/события/результат в `.runtime/builds/<uuid>/`.
- `serve_retrieval`/`run_demo`: один API worker в том же процессе, один CPU encoder; demo запускает LLM после GPU-подготовки и HTTP-only Streamlit после readiness API. События/паспорт/stage timings — `.runtime/startup.json`, журнал UI — `.runtime/ui.log`.
- `llama.py`: явный argv из LLMProfile, model/template hashes и readiness установленного llama.cpp. Чужой endpoint даёт конфликт; своих детей останавливает RuntimeSession.

Qdrant — постоянный сервис, не держит runtime lock и не останавливается при выходе. Compose хранит его данные в `data/qdrant/` проекта через bind mount; отдельного named volume и настройки `QDRANT_STORAGE_VOLUME` больше нет. Размещение GPU освобождается завершением worker до query/LLM. [Руководство](../../../docs/user_docs/CLI.md).
