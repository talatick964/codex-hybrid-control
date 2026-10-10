# Установка

Готовый ZIP есть также **[в Telegram](https://t.me/aislopprogs/10)**.

## Готовая программа

Нужны **Windows, установленный Codex с CLI и собственный API-ключ**. Поддерживаемый протокол провайдера — Responses API.

1. [Скачай ZIP для Windows](https://github.com/talatick964/codex-hybrid-control/releases/latest/download/Codex-Hybrid-Control-7.3.4-Windows.zip).
2. Распакуй архив в обычную папку. Запусти **Codex-Hybrid-Control.exe** — Python не нужен.
3. Открой **«Подключение API»**, укажи ключ и выбери модель. Для другого провайдера создай профиль с его адресом.
4. Посмотри изменения, нажми **«Применить»**, затем **«Проверить и исправить всё»**.
5. В Codex CLI открой `/hooks` и подтверди обработчик Hybrid Control, если он ещё не доверенный. Перезапусти Codex и создай новый сеанс.

## Обновление

Закрой старую панель, распакуй новую и запусти её. Если включён «Обычный Codex», сначала нажми **«Восстановить Hybrid»**. Затем нажми **«Проверить и исправить всё»** и перезапусти Codex. Ключи и настройки хранятся локально, отдельно от программы.

## Вернуться к обычному Codex

В разделе **«Восстановление»** отключи Hybrid Control. Там же можно включить его обратно. После переключения перезапусти Codex.

## Если что-то не работает

Начни с **«Проверить и исправить всё»**. Если ошибка осталась, [создай обращение](https://github.com/talatick964/codex-hybrid-control/issues/new/choose) или напиши в [Telegram](https://t.me/aislopprogs). Укажи версию и действия перед ошибкой; ключи и личные логи не прикладывай.

## Из исходников

Windows, Python 3.10+:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe control_entry.py
```

Сборка EXE:

```powershell
python -m venv .build-venv
.build-venv/Scripts/python.exe -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File build_exe.ps1 -PythonExecutable .build-venv/Scripts/python.exe
```

Готовые файлы появятся в `dist`. Проверки: `python -m pytest tests -q` после установки `requirements-dev.txt`. Подробности защиты — в [FIX-7.3.4.md](../FIX-7.3.4.md).


---

<a id="english"></a>

## English

**Requirements:** Windows, Codex with its CLI, your own API key, and a Responses-compatible provider. No Python is needed for the packaged app. The app interface is currently in Russian.

1. Download the ZIP from [GitHub](https://github.com/talatick964/codex-hybrid-control/releases/latest/download/Codex-Hybrid-Control-7.3.4-Windows.zip) or [Telegram](https://t.me/aislopprogs/10).
2. Extract it and run **Codex-Hybrid-Control.exe**.
3. Open **«Подключение API»** (API connection), enter your key and choose a model. Create a connection profile for a different provider.
4. Review the preview, click **«Применить»** (Apply), then **«Проверить и исправить всё»** (Check and repair everything).
5. Open `/hooks` in Codex CLI and trust the Hybrid Control handler if needed. Restart Codex and start a new session.

**Updating:** close the old panel and extract the new version. If Standard Codex mode is enabled, click **«Восстановить Hybrid»** (Restore Hybrid) first. Run the repair check and restart Codex. Your settings are stored locally, separately from the app.

**Standard Codex:** open **«Восстановление»** (Recovery) to disable or restore Hybrid Control, then restart Codex.

**Need help?** Use [Issues](https://github.com/talatick964/codex-hybrid-control/issues/new/choose) or [Discussions](https://github.com/talatick964/codex-hybrid-control/discussions). Include your version and steps to reproduce; never post keys or private logs.

**Build an EXE:**

```powershell
python -m venv .build-venv
.build-venv/Scripts/python.exe -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File build_exe.ps1 -PythonExecutable .build-venv/Scripts/python.exe
```

The output is in `dist`. See the [English quick start](../README.md#english) for running from source.
