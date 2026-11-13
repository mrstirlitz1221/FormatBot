# FormatBot — заметки для разработки

- Python: `.venv\Scripts\python.exe` (Python 3.12). Команда `python` в системе — заглушка Microsoft Store.
- Тесты: `.venv\Scripts\python.exe -m pytest` (должны проходить все).
- Архитектура, протокол действий, контракт `chat_data` и план этапов 5–9: `docs/ARCHITECTURE.md`.
- aiogram 3.31 не знает Bot API 10.4: методы/типы виджетов — только через `api/widget_api.py`.
  Не выдумывать поля — сверяться с https://core.telegram.org/bots/widgets и https://core.telegram.org/bots/api.
- Шаблоны виджетов `widgets/templates/*.html`: JS без `//`-комментариев и с `;` (минификация склеивает строки),
  строки через `[[key]]` / `[[js:key]]`, лимит 4096 Б после zlib-9 проверяется тестами.
- Новые тексты — в оба языка `utils/i18n.py`.
- Хендлеры регистрируются в `build_router()` каждого модуля `handlers/` (роутер создаётся заново на каждый Dispatcher).
