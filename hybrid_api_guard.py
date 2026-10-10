"""Loopback Responses gateway with hard deadlines and no request replay."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import base64
import re

VERSION = 3
MAX_BYTES = 16 * 1024 * 1024
REASONS = {
    'deadline':'превышен предел времени запроса', 'idle_timeout':'провайдер перестал присылать данные',
    'repeated_output':'ответ зациклился', 'incomplete_stream':'поток оборвался без завершения',
    'incomplete_response':'провайдер не завершил ответ', 'provider_error':'провайдер сообщил об ошибке',
    'connection_failure':'ошибка соединения', 'upstream_disconnected':'соединение оборвалось',
    'retry_limit':'две попытки не удались; повтор заблокирован на 60 секунд',
    'request_too_large':'запрос превышает 16 МиБ', 'response_too_large':'ответ превышает 16 МиБ',
    'client_cancelled':'Codex отменил запрос', 'invalid_stream':'неверный формат потока',
    'unsupported_proxy':'неподдерживаемый тип системного прокси',
    'invalid_response':'некорректный завершённый ответ или вызов инструмента',
    'tool_loop':'один инструмент повторяется с теми же параметрами и результатом; дальнейший повтор остановлен',
}


class GuardError(Exception):
    pass


def load_settings(core):
    path = core.control_dir()/'api-guard.json'
    try:
        settings = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:return {}
    except (OSError, ValueError) as error:
        raise RuntimeError('Настройки контроля API повреждены; выполните «Проверить и исправить всё»') from error
    if not isinstance(settings,dict) or not isinstance(settings.get('enabled'),bool):
        raise RuntimeError('Настройки контроля API повреждены; выполните «Проверить и исправить всё»')
    if settings['enabled'] and (type(settings.get('port')) is not int or not 1 <= settings['port'] <= 65535 or
            not isinstance(settings.get('access'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',settings['access'])):
        raise RuntimeError('Настройки контроля API повреждены; выполните «Проверить и исправить всё»')
    return settings


def repeated_suffix(text):
    maximum = min(1000,len(text)//4)
    if maximum < 24:return False
    # An actual fourfold suffix must repeat its last 24 characters. Find those
    # candidates in C instead of allocating 977 possible repeats per token.
    anchor = text[-24:];end=len(text)-24
    position = text.rfind(anchor,max(0,end-maximum),end)
    while position >= 0:
        period = end-position
        if text[-period:]*4 == text[-period*4:]:return True
        position = text.rfind(anchor,max(0,end-maximum),position+23)
    return False


def validate_response(value, compact=False):
    if not isinstance(value, dict): raise GuardError('invalid_response')
    if compact and value.get('object') == 'response.compaction': return
    if value.get('status') != 'completed': raise GuardError('incomplete_response')
    output = value.get('output')
    if not isinstance(output, list): raise GuardError('invalid_response')
    call_ids = set()
    for item in output:
        if not isinstance(item, dict): raise GuardError('invalid_response')
        if item.get('type') == 'function_call':
            call_id = item.get('call_id')
            if not isinstance(call_id, str) or not call_id or call_id in call_ids or not item.get('name'):
                raise GuardError('invalid_response')
            call_ids.add(call_id)
            try: arguments = json.loads(item.get('arguments', ''))
            except (ValueError, TypeError): raise GuardError('invalid_response')
            if not isinstance(arguments, dict): raise GuardError('invalid_response')


def repeated_tool_call(request, candidate):
    """Bound repeated completed calls using history, without executing any tool."""
    history = request.get('input', []) if isinstance(request, dict) else []
    if not isinstance(history, list): return False
    calls = {}
    completed = []
    def signature(item):
        arguments = item.get('arguments', item.get('input', ''))
        try: arguments = json.loads(arguments)
        except (ValueError, TypeError): pass
        return json.dumps([item.get('type'),item.get('namespace'),item.get('name'),arguments], sort_keys=True)
    for item in history:
        if not isinstance(item, dict): continue
        if item.get('role') == 'user':
            calls.clear(); completed.clear()
        elif item.get('type') in {'function_call','custom_tool_call'}:
            calls[item.get('call_id')] = signature(item)
        elif item.get('type') in {'function_call_output','custom_tool_call_output'} and item.get('call_id') in calls:
            output = item.get('output')
            if isinstance(output, list):
                output = '\n'.join(part.get('text','') if isinstance(part,dict) and part.get('type') in {'input_text','text'}
                                   else json.dumps(part,sort_keys=True) for part in output)
            if isinstance(output, str):
                import re
                marker = re.search(r'(?m)^Output:\s*(?:\n|$)', output)
                if marker: output = output[marker.end():]
            completed.append((calls[item['call_id']], json.dumps(output,sort_keys=True)))
    return len(completed) >= 4 and len(set(completed[-4:])) == 1 and completed[-1][0] == signature(candidate)


def read_stream(response, deadline, idle=60, stop=None, cancelled=None, request=None):
    """Independent clock: keepalives and slow partial lines cannot extend deadline."""
    chunks = queue.Queue(maxsize=32)
    stop = stop or threading.Event()
    def reader():
        try:
            while not stop.is_set():
                data = response.read1(8192)
                while not stop.is_set():
                    try:
                        chunks.put(data, timeout=.1)
                        break
                    except queue.Full:
                        pass
                if not data:break
        except Exception:
            try:chunks.put_nowait(None)
            except queue.Full:pass
    threading.Thread(target=reader, daemon=True).start()
    size = 0
    pending = bytearray()
    search_from = 0
    separator = re.compile(rb'\r\n\r\n|\n\n|\r\r')
    text = ''
    last_data = time.monotonic()
    blocks = []
    text_parts = {}
    emitted_tools = []
    try:
        while True:
            if cancelled and cancelled():raise GuardError('client_cancelled')
            now = time.monotonic()
            remaining = min(deadline-now, idle-(now-last_data))
            if remaining <= 0:raise GuardError('deadline' if now >= deadline else 'idle_timeout')
            try:data = chunks.get(timeout=min(.25, remaining))
            except queue.Empty:continue
            if data is None:raise GuardError('upstream_disconnected')
            if not data:
                raise GuardError('incomplete_stream')
            size += len(data)
            if size > MAX_BYTES:raise GuardError('response_too_large')
            pending.extend(data)
            consumed = 0
            while True:
                match = separator.search(pending,search_from)
                if not match:break
                block = bytes(pending[consumed:match.start()])
                consumed = match.end();search_from = consumed
                blocks.append(block)
                payload = b'\n'.join(line[5:].lstrip() for line in block.splitlines() if line.startswith(b'data:'))
                if not payload or payload == b'[DONE]':continue
                try:event = json.loads(payload)
                except (ValueError, UnicodeError):raise GuardError('invalid_stream')
                if not isinstance(event, dict):raise GuardError('invalid_stream')
                kind = event.get('type', '')
                # Comments/keepalives cannot keep an idle model alive forever.
                if isinstance(kind,str) and kind.startswith('response.'):last_data=time.monotonic()
                if kind == 'response.output_item.done' and isinstance(event.get('item'), dict) and event['item'].get('type') in {'function_call','custom_tool_call'}:
                    emitted_tools.append(event['item'])
                if kind in {'response.output_text.delta', 'response.reasoning_summary_text.delta', 'response.reasoning_text.delta'}:
                    part_key = (kind, event.get('item_id'), event.get('content_index'))
                    text = (text_parts.get(part_key, '') + str(event.get('delta','')))[-12000:]
                    text_parts[part_key] = text
                    # Four equal substantial suffixes, independent of token chunk boundaries.
                    normalized = ' '.join(text.casefold().split())
                    if repeated_suffix(normalized):
                        raise GuardError('repeated_output')
                if kind in {'response.failed', 'error'}:raise GuardError('provider_error')
                if kind == 'response.incomplete':raise GuardError('incomplete_response')
                if kind == 'response.completed':
                    validate_response(event.get('response'))
                    terminal_tools = [item for item in event['response']['output'] if item.get('type') in {'function_call','custom_tool_call'}]
                    if any(repeated_tool_call(request, item) for item in terminal_tools):raise GuardError('tool_loop')
                    def tool_value(item):
                        return tuple(item.get(key) for key in ('type','call_id','namespace','name','arguments','input'))
                    if emitted_tools and [tool_value(item) for item in emitted_tools] != [tool_value(item) for item in terminal_tools]:
                        raise GuardError('invalid_response')
                    # Never forward appended executable events after the terminal event.
                    return b'\n\n'.join(blocks) + b'\n\n'
            if consumed:del pending[:consumed]
            search_from = max(0,len(pending)-3)
    finally:
        stop.set()


def endpoint(core, upstream):
    settings = load_settings(core)
    if not settings.get('enabled'):return upstream
    return f"http://127.0.0.1:{int(settings['port'])}/{settings['access']}/v1"


def server(core, settings, upstream=None, timeout=180, idle=60):
    semaphore = threading.BoundedSemaphore(8)
    failures = {}
    failures_lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)
        def log_message(self, *args):pass
        def reply(self, status, value, content_type='application/json'):
            if hasattr(self,'reply_lock'):
                with self.reply_lock:
                    if self.replied:return
                    self.replied=True
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status);self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)));self.send_header('Connection','close');self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if self.path == '/'+settings['access']+'/health':
                self.reply(200, {'version':VERSION,'pid':os.getpid()})
            else:self.reply(404, {})
        def do_POST(self):
            self.reply_lock=threading.Lock()
            self.replied=False
            self.expired=threading.Event()
            self.expiration_reason=None
            finished=threading.Event()
            def exchange():
                try:self.forward()
                finally:finished.set()
            threading.Thread(target=exchange,daemon=True).start()
            # Independent of DNS, TLS, HTTP headers and the provider's heartbeats.
            until=time.monotonic()+timeout+.25
            while not finished.wait(.1) and time.monotonic()<until:
                try:
                    ready,_,_=select.select([self.connection],[],[],0)
                    if ready and not self.connection.recv(1,socket.MSG_PEEK):
                        self.expired.set()
                        self.expiration_reason='client_cancelled'
                        abort=getattr(self,'abort_connection',None)
                        if abort:abort()
                        return
                except OSError:
                    self.expired.set()
                    self.expiration_reason='client_cancelled'
                    return
            if not finished.is_set():
                self.expired.set()
                self.expiration_reason='deadline'
                abort=getattr(self,'abort_connection',None)
                if abort:abort()
                try:self.reply(502,{'error':{'message':'Hybrid Control: превышено время API-запроса'}})
                except OSError:pass
                try:self.connection.shutdown(socket.SHUT_RD)
                except OSError:pass
                try:core.write_json_atomic(core.control_dir()/'api-guard-last.json',
                    {'status':'deadline','elapsed_seconds':timeout,'checked_at':core.now_iso()})
                except OSError:pass
        def forward(self):
            if core.is_stock_mode():
                self.reply(503,{'error':{'message':'Hybrid Control отключён'}});return
            prefix = '/'+settings['access']+'/v1'
            if self.path not in {prefix+'/responses',prefix+'/responses/compact'} or self.headers.get('Origin'):
                self.reply(403, {});return
            if not semaphore.acquire(blocking=False):self.reply(429, {'error':{'message':'Hybrid Control: слишком много запросов'}});return
            connection = None
            fingerprint = None
            started = time.monotonic()
            failure = None
            try:
                self.connection.settimeout(10)
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= MAX_BYTES:raise GuardError('request_too_large')
                body_parts=[];received=0
                while received<size:
                    if self.expired.is_set():raise GuardError(self.expiration_reason or 'deadline')
                    remaining=timeout-(time.monotonic()-started)
                    if remaining<=0:raise GuardError('deadline')
                    self.connection.settimeout(min(10,remaining))
                    chunk=self.rfile.read1(min(65536,size-received))
                    if not chunk:raise GuardError('incomplete_request')
                    body_parts.append(chunk);received+=len(chunk)
                body=b''.join(body_parts)
                if len(body)!=size:raise GuardError('incomplete_request')
                request_value = json.loads(body)
                if not isinstance(request_value, dict):raise GuardError('invalid_response')
                if self.expired.is_set():raise GuardError('deadline')
                fingerprint=hashlib.sha256(body+self.headers.get('Authorization','').encode()).hexdigest()
                with failures_lock:
                    for key in list(failures):
                        if time.monotonic()-failures[key][1]>60:failures.pop(key)
                    if failures.get(fingerprint,(0,0))[0]>=2:raise GuardError('retry_limit')
                from hybrid_connections import active_connection
                url = urllib.parse.urlsplit(upstream or active_connection(core)['base_url'])
                if url.scheme not in {'http','https'} or not url.hostname:raise GuardError('invalid_upstream')
                if url.hostname=='127.0.0.1' and url.port==settings['port']:raise GuardError('recursive_upstream')
                cls = http.client.HTTPSConnection if url.scheme=='https' else http.client.HTTPConnection
                connection = cls(url.hostname, url.port, timeout=min(idle,timeout))
                request_path=url.path.rstrip('/')+self.path[len(prefix):]
                proxy_headers={}
                if url.hostname not in {'127.0.0.1','localhost','::1'} and not urllib.request.proxy_bypass(url.hostname):
                    proxy_value=urllib.request.getproxies().get(url.scheme)
                    if proxy_value:
                        proxy=urllib.parse.urlsplit(proxy_value if '://' in proxy_value else 'http://'+proxy_value)
                        if proxy.scheme!='http' or not proxy.hostname:raise GuardError('unsupported_proxy')
                        if proxy.username:
                            credential=urllib.parse.unquote(proxy.username)+':'+urllib.parse.unquote(proxy.password or '')
                            proxy_headers['Proxy-Authorization']='Basic '+base64.b64encode(credential.encode()).decode()
                        connection=cls(proxy.hostname,proxy.port or 80,timeout=min(idle,timeout))
                        if url.scheme=='https':connection.set_tunnel(url.hostname,url.port or 443,headers=proxy_headers)
                        else:request_path=urllib.parse.urlunsplit((url.scheme,url.netloc,request_path,'',''))
                # Only request-scoped authorization is forwarded. Never read or log a saved key.
                headers = {'Content-Type':'application/json','Accept':'text/event-stream','Accept-Encoding':'identity'}
                if url.scheme=='http':headers.update(proxy_headers)
                for name in ('Authorization','OpenAI-Beta'):
                    if self.headers.get(name):headers[name] = self.headers[name]
                # Socket shutdown also bounds blocked writes/header reads, not just SSE reads.
                response_socket = [None]
                def expire():
                    if connection and connection.sock:
                        try:connection.sock.shutdown(socket.SHUT_RDWR)
                        except OSError:pass
                    if response_socket[0]:
                        try:response_socket[0].shutdown(socket.SHUT_RDWR)
                        except OSError:pass
                self.abort_connection=expire
                timer = threading.Timer(max(.01,timeout-(time.monotonic()-started)),expire)
                timer.daemon=True;timer.start()
                try:
                    connection.request('POST',request_path,body,headers)
                    response=connection.getresponse()
                    if self.expired.is_set():raise GuardError('deadline')
                    response_socket[0] = getattr(getattr(response.fp,'raw',None),'_sock',None)
                    if not 200 <= response.status < 300:
                        failure='http_'+str(response.status)
                        # Do not reflect provider bodies that can contain credentials or prompts.
                        self.reply(response.status if response.status in {400,401,403,404,429} else 502,
                                   {'error':{'message':f'Hybrid Control: провайдер вернул HTTP {response.status}'}})
                        return
                    def cancelled():
                        try:
                            ready,_,_=select.select([self.connection],[],[],0)
                            return bool(ready) and not self.connection.recv(1,socket.MSG_PEEK)
                        except OSError:return True
                    if 'text/event-stream' in response.getheader('Content-Type',''):
                        data=read_stream(response,started+timeout,idle,cancelled=cancelled,request=request_value)
                        content='text/event-stream'
                    else:
                        data=response.read(MAX_BYTES+1)
                        if len(data)>MAX_BYTES:raise GuardError('response_too_large')
                        value = json.loads(data)
                        validate_response(value, compact=self.path.endswith('/compact'))
                        if any(repeated_tool_call(request_value, item) for item in value.get('output', [])
                               if isinstance(item,dict) and item.get('type') in {'function_call','custom_tool_call'}):
                            raise GuardError('tool_loop')
                        content='application/json'
                    # Nothing executable reaches Codex until a complete response is validated.
                    self.reply(200,data,content)
                finally:
                    timer.cancel()
                    expire()
            except (GuardError,OSError,ValueError,http.client.HTTPException) as exc:
                failure=str(exc) if isinstance(exc,GuardError) else 'connection_failure'
                if isinstance(exc,TimeoutError):failure='deadline' if time.monotonic()>=started+timeout else 'idle_timeout'
                try:self.reply(502,{'error':{'message':'Hybrid Control: '+REASONS.get(failure,'ошибка обработки запроса')}})
                except OSError:pass
            finally:
                if connection:connection.close()
                semaphore.release()
                if self.expired.is_set():failure=self.expiration_reason or 'deadline'
                elif time.monotonic()>=started+timeout and failure:failure='deadline'
                if fingerprint:
                    with failures_lock:
                        if failure=='client_cancelled':pass
                        elif failure:
                            if len(failures)>=1024:failures.pop(next(iter(failures)))
                            failures[fingerprint]=(failures.get(fingerprint,(0,0))[0]+1,time.monotonic())
                        else:failures.pop(fingerprint,None)
                try:core.write_json_atomic(core.control_dir()/'api-guard-last.json',
                    {'status':failure or 'completed','elapsed_seconds':round(time.monotonic()-started,2),'checked_at':core.now_iso()})
                except OSError:pass
    result=ThreadingHTTPServer(('127.0.0.1',int(settings['port'])),Handler)
    result.daemon_threads=True
    return result


def health_info(settings):
    try:connection=http.client.HTTPConnection('127.0.0.1',int(settings['port']),timeout=.5)
    except (KeyError,ValueError,TypeError):return {}
    try:
        connection.request('GET','/'+settings['access']+'/health')
        response=connection.getresponse()
        from hybrid_http import read_limited
        value = json.loads(read_limited(response,time.monotonic()+.5,1024))
        return value if response.status == 200 and isinstance(value, dict) else {}
    except (OSError,ValueError,KeyError,TypeError,http.client.HTTPException):return {}
    finally:connection.close()


def healthy(settings):
    return health_info(settings).get('version') == VERSION


def ensure_started(core):
    from hybrid_storage import file_transaction
    if core.is_stock_mode():return
    with file_transaction(core.control_dir()/'api-guard-start.lock'):
        settings=load_settings(core)
        if not settings.get('enabled'):return
        health = health_info(settings)
        if health.get('version') == VERSION:return
        original = None
        if health:
            # An old daemon may still serve an existing Codex session. Give the
            # updated runtime its own endpoint; never kill a process by bare PID.
            original = settings
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
            settings = {**settings, 'port':port, 'access':secrets.token_urlsafe(32)}
            core.write_json_atomic(core.control_dir()/'api-guard.json', settings)
        if getattr(sys,'frozen',False):
            command,_=core._self_command_for_worker_mcp();args=[command,'--api-guard']
        else:args=[core._stdio_python_executable(),str(Path(__file__).resolve()),'--api-guard']
        try:
            process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             env=dict(os.environ,USERPROFILE=str(core._home()),HOME=str(core._home()),CODEX_HOME=str(core.codex_dir())),
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
        except Exception:
            if original:core.write_json_atomic(core.control_dir()/'api-guard.json', original)
            raise
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if healthy(settings):return
            if process is not None and process.poll() is not None:break
            time.sleep(.1)
        if process is not None:
            from hybrid_process import kill_tree
            kill_tree(process)
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:pass
        if original:core.write_json_atomic(core.control_dir()/'api-guard.json', original)
        raise RuntimeError('Контроль API не запустился; настройки подключения не переключены')


def install(core):
    if core.is_stock_mode():return 'Отключено в обычном Codex'
    from hybrid_proxy import repair_loopback_proxy
    repair_loopback_proxy(core)
    path=core.control_dir()/'api-guard.json'
    from hybrid_storage import file_transaction
    with file_transaction(core.control_dir()/'api-guard-start.lock'):
        original = path.read_bytes() if path.exists() else None
        try:settings=load_settings(core)
        except RuntimeError:
            # Keep the exact broken bytes for diagnosis and explicit rollback.
            path.with_name('api-guard.invalid-'+secrets.token_hex(6)+'.json').write_bytes(original)
            settings={}
        if not settings.get('enabled'):
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            settings={'enabled':True,'port':port,'access':secrets.token_urlsafe(32)}
            core.write_json_atomic(path,settings)
        try:ensure_started(core)
        except Exception:
            if original is None:path.unlink(missing_ok=True)
            else:
                from hybrid_recovery import write_bytes
                write_bytes(core,path,original)
            raise
    return 'Контроль API активен: максимум 180 секунд на запрос, 60 секунд тишины; без воспроизведения инструментов. Локальный адрес исключён из прокси; полностью перезапустите Codex.'


def main():
    import codex_hybrid_control as core
    settings=load_settings(core)
    if settings.get('enabled'):server(core,settings).serve_forever()


if __name__=='__main__':main()
