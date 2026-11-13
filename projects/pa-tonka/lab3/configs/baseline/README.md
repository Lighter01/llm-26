# Готовый агент Codex

Baseline — установленный Codex CLI **0.167.0-alpha.4.1**, который работает с той же локальной GGUF-моделью и пятью MCP-инструментами, что и собственный агент. [CodexRunner](../../src/dnd_rag/experiments/codex.py) запускает его и переносит результаты в общие контракты; штатные решения о действиях и сокращении истории остаются внутри Codex.

## Конфигурация и изоляция

| Файл | Назначение |
| --- | --- |
| [codex.toml](codex.toml) | Явные настройки модели, окна, compaction, разрешённых инструментов и локального MCP. |
| [models.json](models.json) | Каталог локального alias: `tool_mode=direct`, окно 16K и штатная fallback-инструкция установленного Codex. |

Runner передаёт настройки через `codex exec --ignore-user-config --strict-config --json --skip-git-repo-check` в пустом временном каталоге. Следующие реплики запускаются через `exec resume` с точным native session ID. Используемый `CODEX_HOME` нужен для поиска собственного журнала сессии; личный config и Stop hook не редактируются.

Shell, unified exec, apps, JS, memory, multi-agent и web отключены. Разрешены пять общих MCP names; `approval_mode=approve` относится к этим явно разрешённым локальным инструментам. Модельные weights остаются локальными, хотя `models.json` использует fallback-инструкцию [OpenAI Codex](https://github.com/openai/codex), Apache-2.0.

## Контекст и профиль модели

`remote_compaction="unsupported"` выбирает штатную local compaction Codex. Серверное окно — **16 384**, порог сокращения — **9 500**. Middleware собственного агента в этот цикл не подставляется.

В режиме `off` используется effort `none`. Для `budgeted` runner задаёт транспортное effort `medium`, а общий [серверный профиль](../llm/README.md) ограничивает reasoning block 512 токенами. Это не поддержка native `low/minimal` и не отдельный бюджет сверх общего лимита ответа.

## Зачем нужен proxy 8081 → 8080

Codex 0.167 передаёт схемы tools в формате `additional_tools/namespace`, который llama build 11046 не поддерживает. Локальный [HTTP-посредник](../../src/dnd_rag/runtime/codex_proxy.py) принимает Responses-запросы на порту **8081**, переносит схемы в поддерживаемый формат functions и обращается к llama.cpp на порту **8080**. Runner подставляет адрес посредника вместо исходного `base_url` из TOML.

Имена преобразуются обратимо; исходные и преобразованные запросы сохраняются в [wire-журнале](../../docs/user_docs/GLOSSARY.md#wire). Собственного планировщика или compaction у посредника нет. Он использует FastAPI/httpx из `uv.lock`; отдельная установка для proxy не нужна.

## Экспортер: что он переносит

Экспортер — Node.js-скрипт официального [Codex observability plugin](https://github.com/langfuse/codex-observability-plugin/tree/e1d02be28e6bacbfe350a1bc1ccf861e54edee17), закреплённого на commit `e1d02be28e6bacbfe350a1bc1ccf861e54edee17`. Он читает [rollout](../../docs/user_docs/GLOSSARY.md#rollout), собственный JSONL-журнал событий Codex, и создаёт observations в локальном Langfuse.

После каждой реплики адаптер выполняет последовательность:

1. Дожидается завершения текущего `exec/resume` и сохраняет копию журнала вместе со stdout/stderr.
2. Запускает экспортер на исходном журнале; тот отправляет события в Langfuse и завершает отправку перед выходом.
3. Сохраняет полный журнал экспортера и выполняет [readback](../../docs/user_docs/GLOSSARY.md#readback): читает API Langfuse, проверяя generations, доступный usage, ожидаемые tools и полный последний ответ ассистента на текущую реплику.

Повторный экспорт использует служебный файл рядом с исходным rollout для защиты от дубликатов. Такая [дедупликация](../../docs/user_docs/GLOSSARY.md#deduplication) проверена отдельной сквозной пробой; она не проверяется заново при каждом обычном readback. Исходные rollout/wire сохраняются и при ошибке чтения Langfuse. После compaction восстановленный экспортером вход генерации может отличаться от реального HTTP-запроса; последний нужно смотреть в wire.

### Установка

Нужен **Node ≥22.22.2**; проверен Node 24.22.2 из ingestion. Из корня lab3 выполните:

```bash
git clone https://github.com/langfuse/codex-observability-plugin .runtime/codex-plugin
git -C .runtime/codex-plugin checkout e1d02be28e6bacbfe350a1bc1ccf861e54edee17
npm exec --yes --package=pnpm@9.5.0 -- pnpm --dir .runtime/codex-plugin install --frozen-lockfile
npm --prefix .runtime/codex-plugin run build
```

Сборка создаёт `.runtime/codex-plugin/plugins/tracing/dist/index.mjs`. Используется upstream pnpm lock: установка через npm без него дала конфликт peer dependencies.

| Настройка окружения экспортера | Значение и смысл |
| --- | --- |
| `TRACE_TO_LANGFUSE` | `true`: включить отправку. |
| `LANGFUSE_CODEX_USER_ID` | `lab3-local`: пользователь локального эксперимента. |
| `LANGFUSE_CODEX_MAX_HISTORY_CHARS` | `0`: не усекать историю по числу символов. |
| `LANGFUSE_CODEX_FAIL_ON_ERROR` | `true`: ошибка экспорта должна завершать процесс с ошибкой. |

Runner задаёт эти переменные только дочернему процессу экспортера. Ключи и адрес Langfuse берутся из локального окружения проекта. Параметры установки и реально проверенная полнота resume/последнего ответа описаны в [VALIDATION](../../docs/rag/VALIDATION.md), устройство результатов — в [EVALUATION](../../docs/user_docs/EVALUATION.md).
