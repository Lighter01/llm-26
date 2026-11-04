# Runtime и upstream API

`preflight.mjs` проверяет gitlink из HEAD, чистоту tracked-файлов, SHA и Node. `upstream_runtime.mjs` загружает native модули и разрешает только локальные JSON внутри submodule. `inventory_runtime.mjs` использует штатные UID/hash/tag API, lookup routes и entry grammar.

Runtime общий для inventory, assembly и enrichment, один snapshot на процесс. CLI стадий запускаются отдельными процессами. Подмодуль не изменяется, сетевые JSON запрещены. Native smoke находится в тестах `smoke/`.
