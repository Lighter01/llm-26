# Runtime

- `lock.py`: ProjectLock — неблокирующий flock на стабильном `.runtime/project.lock`.
  Файл не удаляется, PID не подменяет OS lock.
- `processes.py`: RuntimeSession — держит lock, запускает свои process groups с
  наследуемым descriptor, завершает их перед освобождением lock. Смерть родителя
  не освобождает защиту, пока descriptor остаётся у живого ребёнка.
- `application.py`: mode-specific Qdrant preflight, `ensure_index` и `reset_index`.
  Ready-путь не импортирует document encoder. Полная сборка — отдельный GPU worker,
  сериализованный запрос/события/результат в `.runtime/builds/<uuid>/`.

Qdrant — постоянный сервис, не держит runtime lock и не останавливается при выходе.
Размещение GPU освобождается завершением worker до query/LLM. Launcher LLM/API/UI
добавляется в следующих задачах. [Руководство](../../../docs/user_docs/CLI.md).
