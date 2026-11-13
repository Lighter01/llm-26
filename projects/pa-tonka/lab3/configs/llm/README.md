# Профили локальной модели

Оба агента используют один GGUF и общий профиль сервера. Профиль выбирается через `--llm-profile`; отдельные внутренние инструкции и управление историей остаются свойствами агентов.

## Режимы генерации

| Файл | Thinking | Бюджет reasoning |
| --- | --- | --- |
| [off.yaml](off.yaml) | Выключен. | 0. |
| [budgeted.yaml](budgeted.yaml) | Включён. | 512 токенов на распознанный thinking block. |

Общий `max_output_tokens=2048` включает reasoning и финальный ответ. Можно задать 1024 в копии YAML, но бюджет одного блока не является строгим суммарным пределом всех блоков. Native effort `low/minimal` выбранные templates не поддерживают; схема их отвергает.

## Окно и параметры сервера

Серверное окно — **16 384**, резерв ответа — **2 048**, safety margin — **256** токенов. Допускается только полный запрос, для которого `input + output reserve + safety <= server window`. Порог сокращения истории агента 9 500 настраивается отдельно; причины ошибок после summary объяснены в [архитектуре](../../docs/user_docs/ARCHITECTURE.md#как-заменяется-история).

В обоих файлах: GPU layers 99, batch/ubatch 512/128, KV q8_0, flash attention on, temperature 0 и seed 42. Возможность размещения проверяется live-пробой. Чужой endpoint launcher не завершает и не использует без полной верификации профиля.

## Модель и исполняемый файл

| Переменная | Значение / назначение |
| --- | --- |
| `LLM_MODEL_PATH` | Основная модель: `~/hf_models/gemma/nemotron/nemotron-3.5/bolt/NVIDIA-Nemotron-3.5-Bolt-E4B-UD-Q4_K_XL.gguf`. |
| `LLAMA_SERVER_BIN` | Путь к llama.cpp; установленный build 11046 запускается с `server_subcommand=serve`. |

Согласованный fallback — `~/hf_models/gemma/gemma4/gemma-4-E2B-it-Q4_K_M.gguf`. Переход на него требует повторить все четыре измерения.

## Полный подсчёт входа

[runtime.llm.NativeLLM](../../src/dnd_rag/runtime/llm.py) — HTTP-обёртка над llama.cpp, а не ещё одна модель. Она считает фактический полный JSON родным токенайзером GGUF через `/v1/chat/completions/input_tokens`; Responses использует `/v1/responses/input_tokens`.

Только при подтверждённом отсутствии Chat count route разрешён fallback apply-template/tokenize с тем же body. Таймаут или невалидный count считаются ошибкой. При реальной генерации число входных токенов сверяется с серверным usage; несовпадение не скрывается. Определения [payload](../../docs/user_docs/GLOSSARY.md#payload) и [usage](../../docs/user_docs/GLOSSARY.md#usage) собраны в глоссарии.
