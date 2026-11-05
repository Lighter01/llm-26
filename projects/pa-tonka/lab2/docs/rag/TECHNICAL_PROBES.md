# Технические пробы

2026-11-05, Europe/Moscow. Реализация Tasks 1–8. Непроведённые проверки не считаются PASS.

| Проверка | Наблюдение |
| --- | --- |
| Python / uv | system 3.13.1; uv 0.11.6. Project interpreter уточняется после sync. |
| CUDA | Elevated nvidia-smi: RTX 3060 Laptop, 6144 MiB; driver 617.42, CUDA UMD 13.4. Sandbox NVML недоступен. |
| Docker | CLI 29.9.2; Desktop initially stopped; `docker desktop start` выполнен. |
| LLM | GGUF существует, 5060482240 bytes. llama-server не в PATH. Task 9 probe ещё не выполнена. |
| Model / tokenizer revision | `hf models info google/embeddinggemma-2 --expand sha --format json`: f9972ac22e696a105c482202646979e33e4b5a1e. |
| Qdrant | Выбран server/client 1.20.0; живые BM25/quantization/persistence ещё не проверены. |

Закреплённые API: [EG2 card](https://huggingface.co/google/embeddinggemma-2),
[Qdrant 1.20.0](https://github.com/qdrant/qdrant/releases/tag/v1.20.0),
[native full-text BM25](https://qdrant.tech/documentation/search/text-search/full-text-search/),
[quantization](https://qdrant.tech/documentation/manage-data/quantization/).
Версии Python-пакетов закрепляются uv.lock; измерения живого адаптера ниже по мере выполнения.
