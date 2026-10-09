# Лабораторная работа №1 — локальные LLM

Проект для запуска **Gemma-4-E2B-it**, **Phi-4-mini-instruct** и **Qwen3.5-4B** через OpenAI-совместимый REST API llama.cpp. Эксперименты охватывают генерацию текста, классификацию и суммаризацию; ответы и измерения сохраняются для последующего анализа.

## Отчеты

- [Краткий отчет](report/report_short.md) — сжатое описание экспериментов и анализ результатов.
- [Полный отчет](report/report_completed.md) — подробный разбор ответов, настроек и производительности.

## Организация проекта

| Path | Contents |
| --- | --- |
| [src/](src/) | Код экспериментов: CLI, HTTP-клиент и управление сервером llama.cpp. Точка входа — [run_experiments.py](src/run_experiments.py), пресеты и список задач — [globals.py](src/globals.py). |
| [prompts/](prompts/) | Три промпта на русском языке; `p2_answers.txt` содержит эталонные метки классификации. |
| [notebooks/analysis.ipynb](notebooks/analysis.ipynb) | Загрузка сохраненных запусков, подготовка таблиц и графиков. |
| [results/](results/) | Исходные результаты в папках `gemma4`, `phi-4-mini` и `qwen3.5-4b`. |
| [results/report_materials/](results/report_materials/) | Готовые материалы: `preset_comparison/<model>/<task>/` для сравнения настроек и `model_comparison/<task>/` для сравнения моделей. |
| [report/](report/) | Версии отчета. |
| [pyproject.toml](pyproject.toml), [uv.lock](uv.lock) | Зависимости Python и зафиксированные версии окружения. |

В `preset_comparison` тексты ответов находятся в `responses_<preset>.md`, таблицы — в `tables/`, изображения и интерактивные HTML-графики — в `figures/`. В `model_comparison` имена артефактов содержат суффикс пресета.

## Запуск экспериментов

Нужны **Python ≥ 3.13**, **uv**, установленный **llama.cpp** и GGUF-веса **Q4_K_M**. Ссылки на использованные веса приведены в полном отчете; сами веса хранятся вне репозитория. Сохраненные эксперименты выполнены сборкой llama.cpp `b11046-60081bb2b`.

Из корня репозитория установите зависимости:

```bash
uv sync --locked --group dev
```

Запустите эксперимент для одной модели, заменив путь к весам:

```bash
uv run python src/run_experiments.py \
  --model /path/to/models/gemma-4-E2B-it-Q4_K_M.gguf \
  --name gemma4 \
  --repeats 5 \
  --base-seed 42 \
  --context-size 4096 \
  --output results_reproduced/gemma4
```

Для двух других моделей повторите команду с соответствующими значениями `--model`, `--name` и `--output`:

| Model name | GGUF filename | Output directory |
| --- | --- | --- |
| phi-4-mini | Phi-4-mini-instruct-Q4_K_M.gguf | results_reproduced/phi-4-mini |
| qwen3.5-4b | Qwen3.5-4B-Q4_K_M.gguf | results_reproduced/qwen3.5-4b |

Скрипт сам запускает и останавливает сервер. По умолчанию используется команда `llama serve` и адрес `127.0.0.1:9931`. Для отдельного бинарного файла сервера передайте `--server-command "/path/to/llama-server"`. Полный список опций:

```bash
uv run python src/run_experiments.py --help
```

При пяти повторах выполняются 60 измеряемых запросов на модель: три задачи × четыре пресета × пять seed (42–46). Прогревочные запросы в результаты не входят. В каталоге `--output` создаются:

- `metadata.json` — параметры запуска, настройки сервера и промпты;
- `runs.jsonl` — ответы и измерения каждого запроса;
- `server.log` — журнал llama.cpp.

Без `--output` результаты записываются в `results/<name>/`. Существующие файлы запуска защищены от перезаписи; `--overwrite` заменяет три перечисленных файла в выбранном каталоге.

## Воспроизведение таблиц и графиков

Повторный запуск моделей не требуется для анализа уже сохраненных данных. Откройте [ноутбук](notebooks/analysis.ipynb), выберите окружение проекта и выполните ячейки сверху вниз. **Рабочая директория ядра должна быть `notebooks/`**: от нее определяется корень проекта.

Например, из корня репозитория можно запустить JupyterLab с этой рабочей директорией:

```bash
cd notebooks
uv run --with jupyterlab jupyter lab analysis.ipynb
```

Для экспорта Plotly-графиков в PNG Kaleido требуется **Chrome**. Если он не установлен, его можно получить командой `uv run kaleido_get_chrome`.

По умолчанию ноутбук читает `results/` и сохраняет артефакты в `results/report_materials/`. Для новых запусков в ячейке настройки путей задайте:

```python
RESULTS_DIR = PROJECT_ROOT / "results_reproduced"
```

Тогда материалы будут созданы в `results_reproduced/report_materials/`. Ноутбук формирует Markdown-таблицы и ответы, PNG-графики Matplotlib и Plotly, а также интерактивные HTML-версии. Повторное выполнение обновляет артефакты; значения времени зависят от оборудования и условий запуска.
