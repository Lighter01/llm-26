# Проверки MCP

`test_server.py` проверяет реальный FastMCP registry/serialization: search limit5/1/10, отбрасывание0/11 до encoder, сохранение raw text/provenance и отличие пустой выдачи от ошибки. `tests/agent/test_observability.py` с настоящим OTel exporter проверяет родительство turn→tool→retrieval без второго поиска. Живой StreamableHTTP транспорт проверяется отдельно.

Проверка полного registry вызывает все четыре игровые функции на независимом каталоге и различает unknown_monster/conflict. Реальный StreamableHTTP smoke всех5 прошёл на503 monsters/2297 items; не подменяется unit-тестом.

`test_citation_scope.py` проверяет программный transport scope, отсутствие model-параметра scope и реальный StreamableHTTP с двумя независимыми клиентами/повторными поисками.
