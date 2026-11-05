# RAG tests

```bash
uv run --group test python -m pytest tests/rag
uv run --group test python -m pytest tests/rag/integration/test_embedding_live.py --run-models
uv run --group test python -m pytest tests/rag/integration/test_qdrant_live.py --run-qdrant
```

Unit tests используют малые LF-книги, fake encoders/client и реальные короткие
subprocesses для lock/parent death/cleanup. По умолчанию live tests skip до setup.
Модельная проба только split/tokenize полного корпуса и ограниченные GPU/CPU embeddings;
она не векторизует все книги. Qdrant-проба использует собственные disposable collections
и fixed vectors, проверяет три quantization режима, BM25/RRF и restart persistence.
Индекс baseline и результаты не удаляются. Запускайте живые пробы последовательно,
когда другой runtime проекта остановлен.

`test_metrics.py` содержит независимые математические fixtures. `test_retrieval_run.py`
проверяет сохранность failed-run, отсутствие новых index side effects при повторном
имени и пересчёт метрик из artifacts после отключения fake store.
