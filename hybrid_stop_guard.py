"""Bounded native Stop recovery, renewed only by distinct tool results."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

FLAG = '--hybrid-stop-guard'
STATUS = 'Hybrid Control: проверка завершения API'


def damaged_answer(text):
    if not isinstance(text, str):
        return False
    text = text[-32000:]
    # Quoted examples and source snippets are not provider protocol leakage.
    plain = re.sub(r'```.*?```|`[^`]*`', '', text, flags=re.S)
    plain = re.sub(r'(?m)^\s*>.*$', '', plain).strip()
    if re.search(r'(?:</(?:think|arg_value|tool_call|function)>\s*)+$', plain):
        return True
    if re.search(r'(?m)^\s*</(?:think|arg_value|tool_call|function)>', plain):
        return True
    if len(re.findall(r'</(?:think|arg_value|tool_call|function)>', plain)) >= 2:
        return True
    words = re.findall(r'\w+', plain.casefold())
    if len(words) >= 15:
        prefix = ' '.join(words[:6])
        normalized = ' '.join(words)
        if normalized.count(prefix) >= 3:
            return True
    return False


def unfinished_progress(text):
    if not isinstance(text, str) or len(text) > 4000 or '?' in text:
        return False
    if re.search(r'(?im)```|`|^\s*>|нужн[оаы]?\s+(?:ваш|подтвержден)|уточнит|не могу|нет доступ|жду|blocked|please confirm', text):
        return False
    # Only an explicit next-action announcement at the end, not a broad judgment
    # about whether an arbitrary answer has completed the user's entire task.
    plain = re.sub(r'\*\*|__', '', text).strip()
    return bool(re.search(r'(?:^|[.!\n]\s*|—\s*)(?:сейчас\s+)?(?:проверяю|проверю|продолжаю|перезапускаю|запускаю|исправляю|создаю|тестирую|обновляю|начинаю|перехожу к|i(?:’|\x27)ll (?:check|run|start|verify|fix)|(?:checking|starting|launching|running|verifying))\b[^.!?\n]{0,240}[.:]?\s*$', plain, re.I))


def session_context(path):
    """Bounded read; unknown transcript schemas disable automatic continuation."""
    with Path(path).open('rb') as stream:
        head = stream.read(65536)
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - 524288))
        tail = stream.read(524288)
    provider = None
    has_tool = False
    prompt = ''
    calls = {}
    results = set()
    pending_plan = False
    metadata=[]
    for raw in head.splitlines()[:10]:
        try:
            if json.loads(raw).get('type')=='session_meta':metadata.append(raw)
        except (ValueError,AttributeError):pass
    for raw in metadata + tail.splitlines():
        try:
            row = json.loads(raw)
            payload = row.get('payload', {})
            if row.get('type') == 'session_meta':
                provider = payload.get('model_provider')
            if row.get('type') == 'turn_context' and payload.get('model_provider'):
                provider = payload['model_provider']
            if row.get('type') == 'event_msg' and payload.get('type') == 'user_message':
                prompt = payload.get('message', '')
                has_tool = False
                calls.clear(); results.clear(); pending_plan = False
            if row.get('type') == 'event_msg' and payload.get('type') == 'item_completed' and payload.get('item', {}).get('type') == 'UserMessage':
                prompt = ''.join(part.get('text', '') for part in payload['item'].get('content', []) if isinstance(part, dict))
                has_tool = False
                calls.clear(); results.clear(); pending_plan = False
            if row.get('type') == 'response_item' and payload.get('type') in {'function_call', 'custom_tool_call'}:
                has_tool = True
                name = payload.get('name', '')
                arguments = payload.get('arguments', payload.get('input', ''))
                try: canonical_args = json.loads(arguments) if isinstance(arguments, str) else arguments
                except ValueError: canonical_args = arguments
                calls[payload.get('call_id')] = (payload.get('namespace', '') + ':' + name, canonical_args)
                if name.split('.')[-1] == 'update_plan':
                    try:
                        plan = json.loads(arguments).get('plan', [])
                        pending_plan = bool(plan) and any(p.get('status') != 'completed' for p in plan)
                    except (ValueError, TypeError, AttributeError):
                        pass
            if row.get('type') == 'response_item' and payload.get('type') in {'function_call_output', 'custom_tool_call_output'}:
                call = calls.get(payload.get('call_id'))
                if call:
                    output = payload.get('output', '')
                    # Native shell envelopes include changing timing/session IDs.
                    # Only the actual command output counts as progress.
                    if isinstance(output, list):
                        output = '\n'.join(part.get('text', '') if isinstance(part, dict) and part.get('type') == 'input_text'
                                           else json.dumps(part, sort_keys=True) for part in output)
                    if isinstance(output, str):
                        try:
                            envelope = json.loads(output)
                            if isinstance(envelope, dict) and 'output' in envelope:
                                output = envelope['output']
                        except ValueError:
                            marker = re.search(r'(?m)^Output:\s*(?:\n|$)', output)
                            if marker: output = output[marker.end():]
                    signature = json.dumps([*call, output], sort_keys=True, ensure_ascii=False)
                    results.add(hashlib.sha256(signature.encode()).hexdigest())
        except (ValueError, AttributeError):
            continue
    progress = hashlib.sha256(''.join(sorted(results)).encode()).hexdigest()
    return provider, has_tool, prompt, progress, pending_plan


def decide(payload, home):
    if not isinstance(payload, dict) or payload.get('hook_event_name') != 'Stop':
        return {}
    if not isinstance(payload.get('stop_hook_active'), bool) or payload.get('permission_mode') == 'plan':
        return {}
    home = Path(home)
    state_path = home / 'hybrid-control' / 'restore-point.json'
    if state_path.exists() and json.loads(state_path.read_text(encoding='utf-8')).get('active'):
        return {}
    path = Path(payload.get('transcript_path') or '')
    # Never read arbitrary files supplied as a transcript.
    if not path.resolve().is_relative_to((home / 'sessions').resolve()):
        return {}
    provider, has_tool, prompt, progress, pending_plan = session_context(path)
    if provider != 'funpay':
        return {}
    if re.fullmatch(r'\s*(?:стоп|остановись|хватит|stop|cancel|не продолжай)[.!\s]*', prompt, re.I):
        return {}
    answer = payload.get('last_assistant_message')
    # A real blocker or a user question must not be overridden by plan state.
    blocked = isinstance(answer, str) and bool(re.search(
        r'(?i)\?|нужн[оаы]?\s+(?:ваш|подтвержден)|уточнит|не могу|нет доступ|жду|blocked|please confirm', answer))
    if blocked:return {}
    empty_after_tool = has_tool and (answer is None or isinstance(answer, str) and not answer.strip())
    promised_action = unfinished_progress(answer) and (has_tool or bool(prompt) and not re.search(r'(?i)скажи|повтори|напиши фразу|quote|repeat',prompt))
    open_plan = pending_plan and not blocked
    if not damaged_answer(answer) and not empty_after_tool and not promised_action and not open_plan:
        return {}
    session, turn = payload.get('session_id'), payload.get('turn_id')
    if not session or not turn:
        return {}
    # The same root turn can continue only while tools produce new results.
    # Distinct call IDs/timing alone do not justify another request.
    folder = home / 'hybrid-control' / 'stop-guard'
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((str(session) + ':' + str(turn)).encode()).hexdigest()
    from hybrid_storage import file_transaction
    marker = folder / (key + '.json')
    with file_transaction(folder / 'state.lock', timeout=2):
        state = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
        if payload['stop_hook_active'] and not state:
            return {}
        if state and (not payload['stop_hook_active'] or state.get('progress') == progress or state.get('attempts', 0) >= 6):
            return {}
        state = {'event': 'continuation_requested', 'reason': 'open_plan' if open_plan else 'malformed_or_progress_only',
                 'progress': progress, 'attempts': state.get('attempts', 0) + 1}
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(json.dumps(state), encoding='utf-8')
        temporary.replace(marker)
    return {'decision': 'block', 'reason': (
        'Hybrid Control обнаружил повреждённый или преждевременно завершённый ответ API. '
        'Продолжи ранее порученную пользователем работу с текущего состояния, если она ещё не закончена. '
        'Сначала проверь результаты последних инструментов. Не повторяй уже выполненные изменяющие '
        'действия; при неизвестном результате сначала проверь состояние и журнал action_id. '
        'Не расширяй исходное поручение, не обходи разрешения и не возобновляй отменённую пользователем работу. '
        'Если работа выполнена — дай итог; если нужны данные или разрешение пользователя — задай вопрос. '
        'Если есть незакрытый план, выполни оставшиеся пункты или приведи его в соответствие с проверенными результатами. '
        'Не заканчивай одним объявлением следующего действия: выполни его в пределах поручения. '
        'При отсутствии прогресса прекрати повторять тот же подход, попробуй обоснованный другой способ или сообщи конкретную причину сбоя. '
        'Не выводи служебные XML-теги и повторяющиеся обрывки текста.'
    )}


def main():
    result = {}
    status = 'ignored'
    home = os.environ.get('CODEX_HOME') or str(Path.home() / '.codex')
    try:
        raw = sys.stdin.buffer.read(262145)
        if len(raw) > 262144:
            raise ValueError('Hook input too large')
        result = decide(json.loads(raw), home)
        status = 'continuation_requested' if result.get('decision') == 'block' else 'ignored'
    except Exception:
        # A broken guard must never prevent normal completion or leak transcript text.
        result = {}
        status = 'failed'
    try:
        folder = Path(home) / 'hybrid-control' / 'stop-guard'
        folder.mkdir(parents=True, exist_ok=True)
        # No transcript, commands, prompts or keys in the execution receipt.
        receipt = {'checked_at': datetime.now(timezone.utc).isoformat(), 'status': status}
        temporary = folder / ('last-check.' + str(os.getpid()) + '.tmp')
        temporary.write_text(json.dumps(receipt), encoding='utf-8')
        temporary.replace(folder / 'last-check.json')
    except OSError:
        pass
    sys.stdout.write(json.dumps(result, ensure_ascii=True) + '\n')


def clean_hooks(value):
    result = copy.deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get('hooks', {}), dict):
        raise ValueError('Некорректный hooks.json; файл не изменён')
    groups = result.get('hooks', {}).get('Stop', [])
    if not isinstance(groups, list):
        raise ValueError('Некорректный список Stop hooks')
    kept = []
    for group in groups:
        handlers = group.get('hooks', [])
        remaining = [h for h in handlers if not (h.get('statusMessage') == STATUS and FLAG in h.get('command', ''))]
        if remaining or not handlers:
            kept.append({**group, 'hooks': remaining})
    if groups:
        if kept: result['hooks']['Stop'] = kept
        else: result['hooks'].pop('Stop', None)
    return result


def install(core, config_path):
    from hybrid_storage import file_transaction
    if core.is_stock_mode():
        return 'Отключено в обычном Codex'
    path = Path(config_path).parent / 'hooks.json'
    with file_transaction(core.control_dir() / 'hooks.lock'):
        original = path.read_bytes() if path.exists() else None
        value = clean_hooks(json.loads(original.decode('utf-8-sig')) if original else {})
        if getattr(sys, 'frozen', False):
            executable, _ = core._self_command_for_worker_mcp()
            argv = [executable, FLAG]
        else:
            argv = [core._stdio_python_executable(), str(Path(__file__).resolve()), FLAG]
        # Windows command hooks execute under PowerShell; single quotes protect
        # literal dollar signs/backticks in paths. POSIX hooks use shlex quoting.
        if os.name == 'nt':
            command = '& ' + ' '.join("'" + arg.replace("'", "''") + "'" for arg in argv)
        else:
            import shlex
            command = shlex.join(argv)
        handler = {'type': 'command', 'command': command, 'timeout': 10, 'statusMessage': STATUS}
        value.setdefault('hooks', {}).setdefault('Stop', []).append({'hooks': [handler]})
        if original and json.loads(original.decode('utf-8-sig')) == value:
            return 'Установлено; доверие проверяется в Codex через /hooks'
        if original:
            backup = core.control_dir() / 'hook-backups' / (core.datetime.now().strftime('%Y%m%d%H%M%S%f') + '.json')
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(original)
        core.write_json_atomic(path, value)
    return 'Установлено. В Codex откройте /hooks и подтвердите доверие к проверке Hybrid Control'


if __name__ == '__main__':
    main()
