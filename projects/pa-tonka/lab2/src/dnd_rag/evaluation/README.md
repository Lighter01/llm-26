# Evaluation

- `gold.py`: `load_gold(path, corpus, report_path) -> GoldSet`; строгие schema,
  matching PASS report, hashes, exact evidence/section/line/char ranges.
  20 answerable и 3 insufficient хранятся раздельно.
- `metrics.py`: чистые `evaluate_question` и `aggregate_metrics`. Relevance считается
  по всему manifest, EC — union top-k → best alternative → mean facts/questions.
  Никаких моделей, сети, fuzzy match или автоматического semantic judge.

Метрики используют body Unicode ranges, а не названия sections или актуальные chunk IDs
из gold. Manifest пересчитывается для каждого индекса. [Формулы и поток](../../../docs/user_docs/ARCHITECTURE.md).
