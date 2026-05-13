# Paragraph Test Automation System

Система тестирования сборок СПО Параграф:
- `user-dicts` — проверка плагина справочников через ИШД (XML -> ИШД -> Параграф).
- `user-dicts-rest` — REST-операции Параграфа.
- `paragraph` — просмотр/выгрузка документов из БД Параграфа.
- `autotest` — единый автопрогон с отчётом в UI и JSON.

## Multi-target (главная идея)

Один backend/UI обслуживает **много VM/сборок**.

Каждая VM описывается как `target`-профиль:
- параметры ИШД;
- `PARAGRAPH_REST_BASE_URL`;
- (опционально) `PARAGRAPH_DB_DSN`.

Пользователь выбирает target в UI, и дальше все запросы идут в выбранную VM.
Код менять не нужно.

## Как коллеги работают (без разработки)

1. Разворачивают новую сборку Параграфа в VM.
2. Открывают UI: `http://<server-ip>:8000/ui`.
3. В верхней панели нажимают `Автонастроить VM`:
   - система берёт IP текущей VM из запроса браузера,
   - создаёт/обновляет target-профиль автоматически,
   - делает его активным.
   - для NAT-режима (если вернулся loopback) достаточно заполнить только поле `IP узла ИШД` и нажать кнопку ещё раз.
4. Если нужно — корректируют профиль вручную в блоке `Профили стендов (VM/сборок)`.
5. В блоке `Автотест справочников`:
   - выбирают предустановленный справочник из списка,
   - нажимают `Запустить автотест`.
6. Смотрят:
   - шаги с `ok/fail` в UI,
   - полный JSON-отчёт (и историю прогонов).
7. Если падение не со стороны нашей системы, отдают отчёт разработчикам API Параграфа.

## Безопасность автопрогона

- Предустановленные справочники тестируются в read-only шагах.
- CRUD-сценарий выполняется на временном справочнике с префиксом автотеста.
- Массовое удаление защищено (блокируется без явного разрешения/условий).

## Запуск backend

```powershell
cd backend
poetry install
poetry run alembic upgrade head
poetry run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

UI / Swagger:
- `http://127.0.0.1:8000/ui`
- `http://127.0.0.1:8000/docs`
- `http://<server-ip>:8000/ui`
- `http://<server-ip>:8000/docs`

Для VirtualBox NAT (гость -> хост):
- в VM обычно открывают `http://10.0.2.2:8000/ui`

## Переменные .env (fallback target)

Если в запросе не выбран `target_id`, backend использует `.env`:
- `BACKEND_DB_DSN`
- `ISHD_HOST`
- `ISHD_PORT`
- `ISHD_HOST_ID`
- `ISHD_SOFTWARE_NAME`
- `ISHD_LOGIN`
- `ISHD_PASSWORD`
- `ISHD_TARGET_HOST_IDS`
- `PARAGRAPH_REST_BASE_URL`
- `PARAGRAPH_DB_DSN` (опционально)

## API multi-target

Любой запрос можно направить в нужный профиль:
- query: `?target_id=<id>`
- header: `X-Target-ID: <id>`

UI делает это автоматически по выбранному target.

# 1) Перейти в backend
cd d:\par-test-automation-system\backend

# 2) Установить Poetry (если не установлен)
py -m pip install --user poetry

# 3) Установить зависимости проекта
py -m poetry install

# 4) Применить миграции
py -m poetry run alembic upgrade head

# 5) Запустить backend + UI
py -m poetry run uvicorn src.main:app --host 0.0.0.0 --port 8000

## Desktop-приложение (Windows)

Поддерживается установка как обычного Windows-приложения (WebView + встроенный backend):
- сборка portable: `desktop/dist/ParagraphTestSystem/ParagraphTestSystem.exe`
- инсталлятор: `desktop/dist-installer/ParagraphTestSystem-Setup.exe`

См. инструкции:
- `desktop/README.md`
- `docs/USER_GUIDE_DESKTOP_RU.md`
