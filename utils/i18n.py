"""Russian / English strings. Keys used inside widget templates are rendered at send time."""
from __future__ import annotations

LANGUAGES = ("ru", "en")

_RU: dict[str, str] = {
    # --- start / menu
    "greeting": "Привет! Я FormatBot 👋\nТвой универсальный помощник для работы с файлами.\n"
                "Конвертируй, сжимай и редактируй изображения, документы, аудио и видео прямо в Telegram.",
    "greeting_hint": "Отправьте файл — я определю его формат и покажу, что с ним можно сделать.\n"
                     "Если ниже не видно интерактивного меню, переключитесь на классические кнопки.",
    "btn_classic": "Классические кнопки",
    "btn_widgets": "Интерактивные виджеты",
    "cap_main": "FormatBot — главное меню",
    "menu_text": "<b>FormatBot</b> — главное меню\nОтправьте файл или выберите раздел.",
    "send_file_for": {
        "cv": "Отправьте файл, который нужно конвертировать.",
        "cz": "Отправьте файл, который нужно сжать.",
        "pt": "Отправьте PDF-файл.",
        "it": "Отправьте изображение (лучше как файл, без сжатия Telegram).",
    },
    "about": "<b>FormatBot</b> · Universal File Toolkit\n\n"
             "Конвертация, сжатие и редактирование файлов прямо в Telegram. Всё обрабатывается на сервере бота, "
             "без сторонних сервисов, бесплатно.\n\n"
             "Лимит входного файла: {limit}.\nФайлы удаляются сразу после обработки.",
    # --- widget common
    "wait": "Отправка…",
    "e_na": "Действие недоступно здесь",
    "e_rl": "Слишком часто, подождите пару секунд",
    "e_to": "Бот не ответил, попробуйте ещё раз",
    "e_busy": "Подождите завершения предыдущего действия",
    "e_fail": "Не получилось, попробуйте ещё раз",
    "u_b": "Б", "u_kb": "КБ", "u_mb": "МБ", "u_gb": "ГБ", "u_s": "с",
    # --- main widget
    "m_cv": "Конвертация", "m_cv_d": "Изменить формат файла",
    "m_cz": "Сжатие", "m_cz_d": "Уменьшить размер",
    "m_pt": "PDF", "m_pt_d": "Объединить, разделить, извлечь",
    "m_it": "Изображения", "m_it_d": "Размер, обрезка, поворот",
    "m_hi": "История", "m_se": "Настройки", "m_ab": "О боте",
    "m_done": "Обработано:", "m_saved": "сэкономлено",
    # --- file widget
    "k_image": "Изображение", "k_document": "Документ", "k_audio": "Аудио", "k_video": "Видео", "k_pdf": "PDF",
    "a_cv": "Конвертировать", "a_cz": "Сжать", "a_tl": "Инструменты",
    "i_fmt": "Формат", "i_size": "Размер", "i_res": "Разрешение", "i_dur": "Длительность", "i_pages": "Страниц",
    "f_none": "Для этого файла пока нет доступных действий",
    "cap_file": "{name} · {size}",
    # --- convert widget
    "cv_t": "Конвертация", "cv_to": "Преобразовать в", "cv_pick": "Выберите формат", "cv_go": "Конвертировать в",
    "q_t": "Качество", "q_max": "макс.", "q_hi": "высокое", "q_md": "среднее", "q_lo": "низкое",
    "cap_convert": "Конвертация · {name}",
    # --- compress widget
    "cz_t": "Сжатие", "cz_res": "Разрешение", "cz_go": "Сжать",
    "cap_compress": "Сжатие · {name}",
    "cz_mq": "Максимальное качество", "cz_bal": "Баланс", "cz_max": "Максимальное сжатие", "cz_cus": "Свои настройки",
    "cz_cus_d": "Качество и разрешение вручную",
    "cz_orig": "Исходное",
    "plan_q": "{fmt} · качество {q}",
    "plan_lossless": "{fmt} · без потерь",
    "plan_palette": "{fmt} · палитра {colors} цветов",
    "plan_side": "до {side}px",
    "plan_keep": "исходный размер",
    "plan_meta": "без метаданных",
    "plan_bmp": "BMP → PNG без потерь",
    # --- tools widget
    "tl_image": "Инструменты изображений",
    "tl_pdf": "Инструменты PDF",
    "tl_media": "Медиа-инструменты",
    "cap_tools": "Инструменты · {name}",
    "t_rs": "Изменить размер", "t_cr": "Обрезать", "t_ro": "Повернуть", "t_gr": "Чёрно-белое",
    "t_pd": "В PDF", "t_mt": "Удалить метаданные", "t_op": "Оптимизировать",
    "o_custom": "Свой…", "o_90": "90° →", "o_180": "180°", "o_270": "← 90°", "o_fh": "Отразить ↔", "o_fv": "Отразить ↕",
    # --- task widget
    "t_cancel": "Отменить", "t_rp": "Ещё раз", "t_mn": "Меню",
    "st_w": "В очереди", "st_p": "Обработка…", "st_d": "Готово", "st_f": "Ошибка", "st_c": "Отменено",
    "t_orig": "Исходный", "t_res": "Результат", "t_saved": "сэкономлено", "t_bigger": "файл стал больше",
    "cap_task": "Задача #{id} · {op}",
    # --- answers to widget requests
    "ans_open_below": "Открыл ниже ↓",
    "ans_started": "Задача #{id} создана ↓",
    "ans_cancelled": "Отменяю…",
    "ans_not_running": "Задача уже завершена",
    "ans_input": "Напишите параметры в чат ↓",
    "ans_sent": "Отправил в чат ↓",
    "ans_bad": "Некорректное действие",
    "ans_expired": "Это меню устарело, отправьте файл заново",
    "ans_limit": "Уже выполняется {n} задач(и). Дождитесь завершения.",
    "ans_need_file": "Сначала отправьте файл",
    # --- files
    "file_received": "Файл получен, проверяю…",
    "file_too_big": "Файл слишком большой: {size}. Максимум — {limit}.",
    "file_too_big_hint": "Telegram позволяет ботам скачивать файлы до 20 МБ. "
                         "Для больших файлов нужен локальный Bot API Server (см. README).",
    "file_unknown": "Не удалось определить тип файла. Поддерживаются изображения, PDF, документы, аудио и видео.",
    "file_broken": "Файл повреждён или не открывается.",
    "file_encrypted": "PDF защищён паролем — такой файл обработать нельзя.",
    "file_too_large_image": "Изображение слишком большое (более 90 мегапикселей).",
    "file_mismatch": "Расширение .{claimed} не совпадает с содержимым — это {real}.",
    "file_photo_note": "Фото, отправленные как «фото», Telegram уже сжал. Для лучшего качества отправляйте файлом.",
    "download_failed": "Не удалось скачать файл из Telegram. Попробуйте ещё раз.",
    # --- processing
    "res_caption": "{name}\n{orig} → {res} · {time} с",
    "res_caption_saved": "{name}\n{orig} → {res} (−{pct}%) · {time} с",
    "res_caption_bigger": "{name}\n{orig} → {res}: файл не уменьшился · {time} с",
    "res_not_smaller": "Сжатие не уменьшило файл: результат {res} при исходных {orig}. "
                       "Файл, вероятно, уже оптимизирован, поэтому увеличенную копию не отправляю.",
    "res_too_big": "Результат слишком большой для отправки через Telegram ({size}, максимум {limit}).",
    "err_timeout": "Обработка заняла слишком много времени и была остановлена.",
    "err_generic": "Во время обработки произошла ошибка.",
    "err_unsupported_target": "Этот формат недоступен.",
    "err_bad_params": "Некорректные параметры.",
    "err_crop_outside": "Область обрезки выходит за границы изображения.",
    "err_broken_file": "Файл повреждён или не открывается.",
    "err_image_too_large": "Изображение слишком большое.",
    "err_type_changed": "Содержимое файла не совпадает с ожидаемым типом.",
    "err_download_failed": "Не удалось скачать файл из Telegram. Попробуйте ещё раз.",
    "err_file_too_big": "Файл превышает допустимый размер.",
    "err_result_too_big": "Результат слишком большой для отправки через Telegram.",
    "err_unknown_type": "Не удалось определить тип файла.",
    "err_unsupported_type": "Этот тип файла не поддерживается.",
    "err_encrypted_pdf": "PDF защищён паролем.",
    "notify_done": "Готово: задача #{id}",
    # --- text input prompts
    "in_resize": "Напишите новый размер в пикселях, например <code>1280x720</code>.\n"
                 "Можно указать только ширину: <code>1280x</code> или высоту: <code>x720</code>.\n"
                 "Текущий размер: {w}×{h}. /cancel — отмена.",
    "in_crop": "Напишите область обрезки: <code>ширина x высота + X + Y</code>, например <code>800x600+100+50</code>.\n"
               "Размер изображения: {w}×{h}. /cancel — отмена.",
    "in_bad": "Не понял формат. Попробуйте ещё раз или /cancel.",
    "in_cancelled": "Отменено.",
    # --- history / settings
    "hist_title": "<b>История операций</b> · {total}",
    "hist_empty": "История пуста. Отправьте файл, чтобы начать.",
    "hist_row": "{icon} <b>{op}</b> · {date}\n   {src} → {dst}\n   {sizes}",
    "op_convert": "Конвертация", "op_compress": "Сжатие", "op_tool": "Инструмент",
    "st_completed": "✅", "st_failed": "⚠️", "st_cancelled": "⏹",
    "settings_title": "<b>Настройки</b>",
    "settings_body": "Язык: {lang}\nКачество по умолчанию: {q}\nРежим сжатия по умолчанию: {mode}\n"
                     "Уведомления о готовности: {notif}\nИнтерфейс: {ui}",
    "stats_body": "\n\n<b>Статистика</b>\nВсего операций: {total}\nУспешно: {ok}\nОшибок: {failed}\n"
                  "Конвертаций: {conv}\nСэкономлено: {saved}",
    "on": "вкл", "off": "выкл",
    "ui_widget": "виджеты", "ui_classic": "классические кнопки",
    "s_lang": "🌐 Язык", "s_quality": "🎚 Качество: {q}", "s_mode": "🗜 Сжатие: {mode}",
    "s_notif": "🔔 Уведомления: {v}", "s_ui": "🧩 Интерфейс: {v}", "s_clear": "🗑 Очистить историю",
    "s_clear_confirm": "Удалить всю историю операций? Это нельзя отменить.",
    "s_clear_yes": "Да, удалить", "s_clear_no": "Нет",
    "s_cleared": "История очищена ({n} записей).",
    "btn_back": "← Назад", "btn_prev": "←", "btn_next": "→",
    "classic_ui_on": "Включены классические кнопки. Вернуть виджеты можно в настройках.",
    "widget_ui_on": "Включены интерактивные виджеты.",
    "widget_failed": "Интерактивный виджет не отправился, показываю обычные кнопки.",
    # --- classic keyboards
    "c_file": "<b>{name}</b>\n{kind} · {ext} · {size}{extra}\n\nВыберите действие:",
    "c_convert": "Конвертировать <b>{name}</b> в:",
    "c_compress": "Сжатие <b>{name}</b> ({size}):",
    "c_tools": "<b>{title}</b> · {name}",
    "c_task": "{icon} Задача #{id} · {op}\n{status}",
}

_EN: dict[str, str] = {
    "greeting": "Hi! I'm FormatBot 👋\nYour universal file assistant.\n"
                "Convert, compress and edit images, documents, audio and video right in Telegram.",
    "greeting_hint": "Send me a file — I'll detect its format and show what can be done with it.\n"
                     "If you don't see the interactive menu below, switch to classic buttons.",
    "btn_classic": "Classic buttons",
    "btn_widgets": "Interactive widgets",
    "cap_main": "FormatBot — main menu",
    "menu_text": "<b>FormatBot</b> — main menu\nSend a file or pick a section.",
    "send_file_for": {
        "cv": "Send the file you want to convert.",
        "cz": "Send the file you want to compress.",
        "pt": "Send a PDF file.",
        "it": "Send an image (preferably as a file, without Telegram compression).",
    },
    "about": "<b>FormatBot</b> · Universal File Toolkit\n\n"
             "Convert, compress and edit files right in Telegram. Everything is processed on the bot's server, "
             "no third-party services, free.\n\n"
             "Input file limit: {limit}.\nFiles are deleted right after processing.",
    "wait": "Sending…",
    "e_na": "Not available here",
    "e_rl": "Too fast, wait a couple of seconds",
    "e_to": "The bot did not answer, try again",
    "e_busy": "Wait for the previous action",
    "e_fail": "Something went wrong, try again",
    "u_b": "B", "u_kb": "KB", "u_mb": "MB", "u_gb": "GB", "u_s": "s",
    "m_cv": "Convert", "m_cv_d": "Change the file format",
    "m_cz": "Compress", "m_cz_d": "Reduce the size",
    "m_pt": "PDF tools", "m_pt_d": "Merge, split, extract",
    "m_it": "Image tools", "m_it_d": "Resize, crop, rotate",
    "m_hi": "History", "m_se": "Settings", "m_ab": "About",
    "m_done": "Processed:", "m_saved": "saved",
    "k_image": "Image", "k_document": "Document", "k_audio": "Audio", "k_video": "Video", "k_pdf": "PDF",
    "a_cv": "Convert", "a_cz": "Compress", "a_tl": "Tools",
    "i_fmt": "Format", "i_size": "Size", "i_res": "Resolution", "i_dur": "Duration", "i_pages": "Pages",
    "f_none": "No actions are available for this file yet",
    "cap_file": "{name} · {size}",
    "cv_t": "Convert", "cv_to": "Convert to", "cv_pick": "Pick a format", "cv_go": "Convert to",
    "q_t": "Quality", "q_max": "max", "q_hi": "high", "q_md": "medium", "q_lo": "low",
    "cap_convert": "Convert · {name}",
    "cz_t": "Compress", "cz_res": "Resolution", "cz_go": "Compress",
    "cap_compress": "Compress · {name}",
    "cz_mq": "Maximum quality", "cz_bal": "Balanced", "cz_max": "Maximum compression", "cz_cus": "Custom",
    "cz_cus_d": "Set quality and resolution",
    "cz_orig": "Original",
    "plan_q": "{fmt} · quality {q}",
    "plan_lossless": "{fmt} · lossless",
    "plan_palette": "{fmt} · {colors}-colour palette",
    "plan_side": "up to {side}px",
    "plan_keep": "original size",
    "plan_meta": "no metadata",
    "plan_bmp": "BMP → lossless PNG",
    "tl_image": "Image tools",
    "tl_pdf": "PDF tools",
    "tl_media": "Media tools",
    "cap_tools": "Tools · {name}",
    "t_rs": "Resize", "t_cr": "Crop", "t_ro": "Rotate", "t_gr": "Grayscale",
    "t_pd": "To PDF", "t_mt": "Remove metadata", "t_op": "Optimize",
    "o_custom": "Custom…", "o_90": "90° →", "o_180": "180°", "o_270": "← 90°", "o_fh": "Flip ↔", "o_fv": "Flip ↕",
    "t_cancel": "Cancel", "t_rp": "Again", "t_mn": "Menu",
    "st_w": "Waiting", "st_p": "Processing…", "st_d": "Completed", "st_f": "Failed", "st_c": "Cancelled",
    "t_orig": "Original", "t_res": "Result", "t_saved": "saved", "t_bigger": "the file got bigger",
    "cap_task": "Task #{id} · {op}",
    "ans_open_below": "Opened below ↓",
    "ans_started": "Task #{id} created ↓",
    "ans_cancelled": "Cancelling…",
    "ans_not_running": "The task has already finished",
    "ans_input": "Type the parameters in the chat ↓",
    "ans_sent": "Sent to the chat ↓",
    "ans_bad": "Invalid action",
    "ans_expired": "This menu is outdated, send the file again",
    "ans_limit": "{n} task(s) are already running. Wait until they finish.",
    "ans_need_file": "Send a file first",
    "file_received": "File received, checking…",
    "file_too_big": "The file is too big: {size}. The maximum is {limit}.",
    "file_too_big_hint": "Telegram lets bots download files up to 20 MB. "
                         "Bigger files need a local Bot API Server (see README).",
    "file_unknown": "Could not detect the file type. Images, PDF, documents, audio and video are supported.",
    "file_broken": "The file is damaged or cannot be opened.",
    "file_encrypted": "The PDF is password-protected and cannot be processed.",
    "file_too_large_image": "The image is too large (over 90 megapixels).",
    "file_mismatch": "The .{claimed} extension does not match the content — it is {real}.",
    "file_photo_note": "Photos sent as \"photo\" are already compressed by Telegram. Send as a file for best quality.",
    "download_failed": "Could not download the file from Telegram. Please try again.",
    "res_caption": "{name}\n{orig} → {res} · {time} s",
    "res_caption_saved": "{name}\n{orig} → {res} (−{pct}%) · {time} s",
    "res_caption_bigger": "{name}\n{orig} → {res}: the file did not get smaller · {time} s",
    "res_not_smaller": "Compression did not reduce the file: the result is {res} vs the original {orig}. "
                       "The file is probably already optimized, so I won't send a bigger copy.",
    "res_too_big": "The result is too big to send via Telegram ({size}, max {limit}).",
    "err_timeout": "Processing took too long and was stopped.",
    "err_generic": "An error occurred during processing.",
    "err_unsupported_target": "This format is not available.",
    "err_bad_params": "Invalid parameters.",
    "err_crop_outside": "The crop area is outside the image.",
    "err_broken_file": "The file is damaged or cannot be opened.",
    "err_image_too_large": "The image is too large.",
    "err_type_changed": "The file content does not match the expected type.",
    "err_download_failed": "Could not download the file from Telegram. Please try again.",
    "err_file_too_big": "The file exceeds the allowed size.",
    "err_result_too_big": "The result is too big to send via Telegram.",
    "err_unknown_type": "Could not detect the file type.",
    "err_unsupported_type": "This file type is not supported.",
    "err_encrypted_pdf": "The PDF is password-protected.",
    "notify_done": "Done: task #{id}",
    "in_resize": "Type the new size in pixels, e.g. <code>1280x720</code>.\n"
                 "Width only: <code>1280x</code>, height only: <code>x720</code>.\n"
                 "Current size: {w}×{h}. /cancel to abort.",
    "in_crop": "Type the crop area: <code>width x height + X + Y</code>, e.g. <code>800x600+100+50</code>.\n"
               "Image size: {w}×{h}. /cancel to abort.",
    "in_bad": "I didn't get that. Try again or /cancel.",
    "in_cancelled": "Cancelled.",
    "hist_title": "<b>History</b> · {total}",
    "hist_empty": "History is empty. Send a file to start.",
    "hist_row": "{icon} <b>{op}</b> · {date}\n   {src} → {dst}\n   {sizes}",
    "op_convert": "Convert", "op_compress": "Compress", "op_tool": "Tool",
    "st_completed": "✅", "st_failed": "⚠️", "st_cancelled": "⏹",
    "settings_title": "<b>Settings</b>",
    "settings_body": "Language: {lang}\nDefault quality: {q}\nDefault compression: {mode}\n"
                     "Completion notifications: {notif}\nInterface: {ui}",
    "stats_body": "\n\n<b>Statistics</b>\nTotal operations: {total}\nSuccessful: {ok}\nErrors: {failed}\n"
                  "Conversions: {conv}\nSaved: {saved}",
    "on": "on", "off": "off",
    "ui_widget": "widgets", "ui_classic": "classic buttons",
    "s_lang": "🌐 Language", "s_quality": "🎚 Quality: {q}", "s_mode": "🗜 Compression: {mode}",
    "s_notif": "🔔 Notifications: {v}", "s_ui": "🧩 Interface: {v}", "s_clear": "🗑 Clear history",
    "s_clear_confirm": "Delete the whole operation history? This cannot be undone.",
    "s_clear_yes": "Yes, delete", "s_clear_no": "No",
    "s_cleared": "History cleared ({n} records).",
    "btn_back": "← Back", "btn_prev": "←", "btn_next": "→",
    "classic_ui_on": "Classic buttons are on. You can switch back to widgets in the settings.",
    "widget_ui_on": "Interactive widgets are on.",
    "widget_failed": "The interactive widget could not be sent, showing regular buttons.",
    "c_file": "<b>{name}</b>\n{kind} · {ext} · {size}{extra}\n\nChoose an action:",
    "c_convert": "Convert <b>{name}</b> to:",
    "c_compress": "Compress <b>{name}</b> ({size}):",
    "c_tools": "<b>{title}</b> · {name}",
    "c_task": "{icon} Task #{id} · {op}\n{status}",
}

_STRINGS = {"ru": _RU, "en": _EN}


def norm_lang(lang: str | None) -> str:
    return lang if lang in _STRINGS else "en"


def t(lang: str | None, key: str, **kwargs: object) -> str:
    table = _STRINGS[norm_lang(lang)]
    value = table.get(key)
    if value is None:
        value = _EN.get(key, key)
    if not isinstance(value, str):
        raise TypeError(f"i18n key {key!r} is not a plain string")
    return value.format(**kwargs) if kwargs else value


def t_map(lang: str | None, key: str) -> dict[str, str]:
    value = _STRINGS[norm_lang(lang)].get(key) or _EN[key]
    assert isinstance(value, dict)
    return value


def all_keys(lang: str) -> set[str]:
    return set(_STRINGS[lang])
