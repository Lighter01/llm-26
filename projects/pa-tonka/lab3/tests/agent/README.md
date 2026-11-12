# Проверки агента

`test_model.py` проверяет полный native count того же wire body, tools/template/reasoning options, неподдержанные effort, невалидный счётчик, parity usage и конфигурационные бюджеты. Live-модель запускается отдельно; unit transport не доказывает работу GPU/GGUF.

`test_observability.py` проверяет реальное OTel родительство и сохранение полного retrieval output через in-memory exporter без сети.
