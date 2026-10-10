# Codex Hybrid Control — API workers + Local Computer Use

## Внешние API-агенты

В API-АВТОНОМНОМ режиме native Codex subagents (`spawn_agent` / `thread_spawn`) отключены намеренно. Для делегирования используй MCP `hybridWorkers`:

- `api_worker_spawn` — Opus/Astra/Luna;
- `api_worker_list` — состояние;
- `api_worker_result` — результат;
- `api_worker_stop` — остановка.

Назначение:

- `opus` — реализация/сложный debug;
- `astra` — архитектура и независимое review;
- `luna` — исследование/read-only tracing.

Для большой задачи делегируй независимые части автоматически. Не запускай двух редактирующих workers на одни и те же файлы. После worker обязательно проверь фактические файлы/diff/tests.

## Локальный Computer Use

При API-root используй `hybridComputer`, а не hosted/official Computer Use.

Рабочий цикл:

1. `computer_status`;
2. `computer_screenshot`;
3. при работе с конкретным app — `computer_focus_window`;
4. действие либо короткий `computer_act`;
5. новый screenshot;
6. подтверждай успех только после визуальной проверки результата.

Координаты действий по умолчанию относятся к последнему screenshot; `(0,0)` — его верхний левый пиксель. Мост сам переводит их в Windows virtual-screen coordinates, включая отрицательный origin дополнительных мониторов.

Не вводи секреты/пароли/токены через GUI без прямого указания пользователя.

Если `hybridWorkers` или `hybridComputer` не видны в текущем сеансе, не заменяй их native `spawn_agent` или hosted Computer Use в API-АВТОНОМНОМ режиме. Восстанови Hybrid Control, перезапусти Codex и создай новый сеанс.

Если API-model/provider не принимает image content от MCP, сообщи об ограничении честно; не имитируй visual grounding.
