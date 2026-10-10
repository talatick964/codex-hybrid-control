"""Direct DOM actions in a separately owned Chromium profile via loopback CDP."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import uuid


def browser_environment():
    # Shell known folders must belong to the logged-in Windows user, even when
    # the MCP configuration home is isolated for diagnostics or tests.
    env = dict(os.environ)
    if os.name == 'nt':
        import ctypes
        profile = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x28, None, 0, profile) == 0:
            env['USERPROFILE'] = profile.value
            env['HOME'] = profile.value
    return env


def browser_executable():
    candidates = [shutil.which('msedge'), shutil.which('chrome')]
    for folder in (os.environ.get('PROGRAMFILES',''),os.environ.get('PROGRAMFILES(X86)',''),os.environ.get('LOCALAPPDATA','')):
        if folder:
            candidates += [str(Path(folder)/'Microsoft/Edge/Application/msedge.exe'),
                           str(Path(folder)/'Google/Chrome/Application/chrome.exe')]
    return next((value for value in candidates if value and Path(value).is_file()), None)


def safe_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Используйте HTTP/HTTPS-адрес без встроенного логина и пароля')
    return url


class BrowserControl:
    def __init__(self, core):
        self.core = core
        self.folder = core.control_dir()/'browser-session'

    def _policy(self, input=False, launch=False):
        policy = self.core.computer_policy()
        if not policy.get('enabled'): raise RuntimeError('Локальный мост отключён')
        if policy.get('control_mode') == 'mouse': raise RuntimeError('Включён режим только мыши и клавиатуры')
        if input: self.core._require_input_policy()
        if launch and not policy.get('allow_launch'): raise RuntimeError('Запуск браузера запрещён политикой')

    def start(self):
        self._policy(input=True, launch=True)
        try:
            tabs = self.tabs()
            return {'ok':True,'already_running':True,'tabs':tabs}
        except (OSError,ValueError,RuntimeError): pass
        executable = browser_executable()
        if not executable: raise RuntimeError('Не найден Chrome или Edge')
        self.folder.mkdir(parents=True, exist_ok=True)
        active = self.folder/'DevToolsActivePort'
        if active.exists(): active.unlink()
        process = subprocess.Popen([executable, '--remote-debugging-port=0',
                '--remote-debugging-address=127.0.0.1', '--no-first-run','--no-default-browser-check',
                '--user-data-dir='+str(self.folder.resolve()),'about:blank'],
                env=browser_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.core.write_json_atomic(self.folder/'owner.json',{'pid':process.pid,'created_at':self.core.now_iso()})
        deadline = time.monotonic()+12
        while time.monotonic()<deadline:
            if active.exists():
                try:
                    self.core.write_json_atomic(self.folder/'owner.json',{'pid':process.pid,'created_at':self.core.now_iso()})
                    tabs = self.tabs()
                    return {'ok':True,'already_running':False,'tabs':tabs}
                except (OSError,ValueError,RuntimeError): pass
            if process.poll() is not None and process.returncode:
                raise RuntimeError('Браузер не смог запустить отдельный профиль')
            time.sleep(.1)
        # This Popen handle belongs to the new dedicated session only.
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        raise RuntimeError('Браузер не открыл локальное соединение CDP за 12 секунд; отдельный процесс остановлен')

    def _port(self):
        owner = self.core.read_json(self.folder/'owner.json',{})
        if not self.core.pid_alive(int(owner.get('pid') or 0)):
            raise RuntimeError('Управляемый браузер закрыт. Запустите отдельную сессию.')
        lines = (self.folder/'DevToolsActivePort').read_text(encoding='utf-8').splitlines()
        port = int(lines[0])
        if not 1<=port<=65535: raise ValueError('Некорректный порт браузера')
        return port

    def tabs(self):
        self._policy()
        port = self._port()
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=3) as response:
            rows = json.loads(response.read(2_000_000))
        return [{'tab_id':row['id'],'title':row.get('title',''),'url':row.get('url','')}
                for row in rows if row.get('type')=='page']

    def _socket(self, tab_id):
        import websocket
        port = self._port()
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=3) as response:
            rows = json.loads(response.read(2_000_000))
        page = next((row for row in rows if row.get('id')==tab_id and row.get('type')=='page'),None)
        if not page: raise ValueError('Вкладка не найдена; получите список вкладок')
        address = page.get('webSocketDebuggerUrl','')
        parsed = urllib.parse.urlsplit(address)
        if parsed.scheme!='ws' or parsed.hostname!='127.0.0.1' or parsed.port!=port:
            raise RuntimeError('Браузер вернул неверный локальный адрес соединения')
        return websocket.create_connection(address, timeout=6, suppress_origin=True)

    @staticmethod
    def _rpc(connection, method, params):
        request_id = uuid.uuid4().hex
        # CDP IDs must be integers.
        request_id = int(request_id[:7],16)
        connection.send(json.dumps({'id':request_id,'method':method,'params':params}))
        deadline = time.monotonic()+6
        while time.monotonic()<deadline:
            connection.settimeout(max(.05,deadline-time.monotonic()))
            row = json.loads(connection.recv())
            if row.get('id')!=request_id: continue
            if row.get('error'): raise RuntimeError('CDP отклонил команду: '+str(row['error'].get('message','')))
            return row.get('result',{})
        raise TimeoutError('CDP не ответил вовремя')

    def _evaluate(self, tab_id, expression):
        connection = self._socket(tab_id)
        try:
            result = self._rpc(connection,'Runtime.evaluate',{'expression':expression,'returnByValue':True})
            if result.get('exceptionDetails'): raise RuntimeError('Страница изменилась или не поддерживает действие')
            return result.get('result',{}).get('value')
        finally: connection.close()

    def navigate(self, tab_id, url):
        self._policy(input=True)
        url = safe_url(url)
        connection = self._socket(tab_id)
        try:
            result = self._rpc(connection,'Page.navigate',{'url':url})
            if result.get('errorText'): raise RuntimeError(result['errorText'])
        finally: connection.close()
        def normalized(address):
            parts=urllib.parse.urlsplit(address)
            return (parts.scheme,parts.netloc,parts.path or '/',parts.query,parts.fragment)
        deadline = time.monotonic()+8
        while time.monotonic()<deadline:
            state = self._evaluate(tab_id,'({url:location.href,ready:document.readyState})')
            if state and state.get('ready') in {'interactive','complete'} and normalized(state.get('url',''))==normalized(url):
                return {'ok':True,'dispatched':True,'verified':True,'url':state['url']}
            time.sleep(.15)
        return {'ok':True,'dispatched':True,'verified':False,'hint':'Переход отправлен, загрузка ещё не подтверждена'}

    def close(self):
        self._policy(input=True)
        tabs=self.tabs()
        if not tabs:raise RuntimeError('Управляемый браузер не имеет доступных вкладок')
        owner=self.core.read_json(self.folder/'owner.json',{})
        connection=self._socket(tabs[0]['tab_id'])
        try:
            self._rpc(connection,'Browser.close',{})
        except (OSError,RuntimeError):
            # The browser may close the socket before returning its reply.
            pass
        finally:connection.close()
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            if not self.core.pid_alive(int(owner.get('pid') or 0)):
                return {'ok':True,'dispatched':True,'verified':True}
            time.sleep(.1)
        return {'ok':False,'error':'Закрытие браузера не подтверждено'}

    def inspect(self, tab_id):
        self._policy()
        snapshot = uuid.uuid4().hex
        # No caller-supplied JavaScript. References are actual DOM nodes, never
        # selector strings that could accidentally retarget a different control.
        script = r'''(()=>{
 const nodes=[...document.querySelectorAll('button,a,input,textarea,select,[role="button"],[contenteditable="true"]')]
  .filter(e=>e.getClientRects().length&&!e.hidden).slice(0,200);
 const snapshot=__SNAPSHOT__;
 window.__hybridNodes={snapshot,created:Date.now(),url:location.href,nodes};
 return {ok:true,snapshot,url:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,6000),
 elements:nodes.map((e,i)=>({element_id:snapshot+':'+i,tag:e.tagName.toLowerCase(),
  name:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||e.name||'').slice(0,160),
  type:e.getAttribute('type')||'',disabled:!!e.disabled,password:e.type==='password'}))};
})()'''.replace('__SNAPSHOT__',json.dumps(snapshot))
        return self._evaluate(tab_id,script)

    def act(self, tab_id, element_id, operation, value=None):
        self._policy(input=True)
        if operation not in {'click','fill'}: raise ValueError('Поддерживаются click и fill')
        if value is not None and len(str(value))>12000: raise ValueError('Значение слишком длинное')
        script = r'''(()=>{
 const id=__ID__,operation=__OP__,value=__VALUE__,state=window.__hybridNodes;
 const parts=id.split(':');
 if(!state||parts[0]!==state.snapshot||Date.now()-state.created>90000||state.url!==location.href)
  return {ok:false,error:'Список элементов устарел; получите новый снимок структуры'};
 const e=state.nodes[Number(parts[1])];
 if(!e||!e.isConnected||!e.getClientRects().length||e.disabled)
  return {ok:false,error:'Элемент недоступен'};
 window.__hybridNodes=null;
 if(operation==='fill'){
  if(e.type==='password')return {ok:false,error:'Парольные поля требуют ручного ввода'};
  if(!['INPUT','TEXTAREA'].includes(e.tagName)||e.readOnly)return {ok:false,error:'Поле не поддерживает ввод'};
  const proto=e.tagName==='INPUT'?HTMLInputElement.prototype:HTMLTextAreaElement.prototype;
  Object.getOwnPropertyDescriptor(proto,'value').set.call(e,value);
  e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));
  return {ok:e.value===value,dispatched:true,verified:e.value===value,chars:value.length};
 }
 e.click();return {ok:true,dispatched:true,verified:false,hint:'Проверьте ожидаемое состояние страницы'};
})()'''.replace('__ID__',json.dumps(str(element_id))).replace('__OP__',json.dumps(operation)).replace('__VALUE__',json.dumps(str(value or '')))
        return self._evaluate(tab_id,script)
