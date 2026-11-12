# Эксперименты и оценивание

`data/tasks/lab3.yaml` содержит15 фиксированных English tasks:8 single,4 short dialogues и3 long dialogues, всего47 реплик. Runner подаёт агенту только input текущей реплики и сохраняет один session на item. Следующий item и каждая из четырёх конфигураций получают новый session. Gold/rubric/evidence не входят в model payload.

Перед запуском loader проверяет10 независимых source spans по исходному Markdown body/hash, секции, Unicode координатам и строкам. Quote-only resolver допускает ровно одно совпадение в выбранной секции; первый похожий hit не является разметкой. Frozen fingerprint связывает dataset, corpus/index/build, game catalog, GGUF/template, рабочие prompts/tools/config и adapter. Profile и Git HEAD сохраняются отдельно. Все4 клетки должны иметь одинаковый common fingerprint.

## Файлы одного запуска

`results/lab3/<run-id>/run.json` хранит статус, входной dataset и provenance. `turns.jsonl` — исходные ответы, usage, события, фактические tools и первоначальные scores; `tool_calls.jsonl` — отдельная таблица вызовов. `manifest.json` содержит полный набор chunks индекса. `review.csv` — обязательные смысловые критерии без предзаполненного успеха. После оценивания `scored_turns.jsonl` и `metrics.json` воспроизводятся офлайн из сохранённых входов, raw результатов, manifest и CSV.

`raw/own` содержит полный независимый журнал, `raw/codex` — stdout/stderr/argv и закрытый исходный rollout с export/readback. Wire payload сохраняет original/effective Responses body и native count/usage, включая native compaction. Смысловые snapshots Codex exporter не объявляются точной копией wire после compaction. Отсутствующее число остаётся null; API cost локальной модели явно0.

## Что проверяется автоматически

Формальные проверки сверяют наличие/запрет инструментов, финальные party arguments, XP и бюджеты, точный состав оценки, total/required counts и фильтры успешного build, ожидаемый conflict/search_exhausted, параметры/диапазон loot и фактические ранние records. Исправленный промежуточный вызов не портит проверку финальной калькуляции. Полный журнал всех попыток остаётся для анализа operational tool errors.

Необходимое совпадение чисел/имён добычи с ответом — диагностическая проверка; оно не доказывает корректность объяснения и отсутствие выдумок. Каждая rubric всё равно требует отдельной оценки. Нельзя подменять смысловую оценку поиском служебного `rules_answer` или ключевого слова в тексте.

`review.csv` содержит case_id, turn, criterion, description, value, method, evidence, category. Заполните value0/1, method `human` либо `agent-assisted` и конкретный evidence из ответа/tool result/trace; category может классифицировать ошибку. Пустая оценка остаётся pending. Неизвестный/повторный turn или criterion отклоняется. Agent-assisted оценка не называется человеческой.

Task success требует всех обязательных критериев всех turn. Известная ошибка делает task failed, даже при оставшихся pending; pending никогда не считается успехом. Completion отдельно требует все запланированные turn, completed runtime status, реальный trace и известные input/output usage. Failed, skipped или incomplete не исчезают из знаменателя. Общая success rate остаётся null, пока неизвестен хотя бы один task outcome; счётчик pending показывает незаполненные критерии даже у уже известных failed tasks.

## Retrieval

Используется прежняя математика P/R@1/5/10, MRR@10 и evidence coverage: одинаковые file/hash, пересечение≥50% меньшего span, релевантные IDs из полного manifest. Короткая выдача не уменьшает знаменатель Precision; повторные chunks не улучшают покрытие. Несколько actual search calls одной annotated turn сначала усредняются внутри turn, затем между annotated turns. Для размеченной цели без поиска метрики0 и отдельный `missing_expected_call`; неразмеченный search — N/A. Requested/returned limits сохраняются.

Langfuse SDK5/Compose4 использует event-based Experiments. Дополнительное observation в том же фактическом trace связывает dataset item с experiment через закреплённые OTel attributes SDK; генерации не синтезируются. API readback подтверждает items, generation I/O/usage и последний ответ. Формальные scores загружаются сразу; смысловые — явным `score-agents --upload-scores`.

History correctness получает отдельный обязательный review criterion на размеченных history turns; сводка разделяет его до/после фактического compaction event. Tool correctness — среднее формальных критериев выбора/параметров/результатов на применимых turns; runtime tool errors считаются отдельно по всем попыткам. Максимальный native input и число model calls включают summary/native compaction, когда соответствующий адаптер отдаёт фактические данные. Это разные уровни оценки, они не заменяют task success.

Citation validity — доля уникальных разрешённых `[n]` среди использованных номеров на turns; отсутствие номеров обозначается N/A. Unknown numbers сохраняются, semantic support всё равно относится к rubric. Registry архива сохраняет точный текст/координаты/атрибуцию фактических результатов, включая номера до summary.
