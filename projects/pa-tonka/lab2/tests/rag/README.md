# RAG tests

```bash
uv run --group test python -m pytest tests/rag
uv run --group test python -m pytest tests/rag/integration/test_embedding_live.py --run-models
uv run --group test python -m pytest tests/rag/integration/test_qdrant_live.py --run-qdrant
uv run --group test python -m pytest tests/rag/integration/test_llama_live.py --run-llama
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

`test_context`/`test_citations`/`test_qa_service` проверяют бюджет полного prompt,
целые удаления, frozen registry, Markdown exclusions и один generate. `test_api`
проверяет строгие входы, error envelope, readiness, stateless и 429 при занятой QA.
`test_launcher` повторяет parent-death/cleanup с реальными Uvicorn/Streamlit,
без моделей; `test_ui` использует Streamlit AppTest и fake HTTP. Живой Nemotron
проверяет точный count/usage и установленный chat template; его запуск держит lock.

`test_qa_run` проверяет запись фактических messages/registry без второго retrieval,
not_reviewed поля, раздельные20/3, partial failed-run и защиту правок CSV.
`test_study` проверяет точные дельты10 полных YAML, выбранные completed references,
offline cohorts/failed/reuse; CLI-test доказывает,что summary не читает runtime settings.
