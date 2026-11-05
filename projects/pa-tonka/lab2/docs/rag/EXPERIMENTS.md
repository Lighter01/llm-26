# Сравнение retrieval: C4

Эксперименты используют один validated gold из20 основных вопросов и один corpus
XPHB/XDMG/XMM. Метрики не оценивают смысловую правильность ответов LLM. Основной
приоритет выбора: Evidence Coverage@5, затем MRR@10 и затраты/объём. Каждый YAML
полный; контрольные runs включаются по ссылке без повторной индексации.

## G1 — splitter

| Run | EC@5 | MRR@10 | P@5 | R@5 | Чанков | Raw tokens@5, mean | Весь run, s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [g1_markdown_initial](../../results/g1_markdown_initial/run.json) | 0.8417 | 0.7375 | 0.2900 | 0.7485 | 3175 | 1930.85 | 133.06 |
| [g1_recursive](../../results/g1_recursive/run.json) | 0.8075 | 0.7450 | 0.2700 | 0.7267 | 2848 | 2156.85 | 133.13 |
| [g1_source_map_recursive](../../results/g1_source_map_recursive/run.json) | 0.9700 | 0.9750 | 0.3700 | 0.8979 | 5578 | 1099.45 | 178.91 |

Для G2 выбран **source_map_recursive H4,512/64,title=true,strip=false**. Относительно
Markdown EC@5 вырос с.841667 до.9700, MRR@10 с.7375 до.9750. Покрытие выросло
на phb_04,dmg_02,multi_02,multi_05, ухудшений нет,16 вопросов без изменения.
Средний raw context первых5 hits снизился с1930.85 до1099.45 токенов эмбеддера.
Цена —5578 вместо3175 points и178.91s вместо133.06s всего run. Качество по обоим
приоритетным критериям выше; больший индекс не создаёт неоднозначности выбора.

Recursive по книге экономит points, но теряет EC на phb_02/multi_03 и улучшает
только multi_05. Более высокий MRR.745 не компенсирует EC.8075 по принятому
приоритету. Полные дельты по20 вопросам: [анализ G1](../../.agents/work/implementation/c4-g1.json).

Число релевантных чанков Rq пересчитывается по manifest каждого индекса, поэтому
Recall при разном разбиении имеет разные знаменатели. EC привязан к фактам/evidence
spans, а raw_tokens@k показывает объём выбранного контекста. Это embedding tokens,
не точный LLM token budget. Одна малая выборка используется и для выбора профиля;
статистическая общность и улучшение QA по этим цифрам не утверждаются.

G3–G5 завершены после обновления полных профилей по фактическим выбранным базам.

## G2 — размер и overlap

| Run | EC@5 | MRR@10 | Чанков | Raw tokens@5, mean | Весь run, s |
| --- | --- | --- | --- | --- | --- |
| [g1_source_map_recursive](../../results/g1_source_map_recursive/run.json) | 0.9700 | 0.9750 | 5578 | 1099.45 | 178.91 |
| [g2_overlap_128](../../results/g2_overlap_128/run.json) | 0.9700 | 0.9500 | 5608 | 1183.90 | 181.52 |
| [g2_size_768](../../results/g2_size_768/run.json) | 0.9100 | 1.0000 | 4703 | 1352.30 | 195.59 |

Dense-базой для G3/G5 остаётся **g1_source_map_recursive,512/64**. У overlap128
все20 EC@5 совпали с контролем, но MRR ниже и raw context больше. Size768 теряет
EC на multi_01,multi_03,multi_05, не улучшая EC ни одного вопроса; его MRR1.0
показывает, что наличие первого релевантного чанка не обеспечивает полноту
нескольких фактов. Контроль выигрывает по принятому приоритету EC и расходу
контекста. Полный [анализ G2](../../.agents/work/implementation/c4-g2.json).

## G3 — dense/hybrid

| Run | EC@5 | MRR@10 | Raw tokens@5, mean | Весь run, s |
| --- | --- | --- | --- | --- |
| [g1_source_map_recursive](../../results/g1_source_map_recursive/run.json) | 0.9700 | 0.9750 | 1099.45 | 178.91 |
| [g3_hybrid](../../results/g3_hybrid/run.json) | 0.9467 | 0.9750 | 1187.85 | 194.46 |

Добавление native BM25/RRF на этой выборке снижает EC:улучшение multi_05,
ухудшения multi_02/multi_03,17 вопросов без изменения. Полный [анализ G3](../../.agents/work/implementation/c4-g3.json).
BM25 построен отдельным измеренным шагом после upload:1.168s; используется raw
page_content,20 кандидатов каждой ветви,RRF=2, равные веса, без threshold/rescore.
Обе вариации G4 по программе сравниваются именно с этой hybrid-базой, даже при
более высоком EC dense-контроля. G5 сохраняет исходную dense-базу.

## G4 — два независимых индексных профиля

| Run | EC@5 | MRR@10 | Raw tokens@5, mean | Весь run, s |
| --- | --- | --- | --- | --- |
| [g3_hybrid](../../results/g3_hybrid/run.json) | 0.9467 | 0.9750 | 1187.85 | 194.46 |
| [g4_hnsw_32_200_256](../../results/g4_hnsw_32_200_256/run.json) | 0.9467 | 0.9750 | 1199.30 | 181.80 |
| [g4_bm25_no_stem](../../results/g4_bm25_no_stem/run.json) | 0.9600 | 0.9750 | 1294.25 | 184.58 |

Каждая строка-вариант сравнивается с g3_hybrid, не с другой вариацией G4.
HNSW32/200/256 не меняет EC@5/MRR@10. No-stem включает одновременно stemmer=null,
k1=1.5,b=.5, сохраняя исходный HNSW16/100/128 и остальные BM25/RRF параметры.
Это сравнение составных профилей, не изолированное доказательство влияния одного
из трёх полей. Детали20 вопросов — [анализ G4](../../.agents/work/implementation/c4-g4.json).

## G5 — embedding headings на dense-базе

| Run | EC@5 | MRR@10 | Raw tokens@5, mean | Весь run, s |
| --- | --- | --- | --- | --- |
| [g1_source_map_recursive](../../results/g1_source_map_recursive/run.json) | 0.9700 | 0.9750 | 1099.45 | 178.91 |
| [g5_title_strip](../../results/g5_title_strip/run.json) | 0.9700 | 0.9750 | 1128.85 | 186.26 |
| [g5_no_title_keep](../../results/g5_no_title_keep/run.json) | 0.9533 | 0.9250 | 972.30 | 168.39 |

Title_strip (true/true) сохраняет EC@5 всех20 вопросов и MRR контроля, но средний
raw context немного больше. No_title_keep (false/false) сокращает контекст, но
ухудшает EC на multi_02 и снижает MRR. Оба профиля — dense, без BM25; меняется
только производный embedding input. Полный [анализ G5](../../.agents/work/implementation/c4-g5.json).

## Выбранный профиль для QA20

**g1_source_map_recursive: dense,source_map_recursive H4,512/64,title=true,strip=false.**
EC@5=.9700,MRR@10=.9750,5578 чанков,raw_tokens@5=1099.45 в среднем. По основному
критерию он делит первое место с overlap128/title_strip; первый уступает по MRR,
а второй при тех же EC@5 на всех20 вопросах имеет больший raw context. Преимущества по EC@5/MRR@10
у strip нет, поэтому сохраняется исходный H4 профиль. EC@10 у strip выше (.9900 против .9700; multi_05: .6→1.0), но QA по контракту получает
максимум5 первых чанков, поэтому это улучшение сохраняется в сравнении и не меняет
выбор по EC@5/MRR@10. Hybrid и варианты G4
не превзошли этот dense-контроль. Явной неоднозначности по принятому порядку нет.

Полный YAML: [source_map_recursive.yaml](../../configs/experiments/g1_splitters/source_map_recursive.yaml).
Решение и ссылки на базы: [study.yaml](../../configs/experiments/study.yaml).
Все P/R/EC@1/5/10,MRR@10,top-k объёмы,стадии,all/warm timings и контрольные ссылки:
[retrieval_comparison.csv](../../results/retrieval_comparison.csv). Таблица содержит
10 comparison и4 reference строки; прежние контролы не пересобирались ради таблицы.

Смена профиля по одному run не доказывает общую оптимальность. Времена — одиночные
замеры с обычным HF cache; небольшие различия wall time не трактуются как устойчивый
эффект параметра. Имена/паспорт каждого run сохраняют фактические условия.
Содержательное качество ответов LLM оценивается отдельно: финальный QA20 и
not_reviewed worksheet выполняются в Task14, после остановки C4.

## Полная серия и проверка C4

Все10 обязательных конфигураций completed/built на одном corpus/gold и одной
закреплённой revision EG2. Контролы G2/G3/G4/G5 — ссылки на прежние результаты,
без дополнительных build. Подготовка — сумма tokenizer/split/document model/
embedding/upload/index wait/BM25, без CPU query model и evaluation. Весь run
включает проверки и20 запросов. Warm retrieval исключает первый запрос.

| Run | EC@5 | MRR@10 | Чанков | Raw tokens@5 | Подготовка, s | Warm retrieval median, ms | Disk allocated, MiB | Весь run, s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [g1_markdown_initial](../../results/g1_markdown_initial/run.json) | 0.8417 | 0.7375 | 3175 | 1930.85 | 108.22 | 121.91 | 28.70 | 133.06 |
| [g1_recursive](../../results/g1_recursive/run.json) | 0.8075 | 0.7450 | 2848 | 2156.85 | 109.25 | 127.41 | 26.93 | 133.13 |
| [g1_source_map_recursive](../../results/g1_source_map_recursive/run.json) | 0.9700 | 0.9750 | 5578 | 1099.45 | 153.28 | 121.54 | 43.74 | 178.91 |
| [g2_overlap_128](../../results/g2_overlap_128/run.json) | 0.9700 | 0.9500 | 5608 | 1183.90 | 155.05 | 142.85 | 44.12 | 181.52 |
| [g2_size_768](../../results/g2_size_768/run.json) | 0.9100 | 1.0000 | 4703 | 1352.30 | 169.43 | 180.63 | 37.86 | 195.59 |
| [g3_hybrid](../../results/g3_hybrid/run.json) | 0.9467 | 0.9750 | 5578 | 1187.85 | 167.85 | 134.35 | 47.49 | 194.46 |
| [g4_hnsw_32_200_256](../../results/g4_hnsw_32_200_256/run.json) | 0.9467 | 0.9750 | 5578 | 1199.30 | 157.24 | 124.55 | 47.50 | 181.80 |
| [g4_bm25_no_stem](../../results/g4_bm25_no_stem/run.json) | 0.9600 | 0.9750 | 5578 | 1294.25 | 159.43 | 115.22 | 48.62 | 184.58 |
| [g5_title_strip](../../results/g5_title_strip/run.json) | 0.9700 | 0.9750 | 5578 | 1128.85 | 160.95 | 119.89 | 43.74 | 186.26 |
| [g5_no_title_keep](../../results/g5_no_title_keep/run.json) | 0.9533 | 0.9250 | 5578 | 972.30 | 144.67 | 130.09 | 43.75 | 168.39 |

Девять новых runs заняли суммарно26.74 min последовательного runtime;
исходный Markdown-контроль выполнен ранее на C2. Размеры Disk allocated измерены
через du -s -B1 в persistent volume после readiness; apparent bytes сохранены
отдельно в evidence, поскольку sparse/preallocated WAL не равен занятым блокам.
Это disk, не RAM/VRAM; float32 vector bytes отдельно присутствуют в CSV.

Все метрики каждого run точно воспроизведены из gold/manifest/hits без поиска.
10 разных index_id/build_id подтверждены native API:green/ready, корректные
points и ненулевые indexed_vectors. G5 сохраняет те же body hashes,char/line ranges
и raw token counts; меняются namespace IDs/embedding input, исходный текст прежний.
Полный Python:671 passed,3 opt-in live skipped,64.06s. Ruff check/format PASS,124 файла.

Подробный [паспорт C4](../../.agents/work/implementation/c4-evidence.json) содержит
пересчёт/размеры/выборы баз; по20 вопросам сохранены отдельные анализы G1–G5.
После завершения lock свободен,GPU использовала735MiB фоновой памяти; LLM/API/UI
в этом этапе не запускались. Qdrant/коллекции/results сохранены.

Следующая задача — Task14:один реальный QA20 на выбранном профиле, not_reviewed CSV
для отдельного рецензента, итоговые проверки/документация и независимое code review.
На C4 предусмотрена пауза; QA20 и смысловые grades ещё не выполнены.
