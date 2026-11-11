# Установка, запуск и команды

Все команды выполняются из корня `lab2` через `uv run python -m dnd_rag`. Для знакомства с устройством pipeline см. [ARCHITECTURE.md](ARCHITECTURE.md), для полей экспериментального YAML и Study — [справочник пресетов](../../configs/experiments/README.md).

- [Какой сценарий выбрать](#какой-сценарий-выбрать)
- [Быстрый запуск ассистента](#быстрый-запуск-ассистента)
- [Установка и локальные настройки](#установка-и-локальные-настройки)
- [API и демонстрация](#api-и-демонстрация)
- [Построение и удаление индекса](#построение-и-удаление-индекса)
- [Retrieval-эксперименты и сводка](#retrieval-эксперименты-и-сводка)
- [QA20 и анализ ответов](#qa20-и-анализ-ответов)
- [Профиль llama.cpp и QA](#профиль-llamacpp-и-qa)
- [HTTP API](#http-api)
- [Результаты, времена и журналы](#результаты-времена-и-журналы)
- [Диагностика и остановка](#диагностика-и-остановка)
- [Проверки проекта](#проверки-проекта)

## Какой сценарий выбрать

| Нужно | Команда | Что получится | Отвечающая LLM |
| --- | --- | --- | --- |
| Задать вопрос через веб-интерфейс | `demo` | API и Streamlit с ответами и источниками. | Да. |
| Проверить только поиск по API | `serve-retrieval` | API с `/retrieve`, без генерации и UI. | Нет. |
| Заранее подготовить индекс | `build-index` | Проверенная готовая коллекция Qdrant. | Нет. |
| Измерить качество поиска пресета | `experiment` | Retrieval по 20 вопросам и каталог результатов. | Нет. |
| Сохранить ответы LLM для оценки | `evaluate-qa` | QA20, фактический контекст и таблица рецензирования. | Да. |
| Получить CSV по готовым экспериментам | `summarize-results` | Сводная таблица из сохранённых файлов. | Нет; Qdrant тоже не нужен. |
| Удалить одну коллекцию проекта | `reset-index` | Удаление выбранного индекса; `results/` сохраняется. | Нет. |

Каждая команда — отдельная операция. **`demo` и `serve-retrieval` являются альтернативными режимами.** Для полного ассистента запускайте только `demo`: он сам подготавливает индекс и запускает LLM, API и UI. Перед переключением режима остановите предыдущий через Ctrl+C.

Если задача — писать отчёт по уже выполненной серии, данные готовы в `results/`; повторно запускать эксперименты не требуется. См. [раздел об артефактах](#результаты-времена-и-журналы).

## Быстрый запуск ассистента

### 1. Установить окружение

```bash
uv sync --group test --group lint
cp -n .env.example .env
```

`cp -n` создаёт локальные настройки, сохраняя существующий `.env`. Исходный Markdown-корпус уже подготовлен; ingestion перед RAG запускать не нужно.

### 2. Настроить пути и запустить Docker engine

Проверьте `LLAMA_SERVER_BIN` и `LLM_MODEL_PATH` в `.env`. В проверенном локальном окружении используется установленный unified llama.cpp:

```dotenv
LLAMA_SERVER_BIN=/home/lighter_01/.llama-app/llama
LLM_MODEL_PATH=~/hf_models/gemma/nemotron/nemotron-3.5/bolt/NVIDIA-Nemotron-3.5-Bolt-E4B-UD-Q4_K_XL.gguf
```

Путь к бинарнику должен соответствовать вашей установке. В готовом `configs/llm/local.yaml` стоит `server_subcommand: serve`, что соответствует этому unified-бинарнику. Для отдельного `llama-server` согласуйте путь и `server_subcommand: null`; [различие вариантов](#профиль-llamacpp-и-qa) описано ниже.

Запустите Docker Desktop с Linux engine/WSL integration. В используемом окружении доступна команда `docker desktop start`. Qdrant можно поднять явно:

```bash
docker compose -f compose.yaml up -d qdrant
```

Коллекции хранятся в `data/qdrant/` внутри проекта: Compose подключает этот каталог к `/qdrant/storage` контейнера через bind mount. Каталог исключён из Git. В WSL храните проект в Linux-файловой системе; Qdrant требует POSIX-совместимое хранилище. При подтверждённом отсутствии стандартного локального Qdrant launcher также запускает этот Compose автоматически. Работающий Docker engine всё равно необходим.

### 3. Запустить один режим — `demo`

```bash
uv run python -m dnd_rag demo \
  --config configs/experiments/g1_splitters/source_map_recursive.yaml \
  --llm-profile configs/llm/local.yaml
```

Это выбранный по экспериментам профиль. Если совместимая коллекция есть, она используется повторно. Если её нет, команда сначала выполняет полную GPU-индексацию; запуск может занять существенно больше времени. Локальная LLM стартует после выхода документного GPU worker.

Дождитесь готовности, затем откройте **http://127.0.0.1:8501**. API доступен на http://127.0.0.1:8000, интерактивная документация — http://127.0.0.1:8000/docs. Команда остаётся работать в терминале. Ctrl+C останавливает созданные ею сервисы; Qdrant и сохранённые коллекции остаются.

## Установка и локальные настройки

### Зависимости выбранного режима

Нужны Python ≥3.13 и uv. Управление процессами рассчитано на Linux/WSL: используются `flock` и Linux `/proc`.

| Зависимость | Когда нужна |
| --- | --- |
| Qdrant 1.20.0 | Для build, поиска, QA и reset. Стандартный локальный вариант — закреплённый Docker Compose с хранилищем `data/qdrant/`. |
| CUDA GPU | Для новой векторизации документов. Готовый retrieval-индекс используется с CPU-моделью вопросов; выбранный профиль LLM отдельно использует GPU. |
| EmbeddingGemma 2 | Для построения и векторизации вопросов; ID и ревизия задаются пресетом. Недостающие веса загружаются в HF cache. |
| GGUF Nemotron и llama.cpp | Для `demo`, `evaluate-qa` и отдельного запуска LLM. Веса хранятся вне проекта. |
| Только Python-зависимости | Для offline-summary и обычных unit-тестов; модели и Docker не запускаются. |

Torch и остальные версии закреплены в `uv.lock`; в проверенном Linux-окружении используется CUDA-сборка. Для готовой подготовки данных есть отдельные [команды ingestion](../../src/dnd_rag/ingestion/README.md) и [валидатор вопросов](../../src/dnd_rag/ingestion/question_validation/README.md).

### Где задаются параметры

| Источник | Содержание |
| --- | --- |
| `--config PATH` | Полный экспериментальный YAML: corpus, chunking, embedding, index, retrieval и evaluation. |
| `.env` / окружение процесса | Пути и адреса этой машины. |
| `--llm-profile PATH` | Окно, предел ответа, sampling, размещение LLM и HTTP-timeout. |
| `--study PATH --group NAME` | Карта происхождения сравнений и выбранных баз. |
| `--experiment-name NAME` | Новое имя каталога результатов; в YAML пресета его нет. |

Относительные пути разрешаются от корня `lab2`, поддерживается `~`. Для локальных настроек приоритет — переменные процесса, затем `.env`, затем default. Пустое `EMBEDDING_CACHE_DIR` означает стандартный HF cache. `.env` и секреты не копируются в результаты и исключены из Git.

### Переменные `.env`

| Переменная | Default | Назначение |
| --- | --- | --- |
| `QDRANT_URL` | `http://127.0.0.1:6343` | Адрес собственного Qdrant lab3 (Compose HTTP 6343, gRPC 6344). Для другого адреса совместимый сервер должен уже работать. |
| `LLAMA_SERVER_BIN` | `llama-server` в PATH | Путь к установленному бинарнику. Для готового unified-профиля задайте путь к `~/.llama-app/llama`. |
| `LLM_MODEL_PATH` | Путь к Nemotron из [.env.example](../../.env.example) | Внешний GGUF; полный исходный путь приведён в быстром запуске. |
| `LLM_BASE_URL` | `http://127.0.0.1:8080/v1` | Локальный llama.cpp API. Для managed launch используйте loopback HTTP с `/v1`; завершающий `/` допустим. |
| `EMBEDDING_CACHE_DIR` | Пусто | Обычный HF cache либо заданный `cache_folder` эмбеддера. |
| `RAG_API_URL` | `http://127.0.0.1:8000` | Адрес API для запуска и UI. Используйте `http://127.0.0.1:PORT` или `http://localhost:PORT` без path/query. |

Порт Streamlit фиксирован: **8501**. Порт 8080 относится к LLM, 8000 — к приложению; это разные сервисы. Набор правил обработки YAML, типы и все параметры пресета находятся в [README экспериментов](../../configs/experiments/README.md).

## API и демонстрация

### Полный ассистент: `demo`

Команда показана в [быстром запуске](#быстрый-запуск-ассистента). Предварительно запускать `serve-retrieval`, отдельный llama-server или `build-index` для неё не требуется.

| Аргумент | Обязательность / default | Смысл |
| --- | --- | --- |
| `--config PATH` | Обязателен. | Фиксирует индекс и настройки поиска на весь запуск. |
| `--llm-profile PATH` | Обязателен. | Выбирает профиль отвечающей LLM. |
| `--rebuild` | Флаг, default false. | Перед запуском LLM полностью повторить подготовку индекса. |

В UI вопрос отправляется при `qa_ready=true`. Ответ показывается целиком после генерации и проверки номеров источников. Есть предупреждения, времена, превью и раскрываемые полные исходные фрагменты. Координаты относятся к body книги, а печатные страницы показываются с исходной точностью атрибуции. История в следующий prompt не передаётся. Системная инструкция ориентирует модель на английские ответы; русский ввод не блокируется, но оценочные вопросы и замеры качества относятся к английскому набору.

### Только поиск: `serve-retrieval`

Остановите другой runtime, затем запустите этот режим вместо `demo`:

```bash
uv run python -m dnd_rag serve-retrieval \
  --config configs/experiments/g1_splitters/source_map_recursive.yaml
```

| Аргумент | Обязательность / default | Смысл |
| --- | --- | --- |
| `--config PATH` | Обязателен. | Индекс и профиль поиска. |
| `--rebuild` | Флаг, default false. | Принудительная полная подготовка до запуска API. |

Доступны `/health` и `/retrieve`. LLM и Streamlit не запускаются; `/ask` возвращает 503 `qa_disabled`. GGUF и бинарник llama.cpp не нужны. Примеры HTTP-запросов находятся в [HTTP API](#http-api).

### Новый и готовый индекс

| Состояние / режим | Что делает launcher |
| --- | --- |
| Новый / retrieval | GPU build → worker exit → CPU query encoder → API. |
| Готовый / retrieval | Проверка и reuse → CPU query encoder → API. |
| Новый / demo | GPU build → worker exit → CPU query encoder → LLM → API → UI. |
| Готовый / demo | Проверка и reuse → CPU query encoder → LLM → API → UI. |

API использует один Uvicorn worker без reload; CPU query encoder загружается один раз. Пользовательский HTTP-запрос не строит индекс. Смена пресета требует остановить процесс и запустить нужный режим заново. Совместимость коллекции определяется параметрами сборки, поэтому query-only изменения позволяют reuse.

## Построение и удаление индекса

### Подготовить коллекцию: `build-index`

```bash
uv run python -m dnd_rag build-index \
  --config configs/experiments/g1_splitters/source_map_recursive.yaml
```

| Аргумент | Обязательность / default | Смысл |
| --- | --- | --- |
| `--config PATH` | Обязателен. | Вычислить нужный вариант индекса. |
| `--rebuild` | Флаг, default false. | Полностью пересобрать собственный вариант, включая эмбеддинги. |

Без флага готовая совместимая коллекция проверяется и используется целиком; отсутствующая или неполная проходит полную сборку. Для проверки/reuse GPU-документная модель не загружается. В stdout выводится JSON с `index_id`, `build_id`, `action`, `reason` и стадиями; сведения о стадиях также выводятся в stderr.

Для принудительной пересборки выполните отдельно:

```bash
uv run python -m dnd_rag build-index \
  --config configs/experiments/g1_splitters/source_map_recursive.yaml --rebuild
```

GGUF и llama.cpp команде не требуются. Если настроенный LLM endpoint отвечает, GPU build прекращается с `gpu_conflict`; освободите адрес LLM или исправьте настройку адреса. Любой HTTP-ответ означает занятый endpoint. Неопределённость его состояния даёт `llm_preflight_failed` до подготовки. Готовая коллекция переиспользуется до этой проверки GPU-конфликта.

### Удалить одну коллекцию: `reset-index`

Удаление выполняется по отдельной необходимости; в обычный запуск ассистента оно не входит. Выберите **один** способ адресовать коллекцию:

| Selector | Когда использовать |
| --- | --- |
| `--config PATH` | Удалить вариант, вычисленный по текущему корпусу, конфигу и версиям зависимостей. |
| `--index-id SHA256` | Удалить конкретный прежний вариант по ID из его `run.json`, даже после изменения корпуса или зависимостей. |

Пример по конфигурации baseline:

```bash
uv run python -m dnd_rag reset-index \
  --config configs/experiments/g1_splitters/markdown.yaml
```

Альтернативный пример по прежнему ID:

```bash
uv run python -m dnd_rag reset-index --index-id FULL_64_CHARACTER_SHA256
```

Замените placeholder на полный 64-символьный SHA-256 из строчных `a-f` и цифр. Параметры взаимоисключающие и не имеют default; один обязателен. По ID не читаются корпус/эталоны и не загружаются модели. Повторный reset отсутствующей коллекции успешен: `deleted: false`.

Удаляется только выбранная собственная коллекция с проверенным паспортом. Другие варианты, volume и каталоги `results/` остаются. Следующий запуск её пресета заново построит индекс. Сетевая ошибка не считается отсутствием и не разрешает удаление.

## Retrieval-эксперименты и сводка

### Измерить поиск: `experiment`

```bash
uv run python -m dnd_rag experiment \
  --config configs/experiments/g1_splitters/recursive.yaml \
  --experiment-name g1_recursive_example \
  --study configs/experiments/study.yaml --group G1
```

| Аргумент | Обязательность / default | Смысл |
| --- | --- | --- |
| `--config PATH` | Обязателен. | Полный retrieval-пресет. |
| `--experiment-name NAME` | Обязателен. | Новое имя результата в `results/`. |
| `--rebuild` | Флаг, default false. | Повторить полную сборку даже при готовой коллекции. |
| `--study PATH` | Default не задан; используется вместе с `--group`. | Проверить происхождение сравнения по карте. |
| `--group NAME` | Default не задан; используется вместе с `--study`. | Выбрать группу карты, например G1. |

Без двух последних аргументов выполняется самостоятельный эксперимент. Поиск и остальные параметры берутся из YAML; CLI не подставляет профиль из базы Study.

Команда проверяет корпус и validated gold, подготавливает или переиспользует индекс, дожидается выхода GPU worker, загружает один CPU query encoder и выполняет retrieval по 20 основным вопросам. Затем считает метрики и сохраняет результат. LLM не запускается; её ответы эти метрики не оценивают.

Для оценки нужны `data/questions/validated/questions.yaml` и соответствующий соседний `validation_report.json` с PASS / written. Проверяются хэши и точные срезы evidence. Генерация вопросов/ingestion повторно не выполняется. После смены gold сравнивайте результаты на одной версии; 3 insufficient-вопроса в retrieval-средние не входят.

### Повторить запуск и проверить reuse

Имя — один компонент пути `[A-Za-z0-9_.-]+`, кроме `.` и `..`. Выбирайте имя, которого ещё нет в `results/`. Существующий каталог блокирует новый run до тяжёлой работы и изменения индекса; failed-каталоги тоже сохраняются.

Для проверки reuse выполните ту же команду с новым именем, например `g1_recursive_reuse_example`, без `--rebuild`. Совместимая готовая коллекция не требует повторной векторизации. В паспорте будут `index_action=reused` и прежний `build_id`; у пропущенных стадий — `elapsed_ms=null`. Это отдельное условие измерения затрат, а не новая конфигурация качества поиска.

### Study и порядок групп

Программа содержит 10 полных пресетов: G1 выбирает splitter; G2 — размер/overlap; G3 сравнивает dense/hybrid; оба G4 используют одну гибридную базу G3; G5 использует плотную базу после G2. Перед зависимой группой автор выбирает завершённый base run и уточняет её полные YAML. Невыбранная база, несовместимый корпус/gold или неверная declared delta блокируют запуск с картой.

Понятия `selected_base_run`, `reference_run`, `selection_reason`, схема зависимостей и цели каждого пресета раскрыты в [README экспериментов](../../configs/experiments/README.md#устройство-study-и-зависимости). После нового запуска автор обновляет `comparison.run` в карте; команда сама YAML не редактирует.

### Построить CSV: `summarize-results`

```bash
uv run python -m dnd_rag summarize-results \
  --study configs/experiments/study.yaml \
  --output results/retrieval_comparison.csv
```

Обязательны `--study PATH` и `--output PATH`; других рабочих флагов у команды нет. Она читает карту и готовые паспорта/метрики, атомарно создаёт или заменяет сводку. `.env`, runtime-lock, модели и Qdrant для неё не нужны. Выбирайте output вне каталогов сохранённых runs, как в примере. Перезапись входного study и запись файла рядом с `run.json` отвергаются.

В текущем CSV 14 строк: 10 `comparison` и 4 `reference`, соответствующие 10 уникальным конфигурациям. Failed/missing/not_run и несовместимые controls показаны явно; reuse не получает фиктивную нулевую стоимость первоначальной сборки. Поля CSV и правила сравнимости описаны в [справочнике](../../configs/experiments/README.md#сводка-результатов-csv).

### Пересчитать метрики без нового поиска

Это Python API, отдельной CLI-команды для recompute нет:

```python
from pathlib import Path
from dnd_rag.evaluation.retrieval_run import recompute_saved_metrics

metrics = recompute_saved_metrics(Path('results/g1_markdown_initial'))
```

Функция читает сохранённые gold/manifest/hits и проверяет хэш gold. Qdrant, исходные книги и модели для пересчёта не требуются.

## QA20 и анализ ответов

### Сгенерировать ответы: `evaluate-qa`

```bash
uv run python -m dnd_rag evaluate-qa \
  --config configs/experiments/g1_splitters/source_map_recursive.yaml \
  --llm-profile configs/llm/local.yaml \
  --experiment-name qa_selected_new
```

| Аргумент | Обязательность / default | Смысл |
| --- | --- | --- |
| `--config PATH` | Обязателен. | Выбранный retrieval-профиль. |
| `--llm-profile PATH` | Обязателен. | Профиль отвечающей LLM. |
| `--experiment-name NAME` | Обязателен. | Новое имя QA-run в `results/`. |
| `--include-insufficient` | Флаг, default false. | Добавить 3 отдельных случая недостатка данных к основным 20. |

Команда под общим runtime-lock резервирует результат, проверяет gold/индекс, загружает CPU query encoder, затем Nemotron и выполняет один `RagService.ask` на вопрос. UI не запускается. Для аудита сохраняется контекст именно этого вызова; повторный retrieval не выполняется.

У `evaluate-qa` нет флага `--rebuild`. При необходимости принудительно перестроить индекс сначала отдельно выполните `build-index --rebuild`, затем QA-команду. Обычный QA-run сам построит отсутствующую или неполную коллекцию.

### Что оценивается отдельно

`qa_review.csv` содержит наблюдаемые поля и пустые смысловые критерии `correctness`, `completeness`, `citation_support` с обоснованиями, `missing_facts`, `uncited_claims`. Начальный статус — `not_reviewed`. Наличие номера источника не превращается в автоматическую оценку правильности.

Рецензент заполняет критерии значениями `yes` / `partial` / `no` / `not_applicable`, добавляет обоснования и `review_status=reviewed` / `needs_review`. Для агентской помощи используется `review_method=agent_assisted`, для человека — `human`; также есть `reviewer`, `reviewed_at`, `review_version`. Основные 20 и optional 3 имеют разные сводки. Встроенного LLM-as-judge нет.

При сбое сохраняются предыдущие ответы, строка ошибки и failed-паспорт/сводка. Такой run не считается завершённым QA20. Новое имя защищает существующие ответы и правки рецензента от перезаписи.

## Профиль llama.cpp и QA

Параметры находятся в [configs/llm/local.yaml](../../configs/llm/local.yaml). **Default схемы** — значение при пропуске поля; **локальный профиль** — уже выбранное и проверенное значение в файле. Для GPU placement некоторые defaults равны null, но перед launch их нужно задать явно.

### Окно и поведение QA

| Поле | Фиксированное значение | Назначение |
| --- | --- | --- |
| `context_size` | 8192 | Полное окно LLM; fit/context shift выключены. |
| `max_output_tokens` | 1536 | Максимум генерации, а не требуемая длина ответа. |
| `safety_margin` | 256 | Дополнительный резерв. Весь вход должен быть ≤6400 токенов. |
| `max_context_chunks` | 5 | Максимум первых retrieval hits, рассматриваемых для контекста. |
| `thinking` | false | Выключает reasoning в подсчёте и генерации. |

Вход включает system, вопрос, все источники, маркеры и chat template. При превышении 6400 удаляются целые чанки с конца и выполняется повторный подсчёт. Если не входит первый фрагмент с вопросом, генерации нет и возвращается `context_budget_exceeded`. Исходный вопрос и чанки не обрезаются.

### Запуск сервера и память

| Поле | Допустимо / default схемы | В локальном профиле | Назначение |
| --- | --- | --- | --- |
| `server_subcommand` | null или `serve`; default null. | `serve` | null для standalone llama-server; serve для unified llama. |
| `model_alias` | str; default `dnd-nemotron`. | `dnd-nemotron` | Имя модели в локальном API. |
| `gpu_layers` | int≥0 или null; default null. | 99 | Число слоёв на GPU; значение 99 запрашивает все доступные слои этой модели. |
| `batch_size` | int>0 или null; default null. | 512 | Логический prompt batch; влияет на throughput и память. |
| `ubatch_size` | int>0 или null, ≤batch; default null. | 128 | Физический подпакет; влияет на память. |
| `cache_type_k` / `cache_type_v` | null, `f16`, `q8_0`, `q4_0`; default null. | `q8_0` / `q8_0` | Форматы KV-кэша LLM. |
| `kv_offload` | bool; default true. | true | Размещать KV на GPU; false переносит его в CPU RAM. |
| `flash_attention` | Строка `on` / `off`; default `on`. | `'on'` | Attention backend. В YAML значение on нужно заключать в кавычки. |
| `threads` | int>0; default 8. | 8 | CPU threads генерации и обработки промпта. |

`gpu_layers`, оба batch и оба cache type обязательны для launch. Запрошенные значения размещения фиксируются в argv; профиль не задаёт dtype эмбеддера. Веса GGUF и бинарник остаются вне проекта.

В проверенном окружении используется `~/.llama-app/llama serve`, build11046/60081bb2b. При другой установке задайте путь в `LLAMA_SERVER_BIN` и соответствующий `server_subcommand`; standalone `llama-server` запускается с null. Согласованные Nemotron, окно, резерв ответа и thinking сохраняются; автоматического переключения модели или уменьшения этих лимитов нет. Совместимость и ресурсные замеры находятся в [технических пробах](../rag/TECHNICAL_PROBES.md).

### Sampling и тайм-ауты

| Поле | Допустимо / default | Назначение |
| --- | --- | --- |
| `temperature` | float≥0; 0.0. | При 0 — жадный выбор токена. |
| `top_p` | (0,1]; 1.0. | Nucleus sampling. |
| `top_k` | int≥0; 40. | Число кандидатов sampling. |
| `min_p` | [0,1]; 0.0. | Нижний относительный порог sampling. |
| `seed` | int≥0; 42. | Seed; не гарантия побитовой повторяемости на всех устройствах. |
| `startup_timeout_seconds` | float>0; 120. | Ожидание readiness запускаемого llama.cpp. |
| `http_timeout_seconds` | float>0; 180. | Тайм-аут HTTP-клиента LLM. UI отдельно ждёт ответ до 180 с. |

Локальный профиль явно содержит эти значения. Ориентир полного прогретого QA до 30 с описывает ожидаемое удобство работы и не является HTTP-timeout или гарантией для любого вопроса. Для count/generation используется один template; ChatOpenAI передаёт максимум ответа как `max_completion_tokens`, поддержанный установленным llama.cpp.

### Отдельный сервер LLM

Для технической проверки только LLM можно использовать тонкую обёртку над тем же launcher:

```bash
uv run python scripts/start_llama_server.py --llm-profile configs/llm/local.yaml
```

Скрипт принимает обязательный `--llm-profile PATH`, держит общий runtime-lock и останавливает свой процесс по Ctrl+C. Перед этим остановите demo и другие runtime-команды. Для обычного demo эта отдельная команда не нужна; подключение к уже занятому LLM endpoint прекращается с `llm_conflict`.

## HTTP API

Примеры ниже выполняются **во втором терминале**, пока работает выбранный API-режим. `curl` обращается к уже поднятому API и не запускает второй runtime.

### Методы и готовность

| Метод | Вход | Результат |
| --- | --- | --- |
| `GET /health` | Без тела. | `index_ready`, `query_encoder_ready`, `retrieval_ready`, `qa_ready`, `mode`, `index_id`, `build_id`. |
| `POST /retrieve` | Непустая строка `question`; optional целое `limit` от 1 до `retrieval.limit`. Default берётся из YAML, обычно 10. | `RetrievalResult`: question/index/build/mode, hits с rank/score/score_kind и полным chunk, timings query_embedding/search/total. |
| `POST /ask` | Только непустой `question`. | `AskResult`: status/question/answer/sources/warnings, index/build, context, finish_reason и timings. |

Для `/health` HTTP200 означает готовый retrieval; QA отдельно проверяется по `qa_ready`. В `serve-retrieval` нормальны `mode=retrieval_only` и `qa_ready=false`. В `demo` mode=`qa`. При неготовом retrieval health возвращает 503 с теми же полями состояния. Проверка здоровья не вычисляет эмбеддинги и не читает все payload.

Оба POST-метода отклоняют лишние поля: history/config/model/collection через запрос не передаются. Контекст ответа содержит переданные/удалённые chunk IDs, input tokens и лимиты окна/ответа/резерва. `timings_ms` QA включает query_embedding, search, context, generation, postprocess и total.

### Примеры запросов

Проверка готовности в любом API-режиме:

```bash
curl -s http://127.0.0.1:8000/health
```

Поиск, доступный в обоих режимах:

```bash
curl -s http://127.0.0.1:8000/retrieve -H 'Content-Type: application/json' \
  -d '{"question":"How does the Help action work in combat?","limit":3}'
```

Ответ LLM, доступный в `demo`:

```bash
curl -s http://127.0.0.1:8000/ask -H 'Content-Type: application/json' \
  -d '{"question":"How does the Help action work in combat?"}'
```

### Источники и предупреждения

`sources` содержит только допустимые номера `[n]`, использованные моделью, с полным текстом, превью до 400 Unicode-символов и координатами. Исходные номера сохраняются. Код, escapes и настоящие Markdown links/images не считаются цитатами. Неизвестный номер даёт `unknown_citation`; `finish_reason=length` — `answer_truncated`. Текст возвращается без скрытой повторной генерации.

Успешно пустой retrieval даёт `status=no_context`, пустые sources и null для input_tokens/finish_reason/generation. Отсутствие score-фильтра означает, что по далёкому вопросу выдача обычно всё же есть; достаточность источников нельзя вывести из одного наличия hits. Подробнее о бюджете и реестре — в [архитектуре](ARCHITECTURE.md#путь-одного-вопроса).

### Ошибки HTTP

Для ошибок запросов используется единый конверт:

```json
{"error":{"code":"qa_disabled","message":"Q&A is disabled in retrieval-only mode"}}
```

Поле `details` добавляется при наличии подробностей. Health readiness503 описан отдельно выше. Основные ошибки:

| HTTP | Причина / действие |
| --- | --- |
| 422 | Неверные поля, пустой вопрос, limit вне диапазона, слишком длинный вход эмбеддера или `context_budget_exceeded`. Исправьте запрос. |
| 503 | Не готов индекс/LLM или сервис недоступен; в retrieval-only `/ask` даёт `qa_disabled`. Проверьте режим и `/health`. |
| 504 | Тайм-аут зависимости. Смотрите её состояние и журналы. |
| 429 | `qa_busy`: другой QA-вызов ещё выполняется. Повторите после его окончания; `/retrieve` остаётся доступен. |
| 500 | Неожиданная ошибка приложения или нарушение контракта LLM. Для неожиданной ошибки трассировка пишется в `.runtime/errors.log`. |

Предупреждения о цитатах не меняют успешный HTTP200. Клиент получает готовый ответ после генерации; streaming отсутствует. Разрыв соединения не вызывает автоматическую вторую генерацию.

## Результаты, времена и журналы

### Что записывается в `results/`

У experiment и evaluate-qa общий набор: `config.yaml`, `resolved_config.yaml`, `gold.yaml` и атомарно обновляемый `run.json`. Паспорт фиксирует schema/type/status, начало/конец, ошибку/стадию, config/index/build IDs, action/reason, происхождение сборки, версии/Git state/устройства и времена. `.env` не копируется.

| Тип | Дополнительные файлы | Для чего читать |
| --- | --- | --- |
| Retrieval | `chunks_manifest.jsonl` | Полный перечень chunk IDs, файлов, диапазонов и token counts этого индекса. |
| Retrieval | `relevance.json` | Полное `Rq` каждого вопроса и определение relevance. |
| Retrieval | `per_question.jsonl` | Фактические ranked hits, P/R/EC/RR, покрытия фактов/альтернатив, объёмы, времена и ошибки. |
| Retrieval | `metrics.json` | Агрегаты качества и all/warm/first-query timing, число ошибок и объём top-k. |
| QA | `llm_profile.yaml`, `resolved_llm_profile.yaml` | Исходный и эффективный профиль LLM. |
| QA | `prompts/system.txt`, `prompts/context_builder.py` | Точные снимки system и сборщика динамического блока; хэши в паспорте. |
| QA | `qa_answers.jsonl` | Вопросы, raw answers, AskResult, actual retrieval/messages/registry, usage/native response, finish/warnings/timings и структурная диагностика. |
| QA | `qa_review.csv` | Наблюдения и таблица для отдельной смысловой оценки. |
| QA | `qa_summary.json` | Expected/completed/failed/unattempted, structural diagnostics и времена; primary и insufficient раздельно. |

### Как читать времена

`index_action=built/rebuilt` означает выполненную полную подготовку; `reused` — использование готовой коллекции. Пропущенные build-стадии имеют `elapsed_ms=null`; затраты на исходную сборку доступны в `build_provenance`. Сравнивайте одинаковые условия, сохраняя разделение текущего и первоначального времени.

Первый настоящий запрос помечен `cold_first_query`; `warm` — следующие запросы 2–20 одного процесса. Отдельной исключённой серии прогрева перед ними нет, каждый вопрос основного прогона выполняется один раз. Загрузка моделей, включая первое скачивание при необходимости, учитывается отдельно; файловые/HF-кэши не очищаются. Для сохранённой обязательной серии веса уже были скачаны во время технических проб. Все 20 вопросов входят в метрики качества, первый исключается только из warm-статистики времени. Prompt cache LLM выключен; ответы генерируются заново. Небольшие различия одиночных замеров не доказывают устойчивого преимущества.

### Какие данные уже готовы

Сохранены все 10 retrieval-конфигураций и [comparison CSV](../../results/retrieval_comparison.csv). Выбран dense `source_map_recursive` H4, 512/64, title=true, strip=false: EC@5 = 0.9700, MRR@10 = 0.9750 на 20 gold-вопросах. Это оценка качества поиска; correctness ответа оценивается отдельно.

[Финальный QA20](../../results/qa_final/run.json): completed/reused, 20/20, input 929–2366 токенов, finish=stop, warnings=0. Первый ответ — 4.318 с; следующие 19 — медиана 2.713 с, максимум 4.287 с. Весь run занял 110.107 с с загрузкой и проверкой. Все 20 строк [текущей рецензии](../../results/qa_final/qa_review.csv) заполнены методом `agent_assisted`; исходная QA-сводка остаётся снимком до рецензии. Для повторной генерации используйте новое имя.

При исторической приёмке 6 ноября 2026 года после исправлений runtime demo smoke стал готов за 19.052 с, UI-запрос занял 2.269 с, показаны 2 полных исходных фрагмента. Проверки завершения своих процессов и освобождения lock прошли. Браузерный визуальный осмотр не выполнялся. Подробные [сравнения](../rag/EXPERIMENTS.md), [приёмка/пакет для отчёта](../rag/VALIDATION.md) и [ресурсные замеры](../rag/TECHNICAL_PROBES.md) содержат условия и ссылки на исходные evidence. Постоянные дополнительные измерения перенесены в [results/technical](../../results/technical/README.md); [готовый отчёт](../../report/LAB2_REPORT.md) собирается из штатных runs и этих JSON без служебных материалов разработки.

### Локальная диагностика `.runtime/`

| Путь | Содержание |
| --- | --- |
| `.runtime/startup.json` | Режим/PID/index action/IDs, ensure stages и накопленное время событий index_ready → gpu_worker_exited → cpu_query_loaded → llm_ready → api_ready → ui_started согласно режиму. |
| `.runtime/builds/<uuid>/` | Запрос GPU worker, stages/result и `worker.log`. |
| `.runtime/llama/instance.json` | Actual argv/profile, binary version, model/template hashes и server props. |
| `.runtime/llama/server.log` | Диагностика llama.cpp. |
| `.runtime/ui.log` | Диагностика Streamlit. |
| `.runtime/errors.log` | Неожиданные ошибки CLI/API. |
| `.runtime/project.lock` | Стабильный lock-файл; блокирует открытый OS lock, а не само наличие файла. |

Это локальная диагностика, отдельная от воспроизводимых аналитических runs. Новые пресеты не используют worker-файлы как кэш пропуска индексации.

## Диагностика и остановка

### Один runtime и Ctrl+C

Build/experiment/serve/demo/QA/reset и standalone LLM занимают общий runtime-lock. Второй процесс сразу получает `runtime_busy`. Чтение готовых результатов и summarize-results могут выполняться независимо.

Ctrl+C останавливает только собственные дочерние процессы и ждёт их завершения до освобождения lock. Потомок сохраняет защиту при аварийной смерти родителя. Для группы после выхода wrapper проверяется inherited FLOCK, а TERM-ignoring остатки получают KILL. Подробности Linux `/proc`-проверки — в [архитектуре](ARCHITECTURE.md#процессы-память-и-блокировки). Удалять lock-файл для обхода занятого runtime не нужно.

Qdrant — постоянная база. Остановить её можно отдельно, когда runtime проекта завершён:

```bash
docker compose -f compose.yaml stop qdrant
```

`stop` и `down` сохраняют данные bind mount в `data/qdrant/`; флаг `-v` для этой конфигурации не требуется. Удаление или замена самого каталога затрагивает все коллекции. Для переноса/резервного копирования всего хранилища сначала остановите Qdrant; восстановление выполняйте на той же версии сервера. После запуска готовые совместимые коллекции используются повторно без векторизации документов.

### Частые ситуации

| Симптом / код | Что проверить |
| --- | --- |
| `runtime_busy` | Завершите первый runtime. После аварии его живые дети могут ещё удерживать lock. Существование файла само по себе не мешает запуску. |
| `llm_conflict`, `gpu_conflict`, занятый API/UI порт | Остановите ранее запущенный режим или сервер. Чужой сервис автоматически не завершается. |
| `llm_preflight_failed` | Состояние endpoint не удалось подтвердить: timeout/DNS/protocol/unknown transport. Исправьте адрес/доступность; GPU/новый LLM launch не продолжались. |
| Qdrant недоступен | Запустите Docker engine; проверьте `QDRANT_URL`, Compose, доступность и права `data/qdrant/`. Авто-Compose разрешён только для стандартного локального адреса с подтверждённым ECONNREFUSED. |
| UI сообщает, что QA не готов | Посмотрите `/health`: нужен `qa_ready=true`. В `serve-retrieval` QA отключён штатно; выберите `demo`. |
| `context_budget_exceeded` или слишком длинный embedding input | Укоротите вопрос. Программа не обрезает вход скрыто. |
| Каталог результата уже существует | Задайте новое `--experiment-name`; существующий run, включая failed и reviewer edits, сохраняется. |
| `invalid_study` | Проверьте выбранную completed базу, пару --study/--group, corpus/gold и changed_parameters. Детали схемы — в README пресетов. |
| `index_ownership` | Паспорт не доказывает владение коллекцией; автоматического удаления нет. Проверьте адрес и сохранённый паспорт. |

### Коды завершения CLI

| Код | Значение |
| --- | --- |
| 0 | Успех, включая reset отсутствующей коллекции. |
| 2 | Ошибка аргументов, конфигурации или другой неверный ввод. |
| 1 | Runtime/сборка/сервис/прерывание. |

У всех 7 команд есть `-h` / `--help`, например `uv run python -m dnd_rag demo --help`. Ошибки основного CLI печатаются в stderr; неожиданные ошибки дополнительно записываются в локальный журнал.

## Проверки проекта

### Быстрые проверки

```bash
uv run --group test python -m pytest -m 'not integration'
uv run --group lint ruff check src tests
uv run --group lint ruff format --check src tests
```

Они не запускают модели, GPU или Docker. Подготовленный Markdown-корпус для этих unit-тестов не пересобирается.

### Полный Python-набор с ingestion integration

Этим integration-тестам нужен явный существующий resolved JSON build. Они не выбирают latest и не собирают его автоматически. Укажите известный подготовленный build:

```bash
uv run --group test python -m pytest \
  tests/ingestion/markdown_export tests/ingestion/question_validation tests/rag \
  --input-build data/resolved/5etools/c3d53956346388b222aaaaf4637776f563e201b8/60d007f6a1c747e87aebb75bdb340996700e7e95e9af3ab8adb75b79413f3c81
```

Без `--input-build` соответствующие ingestion integration-тесты завершатся setup errors. Явные test directories также подключают нужную опцию pytest. Отдельные Node-тесты сборщика описаны в [README тестов](../../tests/README.md).

### Opt-in проверки с настоящими компонентами

Opt-in означает, что тест запускается только с явным разрешающим флагом. Перед живыми проверками остановите demo и другой runtime, выполняйте их последовательно:

```bash
uv run --group test python -m pytest tests/rag/integration/test_embedding_live.py --run-models
uv run --group test python -m pytest tests/rag/integration/test_qdrant_live.py --run-qdrant
uv run --group test python -m pytest tests/rag/integration/test_llama_live.py --run-llama
```

Первая проба загружает настоящий эмбеддер, вторая проверяет Qdrant на disposable коллекциях, включая persistence после restart, третья — установленную LLM и точность подсчёта prompt. По умолчанию они skipped; skip не подтверждает live-совместимость. Зафиксированные результаты и ограничения находятся в [TECHNICAL_PROBES.md](../rag/TECHNICAL_PROBES.md).

JSON и копии логов live-тестов сохраняются во временные каталоги pytest (`tmp_path`), а не в постоянные результаты. При необходимости путь виден в выводе pytest; срок хранения задаётся стандартными настройками pytest.
