# Проверки агента

`test_model.py` проверяет полный native count того же wire body, tools/template/reasoning options, неподдержанные effort, невалидный счётчик, parity usage и конфигурационные бюджеты. Live-модель запускается отдельно; unit transport не доказывает работу GPU/GGUF.

`test_observability.py` проверяет реальное OTel родительство и сохранение полного retrieval output через in-memory exporter без сети.

`test_memory.py` проверяет полный prefix, повторное summary, защищённую задачу, явные ошибки и учёт потреблённого usage отклонённого summary. `test_cli.py` проверяет команды/измеренный context; `test_application.py` — порядок стадий и отсутствие downstream при сбое. `integration/test_context_live.py` — явная длинная проверка обоих агентов на работающем общем stack.

`test_citations.py` — повторные hits, независимые диалоги, сохранение registry после summary/restart, неизвестные номера и точная исходная attribution без выдуманной страницы.

`test_service.py` дополнительно проверяет реальные LangGraph parallel-task pending writes при timeout, сохранение уже полученных 19 gp, incomplete для final finishlength и unknown totals после прерванной второй генерации.
