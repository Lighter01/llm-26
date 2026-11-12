# Оценивание retrieval

`evidence.py`: EvidenceSpan, EvidenceFact, EvidenceCase и проверка точного текста, хэша, координат и section attribution канонического корпуса. Формат не фиксирует число задач и не требует reference_answer.

`metrics.py`: `evaluate_question(case, hits, full_manifest)` и `aggregate_metrics`. Релевантность требует совпадения file/body hash и пересечения ≥ половины меньшего span. Precision@k делится на k даже при короткой выдаче; Recall — на релевантные chunks полного manifest; MRR@10 использует первый релевантный hit; EC объединяет пересечения без двойного учёта и усредняет независимые факты. Оцениваются фактические hits, повторный поиск ради оценки не выполняется.
