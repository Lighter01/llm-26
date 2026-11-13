# Демонстрация DM-помощника

## Запуск и два связанных решения

После настройки `.env`, локального Langfuse и зависимостей:

```bash
uv run python -m dnd_rag inspect-index
uv run python -m dnd_rag run --interface cli --llm-profile configs/llm/off.yaml
```

CLI показывает реальные этапы инфраструктуры/catalog/index/model/MCP. При готовом индексе GPU-worker не загружается. Отправьте последовательно:

1. `We have four level-6 adventurers. Look up Mage yourself, then evaluate exactly two Mages. Show total XP, budgets and difficulty. Remember the party and enemies.`
2. `We now have three adventurers, still level6. Re-evaluate the same exact enemies. Keep them fixed.`
3. `For a diagnostic, evaluate one Azure Cathedral Titan without substituting a creature. Explain the actual error.`
4. `/status`, затем `/new` и `/exit`.

Два Mages дают4600XP; для4×6 это high, для3×6 — above_high. Неизвестное имя должно дать честную ошибку. /status содержит последнее native input/agent limit/% и отдельное server window, session UUID и Langfuse trace link. Новый UUID изолирует следующий диалог; журналы остаются.

## Много инструментов, история и реальные summary

Повторяемый длинный сценарий использует те же fixed English inputs и ядро:

```bash
uv run python -m dnd_rag evaluate-agents --agent own --mode off --only long_01_mothbridge_ledger --run-id demo-mothbridge
```

Это девять содержательных реплик: build/individual loot; новая attendance; два правила и четыре lookup; не принятая альтернатива; финальный recall. Не ожидайте фиксированный random payout: сравнивайте финал с реальным первым generate_loot. Новый run-id обязателен при повторе; полный список остальных флагов — в [CLI](CLI.md).

Сохранённый основной own/off v2 Mothbridge демонстрирует4 существа (Blink Dog1, Bugbear Stalker2, Goblin Warrior1),44gp, party4→5 приlevel4, три реальные summary и точный финальный recall с Mira/brass lantern. Эти числа относятся к этому запуску; новый payout может отличаться. Промежуточные ошибки правила/полноты ответа отражены в rubric, поэтому сохранность памяти не означает100% task success. [Финальный Langfuse trace](http://127.0.0.1:3000/project/7d8d3807-b938-4896-9289-8a28375b69b5/traces/74d0d23f76b66826f76059b6d59897b8).

В Langfuse откройте experiment с именем run-id, выберите dataset item/turn. Проверьте agent root, реальные generations с usage, tool→retrieval, compaction/context_summary и raw-model-response. Последний turn должен быть виден отдельно. Raw source registry продолжает разрешать номера, выданные до summary; неизвестные номера остаются warning.

## Измерения и офлайн проверка

Четыре полных вызова — own/Codex × off/budgeted — описаны в [методике](EVALUATION.md). Заполненная review.csv требует0/1, method и trace evidence. Затем:

```bash
uv run python -m dnd_rag score-agents --run results/lab3/lab3-own-off-20261113-v2 --upload-scores
uv run python -m dnd_rag summarize-agents --runs results/lab3/lab3-own-off-20261113-v2 results/lab3/lab3-own-budgeted-20261113-v2 results/lab3/lab3-codex-off-20261113-v2 results/lab3/lab3-codex-budgeted-20261113-v2
```

score-agents не вызывает модель; незаполненные критерии остаются pending. API-cost локальной модели0; токены и время измеряются отдельно. После выхода CLI/runner останавливаются собственные model/service процессы; Docker и артефакты сохраняются.
