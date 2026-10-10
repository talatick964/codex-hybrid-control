# Установка

## Готовая программа

Нужны **Windows, установленный Codex с CLI и собственный API-ключ**. Поддерживаемый протокол провайдера — Responses API.

1. [Скачай ZIP для Windows](https://github.com/talatick964/codex-hybrid-control/releases/latest/download/Codex-Hybrid-Control-7.3.2-Windows.zip).
2. Распакуй архив в обычную папку. Запусти **Codex-Hybrid-Control.exe** — Python не нужен.
3. Открой **«Подключение API»**, укажи ключ и выбери модель. Для другого провайдера создай профиль с его адресом.
4. Посмотри изменения, нажми **«Применить»**, затем **«Проверить и исправить всё»**.
5. В Codex CLI открой `/hooks` и подтверди обработчик Hybrid Control, если он ещё не доверенный. Перезапусти Codex и создай новый сеанс.

## Обновление

Закрой старую панель, распакуй новую и запусти её. Нажми **«Проверить и исправить всё»**, затем перезапусти Codex. Ключи и настройки хранятся локально, отдельно от программы.

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

Готовые файлы появятся в `dist`. Проверки: `python -m pytest tests -q` после установки `requirements-dev.txt`. Подробности защиты — в [FIX-7.3.2.md](../FIX-7.3.2.md).
