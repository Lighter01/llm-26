# Рабочие RAG-профили

`r3.yaml` — default, `r9.yaml` выбирается `RAG_CONFIG_PATH=configs/rag/r9.yaml` в `.env`. Они отличаются только `embedding.strip_markdown_headings`: false/true. Оба используют source_map_recursive H4, 512/64, заголовки embedding title, EmbeddingGemma 2 revision `f9972ac22e696a105c482202646979e33e4b5a1e`, 768d, dense/HNSW 16/100, ef_search=128, retrieval.limit=10.

R3 выбран как исходная конфигурация; качество нового приложения проверяется новым набором. Путь YAML и параметры оценивания не определяют индекс. Corpus hash, source_map, embedding input, chunking и версии библиотек входят в build identity. Strip меняет identity даже при одинаковых spans. Неверный файл приводит к ошибке, скрытого отката к R3 нет.

Схемы полей и диапазоны задаёт `config.py`: chunk_size 100..1000; overlap меньше chunk_size; heading 1..6; размерности 128/256/512/768; dense/hybrid; quantization none/scalar_int8/turboquant_4bit. Сохраняемые дополнительные поисковые режимы не являются новыми измеренными профилями. Gold/evaluation в рабочем YAML отсутствуют.
