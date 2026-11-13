# Локальный Langfuse

[langfuse.compose.yaml](langfuse.compose.yaml) основан на [официальном Compose v4.79.0](https://github.com/langfuse/langfuse/blob/v4.79.0/docker-compose.yml), лицензия MIT. Web и worker закреплены на 4.79.0; AI Gateway отключён.

## Компоненты и данные

| Компонент | Доступ / хранение |
| --- | --- |
| Langfuse Web | `http://127.0.0.1:3000`. |
| MinIO S3 / консоль | Loopback-порты `9090` / `9091`. |
| PostgreSQL, Redis, ClickHouse | Только внутренняя сеть Compose. |
| Данные Langfuse | Именованные volumes проекта `dnd-rag-lab3`. |
| Qdrant | Отдельный сервис корневого Compose, bind mount `data/qdrant/`. |

## Настройка и запуск

В `.env` задайте `NEXTAUTH_SECRET`, `ENCRYPTION_KEY` (64 шестнадцатеричных символа), `SALT` и ключи локального проекта. Автоматическая инициализация поддерживается через `LANGFUSE_INIT_*`; секреты не включаются в Git.

```bash
docker compose --project-name dnd-rag-lab3 --env-file .env -f compose.yaml -f infra/langfuse.compose.yaml up -d --build langfuse-web langfuse-worker
```

Для остановки инфраструктуры замените `up -d --build langfuse-web langfuse-worker` на `stop`. Выход из приложения сохраняет контейнеры и volumes. `down -v` удаляет данные и не относится к обычной остановке.

## Почему MinIO собирается локально

[minio.Dockerfile](minio.Dockerfile) собирает официальный [MinIO RELEASE.2025-09-07T16-13-09Z](https://github.com/minio/minio/tree/RELEASE.2025-09-07T16-13-09Z) из архива с проверкой SHA256. Лицензия AGPL-3.0 включается в образ; исходники доступны по ссылке.

При подготовке окружения registry из upstream Compose вернул HTTP 403, прежние официальные образы оказались недоступны, загрузка бинарника вернула HTTP 410. Поэтому используется закреплённый исходный код с тем же S3 API. Первая сборка требует сети и Go build stage; платного доступа нет.

## Совместимость API

Langfuse 4 работает в `events_only`: прежние `/api/public/traces` read endpoints возвращают HTTP 404. Чтение выполняется через SDK 5 `api.observations.get_many` (v2) с ограниченным временным диапазоном; записи группируются по `traceId`. Связи dataset/run используют Experiments API.

Фактические отправка, вложенность и API-readback проверены; результаты — в [VALIDATION](../docs/rag/VALIDATION.md). Отличия служебных полей Experiments от метрик агента объяснены в [EVALUATION](../docs/user_docs/EVALUATION.md#как-читать-langfuse).
