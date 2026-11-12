# Готовый агент Codex

`codex.toml` задаёт явные overrides для установленного Codex 0.167.0-alpha.4.1. Runner применяет их к `codex exec --ignore-user-config --strict-config --json --skip-git-repo-check` в пустом cwd, затем использует конкретный session ID для `exec resume`. Личный config не редактируется. Сервисы: тот же llama-server Responses endpoint и общий MCP; пять разрешённых MCP names. Shell, unified exec, apps, JS, memory и multi-agent отключены, web disabled. Фактический набор проверяется live, внутренние инструкции Codex остаются свойством готового агента.

`remote_compaction="unsupported"` в capabilities провайдера выбирает штатную local compaction, серверное окно16384 и auto_compact11000 заданы явно. Сжатие не подменяется middleware собственного агента. Effort none используется только для off; budgeted runner заменяет транспортное effort на medium, реальный бюджет512 задаёт общий серверный профиль. Native low/minimal этим не обещаются.

Официальный [Codex observability plugin](https://github.com/langfuse/codex-observability-plugin/tree/e1d02be28e6bacbfe350a1bc1ccf861e54edee17) закреплён на commit e1d02be28e6bacbfe350a1bc1ccf861e54edee17. Установка после clone в `.runtime/codex-plugin`:

```bash
git clone https://github.com/langfuse/codex-observability-plugin .runtime/codex-plugin
git -C .runtime/codex-plugin checkout e1d02be28e6bacbfe350a1bc1ccf861e54edee17
npm exec --yes --package=pnpm@9.5.0 -- pnpm --dir .runtime/codex-plugin install --frozen-lockfile
npm --prefix .runtime/codex-plugin run build
```

Node ≥22.22.2 (проверен Node24.22.2 из ingestion); npm resolution без upstream lock дало peer conflict, поэтому используется pnpm lock. Собранный entrypoint `.runtime/codex-plugin/plugins/tracing/dist/index.mjs` вызывается адаптером на закрытом rollout после каждого turn с flush, fail_on_error=true и max_history_chars=0. Личный Stop hook и доверие к нему не меняются. Повторный export использует upstream sidecar dedup. Переменные TRACE_TO_LANGFUSE=true, LANGFUSE_CODEX_USER_ID=lab3-local, LANGFUSE_CODEX_MAX_HISTORY_CHARS=0 включаются только в окружении экспортера. Полнота последнего turn и resume требует live-приёмки.

`models.json` — явный каталог локального alias для Codex0.167, tool_mode=direct, shell disabled и фактический16K контекст. Он сохраняет штатную fallback base instruction установленного Codex (исходный проект Apache-2.0: https://github.com/openai/codex); weights не заменяются моделью OpenAI. Для benchmark MCP dnd установлен approval_mode=approve в рамках явно разрешённых локальных tools, личный config не меняется.

Codex0.167 сериализует tool schemas как input additional_tools с namespaces. llama build11046 этот формат не поддерживает. Поэтому Codex использует loopback compatibility endpoint8081, который обращается к тому же серверу8080: переносит схемы, обратимо меняет namespace/name, сохраняет original/effective payload и native count/usage parity. В wire catalog остаются только общие MCP functions. Это транспортный адаптер, без планировщика или замены истории/компактизации. Для setup нужен тот же FastAPI/httpx из lock.
