# Проверки MCP

`test_server.py` проверяет реальный FastMCP registry/serialization: search limit5/1/10, отбрасывание0/11 до encoder, сохранение raw text/provenance и отличие пустой выдачи от ошибки. `tests/agent/test_observability.py` с настоящим OTel exporter проверяет родительство turn→tool→retrieval без второго поиска. Живой StreamableHTTP транспорт проверяется отдельно.
