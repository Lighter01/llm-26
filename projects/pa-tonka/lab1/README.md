# Лабораторная работа №1 - эмпирический анализ локальных LLM

## Использованные модели

| Model Family | Model Name          | Model Version     | Link                                                          |
|--------------|---------------------|-------------------|---------------------------------------------------------------|
| Qwen         | Qwen3.5-4B          | Q4_K_M            | [hf](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF)          |
| Gemma        | Gemma-4-E2B-it      | Q4_K_M            | [hf](https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF)      |
| Phi          | Phi-4-mini-instruct | Q4_K_M            | [hf](https://huggingface.co/unsloth/Phi-4-mini-instruct-GGUF) |

Не стал брать Bartkoswki-квантизацию в основном из-за фиксов в модели phi4. Хотя Bartkowski для прямого сравнения методологически более корректный выбор.

Quantization Aware Training - QAT - не стал рассматривать для более прямого и объективного сравнения.

Данные для классификации: https://huggingface.co/datasets/blinoff/kinopoisk/

