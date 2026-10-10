<div align="center">
  <img src="docs/assets/logo.png" alt="Codex Hybrid Control" width="112">
  <h1>Codex Hybrid Control</h1>
  <p><b>Твой API. Настоящий Codex. Одна удобная панель.</b></p>
  <p>Подключения · агенты · управление Windows и браузером · восстановление</p>
  <a href="https://github.com/talatick964/codex-hybrid-control/releases/latest/download/Codex-Hybrid-Control-7.3.2-Windows.zip"><img src="https://img.shields.io/badge/Скачать_для_Windows-7.3.2-aed5fc?style=for-the-badge&labelColor=18212e" alt="Скачать для Windows"></a>
  <a href="https://t.me/aislopprogs"><img src="https://img.shields.io/badge/Telegram-АИслоп-93b8ea?style=for-the-badge&logo=telegram&logoColor=white&labelColor=18212e" alt="Telegram"></a>
  <p><a href="docs/INSTALL.md">Как установить</a> · <a href="https://github.com/talatick964/codex-hybrid-control/issues/new/choose">Сообщить об ошибке</a> · <a href="https://github.com/talatick964/codex-hybrid-control/releases">Все версии</a></p>
</div>

---

Панель настраивает **установленный Codex** для работы через твой API. Здесь можно менять провайдера и модель, подключать агентов и локальные инструменты, проверять ошибки и возвращаться к обычному Codex.

### Запуск за несколько минут

Нужны **Windows, установленный Codex с CLI и свой API-ключ**. Провайдер должен поддерживать Responses API. Python для готовой программы не нужен.

1. [Скачай ZIP](https://github.com/talatick964/codex-hybrid-control/releases/latest/download/Codex-Hybrid-Control-7.3.2-Windows.zip), распакуй и запусти **Codex-Hybrid-Control.exe**.
2. В **«Подключение API»** добавь ключ и выбери модель.
3. Посмотри изменения, нажми **«Применить»**, затем **«Проверить и исправить всё»**.
4. В Codex CLI открой `/hooks`: подтверди обработчик Hybrid Control, если он ещё не доверенный. Перезапусти Codex и создай новый сеанс.

### Что внутри

| Возможность | Для чего |
| --- | --- |
| Профили подключения | Быстро менять API и модель |
| Предпросмотр и откат | Видеть изменения и возвращать настройки |
| Компьютер и браузер | Работать с элементами окон, страницами и настоящими кликами |
| Контроль API | Ограничивать ожидание, замечать повторы и преждевременную остановку |
| Общий ремонт | Проверять и восстанавливать компоненты одной кнопкой |
| Обычный Codex | Обратимо отключать Hybrid Control |

<details>
<summary><b>Посмотреть интерфейс</b></summary>
<br>
<img src="docs/assets/overview.png" alt="Главное окно Codex Hybrid Control" width="100%">
<br><br>
<img src="docs/assets/computer.png" alt="Настройки управления компьютером" width="100%">
</details>

Проверено: **199 тестов**, готовые EXE, управление Windows и отдельной сессией Edge. [Отчёт](docs/VERIFY.md) · [Что нового](CHANGELOG.md) · [Исходники и сборка](docs/INSTALL.md#из-исходников).

Контроль API помогает восстановиться после сбоев, но не гарантирует исправность любого провайдера. [Возможности и ограничения](docs/FEATURES.md).

Новости, идеи и обратная связь — **[АИслоп в Telegram](https://t.me/aislopprogs)**. В сообщениях об ошибках не публикуй API-ключи и личные логи.

<sub>Независимый проект, не связан с OpenAI. [Сторонние компоненты](THIRD_PARTY_NOTICES.md).</sub>
