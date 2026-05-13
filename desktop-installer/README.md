# Desktop Installer (Windows EXE)

Эта папка содержит отдельный desktop-установщик для системы тестирования.
Основной `backend`/`frontend` проект не меняется: desktop-приложение запускает тот же backend и тот же `/ui` внутри окна приложения.

## Что внутри

- `launcher.py` — desktop-оболочка (pywebview) + запуск backend (uvicorn)
- `ui/connect.html` — экран подключения в стиле ESBMonitor
- `build/build_portable.ps1` — сборка portable desktop-версии (PyInstaller)
- `build/installer.iss` — сценарий Inno Setup
- `build/build_installer.ps1` — сборка установщика

## Автоподключение / автонастройка

Экран подключения сохраняет параметры в:

- `%APPDATA%\ParagraphTestSystemDesktop\connection.json`

Сохраняются:

- IP/host
- port
- module_name
- software_name
- login
- пароль (если включено «Запомнить пароль»)

При следующем запуске значения подставляются автоматически.

## Требования для сборки

1. Windows 10/11 x64
2. Python 3.12+
3. Установленный Inno Setup 6
   - по умолчанию путь: `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`

## Сборка portable EXE

Из папки `desktop-installer`:

```powershell
cd d:\par-test-automation-system\desktop-installer
.\build\build_portable.ps1
```

Результат:

- `desktop-installer\dist\ParagraphTestSystemDesktop\ParagraphTestSystemDesktop.exe`

## Сборка установщика (Setup.exe)

```powershell
cd d:\par-test-automation-system\desktop-installer
.\build\build_installer.ps1
```

Результат:

- `desktop-installer\dist-installer\ParagraphTestSystemDesktop-Setup.exe`

Передавать нужно:

- `ParagraphTestSystemDesktop-Setup.exe`

Это полноценный установщик для ПК/ВМ.

## Установка у тестировщика

1. Запустить `ParagraphTestSystemDesktop-Setup.exe`.
2. Пройти шаги мастера установки.
3. Запустить приложение через ярлык `Paragraph Test System`.
4. На экране подключения указать:
   - IP/host ИШД
   - порт
   - module name
   - software name
   - логин/пароль
5. Нажать `Войти`.
6. После запуска backend автоматически откроется основной UI системы тестирования.

## Использование на виртуальной машине

1. Скопировать `ParagraphTestSystemDesktop-Setup.exe` в VM.
2. Установить как обычное Windows-приложение.
3. Запустить и заполнить подключение к ИШД.
4. Дальше работа аналогична физическому ПК.

## Важно

- Desktop-версия не меняет логику тестов, контрактов API или дизайн основного web-интерфейса.
- Это оболочка для уже готовой системы, с отдельным экраном подключения и локальным запуском backend.
