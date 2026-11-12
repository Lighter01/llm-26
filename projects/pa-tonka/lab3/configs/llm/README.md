# Профили локальной модели

`off.yaml` — thinking выключен; `budgeted.yaml` — включён, стартовый бюджет 512 токенов на распознанный thinking block. Можно задать 1024 в копии YAML; общий completion limit 2048 включает reasoning и ответ. Это не строгий суммарный cap всех блоков. Native effort low/minimal у выбранных templates не поддерживается; схема отвергает их.

Общие значения: сервер 16384, резерв 2048, safety 256; GPU layers 99, batch/ubatch 512/128, KV q8_0, flash attention on, temperature 0, seed 42. Реальная возможность размещения проверяется live-пробой. Чужой endpoint launcher не завершает и не использует без полной верификации профиля.

Путь основной модели задаётся `LLM_MODEL_PATH`: `~/hf_models/gemma/nemotron/nemotron-3.5/bolt/NVIDIA-Nemotron-3.5-Bolt-E4B-UD-Q4_K_XL.gguf`. Согласованный fallback: `~/hf_models/gemma/gemma4/gemma-4-E2B-it-Q4_K_M.gguf`; переход требует повторить все четыре измерения. Binary в `LLAMA_SERVER_BIN`; установленный build11046 запускается с server_subcommand=serve.

`runtime.llm.NativeLLM` считает фактический полный OpenAI JSON через native `/v1/chat/completions/input_tokens`; Responses-пробы используют `/v1/responses/input_tokens`. Только при подтверждённом отсутствии chat count route разрешён apply-template/tokenize с тем же body. Timeout/невалидный count — ошибка. Реальная генерация сверяет prompt usage со счётчиком; несовпадение не скрывается.
