"""Stable stdio host; replaces failed child bridges without replaying requests."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import secrets


class BridgeHost:
    def __init__(self, command, timeout=70, status_callback=None):
        self.command = command
        self.timeout = timeout
        self.status_callback = status_callback or (lambda row: None)
        self.process = None
        self.messages = None
        self.initialize = None
        self.generation = 0
        self.transport_handle = None

    def _state(self, state, **extra):
        try:
            self.status_callback({'state': state, 'host_pid': os.getpid(),
                                  'child_pid': self.process.pid if self.process else None,
                                  'generation': self.generation, 'updated_at': time.time(), **extra})
        except Exception as error:
            # A full disk or failed status observer must not invalidate a tool
            # reply or cause an otherwise healthy bridge to be killed.
            self.status_error = type(error).__name__

    def _start(self):
        self.messages = queue.Queue()
        self.transport_token = secrets.token_hex(24)
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                         start_new_session=os.name != 'nt', bufsize=1,
                         env=dict(os.environ, HYBRID_TRANSPORT_TOKEN=self.transport_token))
        self.generation += 1
        def reader(stream, messages):
            try:
                for line in stream:
                    try:
                        value = json.loads(line)
                        messages.put(value if isinstance(value,dict) else {'invalid_protocol':True})
                    except ValueError: messages.put({'invalid_protocol': True})
            finally:
                messages.put(None)
        threading.Thread(target=reader, args=(self.process.stdout, self.messages), daemon=True).start()
        self._state('ready')
        if self.initialize:
            request = dict(self.initialize, id='hybrid-internal-init')
            reply = self._exchange(request)
            if 'result' not in reply: raise RuntimeError('Не удалось инициализировать восстановленный мост')
            self._send({'jsonrpc':'2.0', 'method':'notifications/initialized'})

    def _send(self, request, deadline=None):
        # A full pipe can block before the response timeout even starts.
        stream = self.process.stdin
        finished = threading.Event()
        errors = []
        def write():
            try:
                stream.write(json.dumps(request, ensure_ascii=False)+'\n');stream.flush()
            except Exception as error: errors.append(error)
            finally:finished.set()
        threading.Thread(target=write,daemon=True).start()
        remaining = self.timeout if deadline is None else max(0,deadline-time.monotonic())
        if not finished.wait(remaining):raise TimeoutError('Мост не принял запрос вовремя')
        if errors:raise errors[0]

    def _exchange(self, request):
        deadline = time.monotonic() + self.timeout
        self._send(request, deadline)
        if 'id' not in request: return None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError('Мост превысил срок ответа')
            try: row = self.messages.get(timeout=remaining)
            except queue.Empty: raise TimeoutError('Мост превысил срок ответа') from None
            if row is None: raise RuntimeError('Дочерний процесс моста завершился')
            if row.get('invalid_protocol'): raise RuntimeError('Повреждён ответ протокола моста')
            if row.get('method') == 'notifications/hybrid/transport':
                self._bind_transport(row.get('params',{}))
                continue
            if row.get('id') == request['id']: return row

    def handle(self, request):
        try:
            if self.process is None or self.process.poll() is not None:
                self.close()
                self._start()
            self._state('busy', method=str(request.get('method')), request_id=request.get('id'))
            result = self._exchange(request)
            if request.get('method') == 'initialize' and result and 'result' in result:
                self.initialize = request
            self._state('ready')
            return result
        except Exception as error:
            self.close()
            self._state('recovering', reason=type(error).__name__, outcome='unknown')
            if 'id' not in request: return None
            return {'jsonrpc':'2.0', 'id':request['id'], 'error':{'code':-32001,
                    'message':'Мост остановлен после сбоя. Следующий запрос получит новый процесс. '
                              'Этот запрос не повторялся; результат действий может быть неизвестен. '
                              'Проверьте computer_action_status или состояние приложения.'}}

    def close(self):
        process, self.process = self.process, None
        if process is None: return
        handle, self.transport_handle = self.transport_handle, None
        try:
            # Apps and API supervisors launched by a tool must outlive this
            # transport. Each bounded helper owns its own deadline; terminate
            # only the bridge process here, not previously launched user apps.
            if handle is not None:
                import ctypes
                kernel = ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.TerminateProcess.argtypes = [ctypes.c_void_p,ctypes.c_uint]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                try:kernel.TerminateProcess(handle,1)
                finally:kernel.CloseHandle(handle)
            if process.poll() is None:process.kill()
            process.wait(timeout=10)
        finally:
            def close_streams():
                for stream in (process.stdin, process.stdout):
                    if stream:
                        try: stream.close()
                        except OSError: pass
            # A wrapper's descendants may retain a pipe; never wait on the
            # buffered reader lock on the transport's main thread.
            threading.Thread(target=close_streams,daemon=True).start()

    def _bind_transport(self, params):
        if not isinstance(params,dict) or params.get('token') != self.transport_token:return
        if os.name != 'nt' or self.transport_handle is not None:return
        import ctypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint,ctypes.c_int,ctypes.c_uint]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p,ctypes.c_uint,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_uint)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        pid = params.get('pid')
        if not isinstance(pid,int) or pid <= 0:return
        handle = kernel.OpenProcess(0x101001,False,pid)
        if not handle:return
        path = ctypes.create_unicode_buffer(32768);length=ctypes.c_uint(len(path))
        if (kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(length)) and
                os.path.normcase(os.path.realpath(path.value)) == os.path.normcase(os.path.realpath(self.command[0]))):
            self.transport_handle = handle
        else:kernel.CloseHandle(handle)

    def heartbeat(self):
        if self.initialize:
            return self.handle({'jsonrpc':'2.0','id':'hybrid-internal-ping','method':'ping'})


def run_host(core, kind):
    from hybrid_api_guard import ensure_started
    stop_gateway = threading.Event()
    def start_gateway():
        try:ensure_started(core)
        except (RuntimeError,OSError):
            # Computer/worker transport can operate independently of the API
            # gateway. Keep diagnostics actionable instead of losing MCP too.
            try:core.write_json_atomic(core.control_dir()/'api-guard-last.json',
                    {'status':'startup_failure','elapsed_seconds':0,'checked_at':core.now_iso()})
            except OSError:pass
    start_gateway()
    def watch_gateway():
        while not stop_gateway.wait(20):start_gateway()
    threading.Thread(target=watch_gateway,daemon=True).start()
    core._configure_mcp_stdio()
    flag = '--bridge-child-' + kind
    if getattr(sys, 'frozen', False):
        command = [sys.executable, flag]
    else:
        from pathlib import Path
        command = [sys.executable, str(Path(core.__file__).resolve()), flag]
    def status(row):
        core.write_json_atomic(core.control_dir()/'bridges'/f'{kind}-{os.getpid()}.json', row)
    host = BridgeHost(command, timeout=70, status_callback=status)
    incoming=queue.Queue()
    def read_input():
        try:
            for line in sys.stdin:incoming.put(line)
        finally:incoming.put(None)
    threading.Thread(target=read_input,daemon=True).start()
    try:
        while True:
            try:raw=incoming.get(timeout=5)
            except queue.Empty:
                host.heartbeat()
                continue
            if raw is None:break
            try:
                request = json.loads(raw)
                if not isinstance(request, dict): raise ValueError('Invalid request')
                result = host.handle(request)
                if result is not None:
                    sys.stdout.write(json.dumps(result, ensure_ascii=False)+'\n')
                    sys.stdout.flush()
            except ValueError:
                sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':None,
                            'error':{'code':-32700,'message':'Parse error'}})+'\n')
                sys.stdout.flush()
    finally:
        stop_gateway.set()
        host.close()
        host._state('stopped')


def announce_transport():
    token = os.environ.pop('HYBRID_TRANSPORT_TOKEN',None)
    if token:
        sys.stdout.write(json.dumps({'jsonrpc':'2.0','method':'notifications/hybrid/transport',
                                    'params':{'token':token,'pid':os.getpid()}})+'\n')
        sys.stdout.flush()


def bridge_states(core):
    rows = []
    folder = core.control_dir()/'bridges'
    # Only the visible recent rows need a process liveness query. Old bridge
    # receipts otherwise turn a cheap status refresh into hundreds of queries.
    def modified(path):
        try:return path.stat().st_mtime
        except OSError:return 0
    for path in sorted(folder.glob('*.json'),key=modified,reverse=True)[:16]:
        row = core.read_json(path, {})
        if not isinstance(row, dict): continue
        try:
            pid=int(row.get('host_pid') or 0)
            updated=float(row.get('updated_at') or 0)
        except (ValueError,TypeError):continue
        if pid<=0:continue
        row['updated_at']=updated
        row['kind'] = path.stem.split('-')[0]
        row['alive'] = core.pid_alive(pid)
        if not row['alive']: row['state'] = 'stopped'
        rows.append(row)
    return sorted(rows, key=lambda r:r.get('updated_at',0), reverse=True)[:16]
