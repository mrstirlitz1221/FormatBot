# FormatBot — архитектура

## Итоги исследования (этап 1, 13.11.2026)

- Python 3.12.0 (`py -3.12`), проект в `.venv`. FFmpeg, LibreOffice, Ghostscript **не установлены**.
- Bot API 10.4 (09.11.2026) добавил виджеты. Источник истины: https://core.telegram.org/bots/widgets и
  разделы `sendWidget`, `answerWidgetQuery`, `editMessageWidgetData`, `WidgetQuery` в https://core.telegram.org/bots/api.
- aiogram 3.31.0 (последний релиз, 26.08.2026) = Bot API 10.3, виджетов нет →
  `api/widget_api.py`: свои `TelegramMethod`-классы + `WidgetQueryMiddleware`, который достаёт `widget_query`
  из `Update.model_extra` (у моделей aiogram `extra="allow"`). `allowed_updates` дополняется вручную в `bot.py`.
- Лимиты файлов облачного Bot API: скачивание 20 МБ, отправка 50 МБ (локальный сервер — 2000 МБ).

## Поток данных

```
Telegram ──update──► Dispatcher
   ├─ widget_query ──► WidgetQueryMiddleware ──► widgets/widget_handlers.on_widget_query
   │                                              └─► handlers/actions.handle_action ─► answerWidgetQuery (≤15 с)
   ├─ callback "u:<action>" ──► handlers/callbacks ──► handlers/actions.handle_action ─► answerCallbackQuery
   └─ message (файл) ──► handlers/files: лимит → скачать → detect_file → uploaded_files → карточка файла

handle_action: (chat_id, message_id) → widget_sessions (тип экрана, file_id, владелец) → проверка → действие
  "go:…" / "t:…" ─► tasks/worker.start_operation ─► карточка задачи + TaskManager.submit
TaskManager (семафор, лимит на пользователя, таймаут, отмена) ─► OperationJob.run:
  скачать в TaskWorkspace → повторно определить тип → Processor.run (to_thread) → send_document → история
  → editMessageWidgetData(финальное состояние) → удалить папку задачи
```

## Протокол действий (общий для виджетов и кнопок, ≤ 64 байта)

| Экран (`widget_type`) | Действия |
|---|---|
| main | `cv` `cz` `pt` `it` (запомнить намерение) · `hi` `se` `ab` |
| file | `cv` `cz` `tl` — открыть экран операции |
| convert | `go:<fmt>[:<q>]` |
| compress | `go:<mode>` · `go:cus:<q>:<res>` |
| tools | `t:<tool>[:<opt>]`; опция `in` → ввод текста через FSM `ToolInput` |
| task | `x` отмена · `rp` ещё раз · `mn` меню |

Кнопки fallback-режима используют те же строки с префиксом `u:`. Значения всегда сверяются со списками
процессора (`Processor.parse_*`), а не доверяются клиенту.

## Состояние виджетов (`chat_data`, контракт с шаблонами)

- main `{n, s}` — обработано, сэкономлено байт
- file `{n, e, k, z, r?, d?, p?, w?, a}`
- convert `{n, f, o[], l[], q}`
- compress `{n, z, m[[id,label,desc]], d, q, r[[id,label]]}`
- tools `{n, t[[id,label,icon,[[opt,label]]]]}`
- task `{s: w|p|d|f|c, o, q?, p?, a?, b?, t?, n?, c?, x?, e?}`

Серверное состояние (`widget_sessions.state`): `{f: uploaded_file_id}` или `{task, f, cat}`.

## Решения, отличающиеся от исходной структуры

- `processing.html` + `result.html` объединены в `task.html`: одна карточка проходит ожидание → прогресс →
  результат через `editMessageWidgetData`, без лишних сообщений в чате.
- PDF/Image/Media Tools — один шаблон `tools.html` с заголовком и списком инструментов от процессора.
- Вместо `conversion_service.py`/`compression_service.py` — реестр процессоров `services/operations.py`:
  на каждый тип файла один `Processor` (convert_targets, compress_spec, tools, parse_*, run).
- Файлы не хранятся: в БД только `file_id` Telegram, файл скачивается заново на каждую задачу.

## Этап 5 (PDF и документы)

- `services/pdf_service.py` — PyMuPDF: merge/split/render/text/rotate/select, `compress_pdf`
  (`rewrite_images` + `garbage=4`, deflate, object streams, без метаданных), собственный `pdf_to_docx`.
- `services/document_service.py` — LibreOffice (`--convert-to` с явными фильтрами, профиль
  `-env:UserInstallation` в папке задачи), встроенные конвертации через `pymupdf.Story` и python-docx,
  `compress_office` для ZIP-контейнеров (порядок и имена частей сохраняются, `mimetype` ODF — первым и без сжатия).
- `services/document_processor.py` — `PdfProcessor`, `DocumentProcessor`.
- `services/external_tools.py` — `run_process` (только список аргументов, таймаут, kill дерева процессов),
  `set_tools()` вызывается в `bot.py` с путями из конфигурации.
- Взаимодействие инструментов: `ToolSpec.input` / `input_options` → `ToolInput` (текст в чате, `Processor.parse_text_input`);
  `ToolSpec.collect` / `collect_options` → `CollectFiles` (досылка файлов, кнопки `c:go` / `c:x`,
  `start_operation(..., extras)` скачивает их в `input_1..N`).

## Этап 6 (аудио и видео)

- `services/media_service.py` — ffprobe (`probe`, синхронно, вызывается детектором), `run_ffmpeg` с
  `-progress pipe:1` (проценты по `out_time_us` / длительности), аудио/видео-конвертации, GIF в два прохода,
  извлечение аудио и кадров, разбор отрезков времени.
- `services/media_processor.py` — `AudioProcessor`, `VideoProcessor`. Видео-пресеты: `VIDEO_PRESETS`.
  Масштабирование ограничивает короткую сторону и не увеличивает; размеры всегда чётные (yuv420p).
- `services/external_tools.run_process_lines` — построчное чтение stdout с параллельным чтением stderr.
- Детектор уточняет тип по реальным потокам (MP4 без видео → аудио `m4a`; обложка MP3 не считается видео)
  и отклоняет файлы длиннее 4 часов.
- `Processor.operation_warning` — честное предупреждение при старте задачи (потери качества и т.п.).

## Как добавить новый тип файла

1. Подкласс `Processor` в `services/`, `register(...)` в конце модуля, импорт в `bot.py` и `tests/conftest.py`.
2. Внешние программы — только `run_process` / `run_process_lines` со списком аргументов; пути из
   `services.external_tools`; если программы нет — не показывать операции.
3. Новые строки — в оба словаря `utils/i18n.py`. После правки шаблонов — `pytest tests/test_widgets.py`.

## Известные ограничения

- Работа в потоках (`to_thread`) не прерывается при отмене: результат просто отбрасывается.
- Позиция в очереди показывается в момент постановки и не пересчитывается.
- Реальное отображение виджетов в клиентах Telegram не проверено автоматически — нужна ручная проверка на боте.
