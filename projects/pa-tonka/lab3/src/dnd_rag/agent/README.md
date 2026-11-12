# Агентные контракты

`config.py` — AgentConfig: порог контекста 8192, recent 2048, summary 1024, 12 model calls, 16 tool calls, 300 секунд на реплику и адрес общего MCP. Экспортирует общий LLMProfile без второго набора параметров.

`contracts.py` — сериализуемые AgentReply, ContextStats и AgentEvent для CLI/runner. Неизвестный input_tokens равен None, а не нулю. Интерактивный агент и память подключаются следующими задачами.
