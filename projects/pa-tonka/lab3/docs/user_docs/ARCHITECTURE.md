# Архитектура

Канонические XPHB/XDMG/XMM Markdown и source_map → точные Unicode half-open spans → EmbeddingGemma 2 GPU-worker → собственный Qdrant. QueryEncoder работает на CPU и сохраняется между запросами. Retriever возвращает исходный текст, scores, index/build IDs, sections, честные page attribution и hashes.

Рабочий RagConfig не зависит от датасета, оценивания, LLM и интерфейса. R3/R9 меняют embedding input и build identity, не точность привязки к исходнику. Index manifest содержит весь набор chunks для независимого Recall/MRR. Отсутствие gold не препятствует поиску.

RuntimeSession владеет lock и дочерними process groups. Смерть parent не освобождает унаследованную блокировку, пока жив child; cleanup не завершает посторонние процессы. Неопределённая ошибка endpoint не означает свободный порт. Qdrant изолирован портами 6343/6344 и data/qdrant; ready collection проверяется по паспорту, payloads, количеству и ownership.

Математика retrieval-оценивания сохранена: пересечение ≥50% меньшего span, hash equality, P/R@1/5/10, MRR@10; короткая выдача не меняет знаменатель Precision. Локальные метрики и live-пробы относятся к lab3 только после нового запуска.

## Модель и подсчёт

NativeLLM переиспользует ChatOpenAI и родной GGUF tokenizer. HTTP-hook видит итоговый wire body после сериализации OpenAI: system, messages, schemas, calls/results, template и reasoning поля. Перед отправкой body без изменения передаётся native input_tokens. Guard проверяет `input + completion reserve + safety <= server window`; после ответа проверяет parity с usage. Messages-only счётчик и tiktoken не используются как замена полной проверки.

Предварительный body для middleware строится тем же ChatOpenAI serializer. Счётчик физического окна остаётся последней защитой в самом transport. Отдельный порог приложения 8192 нужен для последующего сокращения; он не равен окну сервера 16384. Off отправляет enable_thinking=false/effort=none/budget0, budgeted — true/budget512 без none; CLI сервера получает тот же профиль.
