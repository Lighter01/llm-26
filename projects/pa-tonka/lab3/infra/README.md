# Локальная наблюдаемость

`langfuse.compose.yaml` основан на [официальном Compose v4.79.0](https://github.com/langfuse/langfuse/blob/v4.79.0/docker-compose.yml), лицензия MIT. Web/worker закреплены на 4.79.0; AI Gateway не включён. PostgreSQL, Redis и ClickHouse доступны только во внутренней сети. Web слушает loopback3000, S3 MinIO — loopback9090/9091. Данные находятся в именованных volumes проекта `dnd-rag-lab3`; Qdrant остаётся отдельным сервисом root Compose с bind `data/qdrant`.

```bash
docker compose --project-name dnd-rag-lab3 --env-file .env -f compose.yaml -f infra/langfuse.compose.yaml up -d --build langfuse-web langfuse-worker
```

`minio.Dockerfile` собирает официальный [MinIO RELEASE.2025-09-07T16-13-09Z](https://github.com/minio/minio/tree/RELEASE.2025-09-07T16-13-09Z) из исходного архива с SHA256. Лицензия AGPL-3.0 включается в образ; исходники общедоступны по ссылке. Причина локальной сборки: registry из upstream Compose вернул403, прежние официальные образы не найдены, binary download вернул410. Первый build требует сети и Go build stage; это не платный доступ. Роль и S3 API сохранены. Не заменяйте образ непроверенным сторонним mirror.

Для setup задайте NEXTAUTH_SECRET, ENCRYPTION_KEY (64hex), SALT и создайте локальный проект/SDK keys. Поддержана автоматическая инициализация через LANGFUSE_INIT_* в `.env`; секреты в Git не включаются. Остановка приложения сохраняет контейнеры/volumes. Явная остановка инфраструктуры: та же Compose-команда с `stop`; `down -v` удаляет данные и не входит в обычный запуск.

Langfuse4 работает в events_only: старые `/api/public/traces` read endpoints отвечают404. Чтение проверяется через SDK5 `api.observations.get_many` (v2) с bounded from/to timestamps; rows группируются по traceId. Dataset/run связи используют актуальный Experiments API. Реальная SDK-проверка отправки и чтения вложенных observations прошла; web health сообщает4.79.0.
