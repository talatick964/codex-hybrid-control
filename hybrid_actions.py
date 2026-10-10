"""Persistent action receipts. Unknown outcomes are never automatically replayed."""
import hashlib
import json
import re
from pathlib import Path
from hybrid_storage import file_transaction


class ActionJournal:
    def __init__(self, core):
        self.core = core
        self.directory = core.control_dir() / 'actions'

    def path(self, action_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(action_id)):
            raise ValueError('action_id: используйте 1–80 букв, цифр, _ или -')
        return self.directory / (str(action_id) + '.json')

    @staticmethod
    def signature(name, arguments):
        return hashlib.sha256(json.dumps([name, arguments], sort_keys=True,
                    ensure_ascii=False, default=str).encode('utf-8')).hexdigest()

    def status(self, action_id):
        path = self.path(action_id)
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'action_id': action_id, 'state': 'not_found'}
        except (OSError, ValueError) as error:
            raise RuntimeError('Журнал действий повреждён или недоступен; автоматическое повторение запрещено') from error
        if (not isinstance(data, dict) or data.get('action_id') != action_id or
                data.get('state') not in {'running','unknown','completed'}):
            raise RuntimeError('Журнал действий повреждён; автоматическое повторение запрещено')
        return data

    def recent(self,limit=10):
        rows=[]
        for path in sorted(self.directory.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:max(1,min(int(limit),30))]:
            row=self.core.read_json(path,{})
            if isinstance(row,dict):rows.append(row)
        return rows

    def execute(self, action_id, name, arguments, execute):
        path = self.path(action_id)
        with file_transaction(self.directory / 'execution.lock', timeout=1):
            signature = self.signature(name, arguments)
            existing = self.status(action_id)
            if existing['state'] != 'not_found':
                if existing.get('signature') != signature:
                    raise RuntimeError('Этот action_id уже использован для другого действия')
                if existing['state'] == 'completed':
                    return {'action_id': action_id, 'state': 'completed', 'replayed': False,
                            'receipt': existing.get('receipt'),
                            'hint': 'Действие уже выполнено. Проверьте текущее состояние отдельным чтением или снимком.'}
                raise RuntimeError('Результат предыдущего действия неизвестен. Проверьте окно; автоматический повтор запрещён.')
            row = {'action_id': action_id, 'name': name, 'signature': signature,
                   'state': 'running', 'started_at': self.core.now_iso()}
            # No typed text, arguments, browser values or credentials in receipts.
            self.core.write_json_atomic(path, row)
            try:
                result = execute()
                if isinstance(result, str):
                    try: inspected = json.loads(result)
                    except ValueError: inspected = None
                    if isinstance(inspected,dict) and (inspected.get('error') or inspected.get('ok') is False):
                        raise RuntimeError('Инструмент не подтвердил действие')
                if isinstance(result, dict) and result.get('ok') is False:
                    raise RuntimeError(result.get('error') or 'Действие не подтверждено')
                row.update(state='completed', finished_at=self.core.now_iso(),
                           receipt={'executed': True})
                self.core.write_json_atomic(path, row)
                return result
            except BaseException:
                row.update(state='unknown', finished_at=self.core.now_iso())
                self.core.write_json_atomic(path, row)
                raise

    def batch(self, action_id, actions, execute):
        # Independent receipts let a known completed prefix survive disconnection.
        overall = self.path(action_id)
        signature = self.signature('computer_act', actions)
        with file_transaction(self.directory / 'execution.lock', timeout=1):
            row = self.status(action_id)
            if row['state'] != 'not_found' and row.get('signature') != signature:
                raise RuntimeError('Пакет с этим action_id содержит другие действия')
            if row['state'] == 'not_found':
                row = {'action_id': action_id, 'name': 'computer_act', 'signature': signature,
                       'state': 'running', 'started_at': self.core.now_iso(), 'completed_steps': 0}
                self.core.write_json_atomic(overall, row)
            results = []
            for index, action in enumerate(actions):
                # Hash avoids overflowing the bounded caller-provided identifier.
                step_id = hashlib.sha256((action_id+':'+str(index)).encode()).hexdigest()
                result = self.execute(step_id, 'computer_step', action, lambda a=action: execute(a))
                results.append({'step': index+1, 'result': result})
                row['completed_steps'] = index+1
                self.core.write_json_atomic(overall, row)
            row.update(state='completed', finished_at=self.core.now_iso())
            self.core.write_json_atomic(overall, row)
            return results


def serialized(core, execute):
    """Also serialize legacy calls without receipts with all direct tools."""
    with file_transaction(core.control_dir() / 'actions' / 'execution.lock', timeout=1):
        return execute()
