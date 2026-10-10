"""Honest local compatibility checks, bounded API probes, and redacted exports."""
import base64
import io
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from hybrid_process import kill_tree


SECRET_KEYS = re.compile(r'(api[_-]?key|token|password|authorization|secret|cookie|encrypted_key|before_data|after_data)',re.I)


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {key:('[скрыто]' if SECRET_KEYS.search(str(key)) and not str(key).endswith('_present') else redact(item,secrets))
                for key,item in value.items()}
    if isinstance(value,list): return [redact(item,secrets) for item in value]
    if not isinstance(value,str): return value
    value = re.sub(r'(http://127\.0\.0\.1:\d+/)[A-Za-z0-9_-]{32,}(/v1)',r'\1[скрыто]\2',value)
    for secret in secrets:
        if secret: value = value.replace(str(secret),'[скрыто]')
    value = re.sub(r'(?i)(Bearer\s+)[^\s"\'<>]+',r'\1[скрыто]',value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[скрыто]',value)
    value = re.sub(r'(?im)((?:[A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|SECRET))\s*[:=]\s*)[^\r\n]+',r'\1[скрыто]',value)
    value = re.sub(r'(?i)([?&](?:key|api_key|token|access_token|secret|password)=)[^&\s"\']+',r'\1[скрыто]',value)
    value = re.sub(r'(?i)(https?://)[^/\s:@]+:[^/\s@]+@',r'\1[скрыто]@',value)
    # Log bodies are not copied: even a provider can echo a secret under an
    # arbitrary field name. This filter is defense in depth for summary errors.
    return value


def _step(name,status,detail,**extra):
    return {'name':name,'status':status,'detail':detail,**extra}


def mcp_probe(command,args,expected,timeout=12,env=None):
    requests = [{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'hybrid-check','version':'1'}}},
                {'jsonrpc':'2.0','method':'notifications/initialized'},
                {'jsonrpc':'2.0','id':2,'method':'ping'},
                {'jsonrpc':'2.0','id':3,'method':'tools/list'}]
    process = subprocess.Popen([command]+list(args),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                       encoding='utf-8',errors='replace',env=env,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
    try:
        output,error = process.communicate('\n'.join(json.dumps(row) for row in requests)+'\n',timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(process);process.communicate(timeout=10)
        raise TimeoutError('Мост не ответил на initialize/ping/tools/list за отведённое время') from None
    if process.returncode: raise RuntimeError(f'Мост завершился с кодом {process.returncode}')
    rows = {row.get('id'):row for row in (json.loads(line) for line in output.splitlines() if line.strip())}
    if rows.get(1,{}).get('result',{}).get('serverInfo') is None or 'result' not in rows.get(2,{}):
        raise RuntimeError('Мост не подтвердил initialize и ping')
    tools = rows.get(3,{}).get('result',{}).get('tools',[])
    names = {tool.get('name') for tool in tools}
    missing = set(expected)-names
    if missing: raise RuntimeError('Не хватает инструментов: '+', '.join(sorted(missing)))
    return {'version':rows[1]['result']['serverInfo'].get('version'),'tool_count':len(tools),'ping':True}


def compatibility(core, config_path):
    steps = []
    previous = core.read_json(core.control_dir()/'compatibility.json',{})
    desktop_version=None
    if os.name=='nt':
        try:
            script="[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); Get-AppxPackage -Name '*Codex*' | Select-Object Name,Version | ConvertTo-Json -Compress"
            result=core.run_bounded_process(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],timeout=8,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            packages=json.loads(result.stdout) if result.returncode==0 and result.stdout.strip() else []
            if isinstance(packages,dict):packages=[packages]
            if packages:
                desktop_version='; '.join(str(p['Name'])+' '+str(p['Version']) for p in packages)
                steps.append(_step('Codex Desktop','ok',desktop_version))
            else:steps.append(_step('Codex Desktop','warning','Версия пакета не определена. Проверяем доступный CLI и локальную конфигурацию.'))
        except Exception:
            steps.append(_step('Codex Desktop','warning','Версию настольного приложения определить не удалось'))
    try:
        text,_ = core.read_text_preserve_bom(Path(config_path))
        parsed = core.validate_toml(text)
        steps.append(_step('Конфигурация','ok','TOML читается'))
    except Exception as error:
        return {'ok':False,'steps':[_step('Конфигурация','error',redact(str(error),(core.get_user_api_key(),)))], 'checked_at':core.now_iso()}
    try:
        result = core.run_bounded_process([core.codex_command(),'--version'],timeout=8,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode: raise RuntimeError(f'Код завершения {result.returncode}')
        version = result.stdout.strip()[:200]
        changed = bool(previous.get('cli_version') and previous['cli_version'] != version)
        steps.append(_step('Codex CLI','ok',version,changed=changed))
        help_result = core.run_bounded_process([core.codex_command(),'exec','--help'],timeout=8,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        flags = ['--json','--sandbox','--skip-git-repo-check']
        missing = [flag for flag in flags if flag not in help_result.stdout]
        steps.append(_step('Параметры запуска','error' if missing or help_result.returncode else 'ok',
                           'Отсутствуют: '+', '.join(missing) if missing else 'Параметры внешних агентов доступны'))
    except Exception as error:
        version = None;changed=False
        steps.append(_step('Codex CLI','error',redact(str(error),(core.get_user_api_key(),))))
    provider = parsed.get('model_provider','openai')
    if not core.is_stock_mode():
        from hybrid_api_guard import healthy,load_settings
        guard_error=None;guard_settings={}
        try:
            guard_settings=load_settings(core)
            running=bool(guard_settings.get('enabled')) and healthy(guard_settings)
        except RuntimeError as error:
            guard_error=str(error);running=False
        last=core.read_json(core.control_dir()/'api-guard-last.json',{})
        if not isinstance(last,dict):last={}
        steps.append(_step('Контроль активных API-запросов','error' if guard_error else 'ok' if running else 'warning',
            (guard_error or ('Локальный шлюз отвечает. Предел запроса 180 с, тишины 60 с. Текст выдаётся после проверки полного ответа.'
             if running else 'Шлюз не запущен. Выполните «Проверить и исправить всё».'))+
            (' Последний результат: '+str(last.get('status'))+'.' if last else '')))
        from hybrid_proxy import loopback_status
        routing=loopback_status()
        steps.append(_step('Локальный маршрут и прокси','ok' if routing['ok'] else 'warning',
            'Локальные адреса исключены из прокси текущего процесса.' if routing['ok'] and routing['proxy_present']
            else 'Прокси в окружении и настройках Windows не обнаружен.' if routing['ok']
            else 'Исключения сохранены, но текущий процесс использует старое окружение. Полностью перезапустите Codex и панель.' if routing['restart_required']
            else 'Прокси может перехватывать локальный шлюз и возвращать 403. Выполните «Проверить и исправить всё», затем полностью перезапустите Codex.',
            **routing))
        provider_settings=parsed.get('model_providers',{}).get(core.API_PROVIDER,{})
        if guard_settings.get('enabled') and provider_settings:
            expected=f"http://127.0.0.1:{guard_settings['port']}/{guard_settings['access']}/v1"
            matches=str(provider_settings.get('base_url','')).rstrip('/')==expected
            steps.append(_step('Маршрут API-шлюза','ok' if matches else 'error',
                'Адрес провайдера совпадает с текущим локальным шлюзом.' if matches
                else 'Адрес провайдера устарел или отличается от текущего шлюза. Выполните «Проверить и исправить всё» и полностью перезапустите Codex.'))
    if not core.is_stock_mode():
        try:
            from hybrid_stop_guard import clean_hooks
            hooks_path=Path(config_path).parent/'hooks.json'
            hooks=json.loads(hooks_path.read_text(encoding='utf-8-sig')) if hooks_path.exists() else {}
            installed=clean_hooks(hooks)!=hooks
            receipt=core.read_json(core.control_dir()/'stop-guard'/'last-check.json',{})
            execution=(' Последний зарегистрированный запуск: '+str(receipt.get('checked_at'))+'; результат: '+str(receipt.get('status'))+'.') if receipt else ' Запуск обработчика пока не зарегистрирован.'
            steps.append(_step('Восстановление ответа API','warning',
                'Обработчик установлен. Проверьте доверие к Hybrid Control в Codex через /hooks; наличие файла не подтверждает активацию.'+execution
                if installed else 'Обработчик не установлен. Выполните «Проверить и исправить всё», затем подтвердите его через /hooks.'))
        except Exception:
            steps.append(_step('Восстановление ответа API','error','Не удалось прочитать hooks.json; существующие обработчики сохранены.'))
    model = parsed.get('model')
    catalog_path=parsed.get('model_catalog_json')
    if catalog_path:
        try:
            from hybrid_catalog import validate,check_with_codex
            validate(json.loads(Path(catalog_path).read_text(encoding='utf-8-sig')))
            check_with_codex(core,Path(catalog_path))
            steps.append(_step('Каталог Codex','ok','Метаданные приняты установленным Codex CLI'))
        except Exception as error:
            steps.append(_step('Каталог Codex','error',redact(str(error),(core.get_user_api_key(),))))
    providers = parsed.get('model_providers',{})
    if provider != 'openai':
        settings = providers.get(provider,{})
        url = urllib.parse.urlsplit(str(settings.get('base_url','')))
        valid = url.scheme in {'https','http'} and bool(url.hostname) and settings.get('wire_api')=='responses'
        steps.append(_step('Провайдер','ok' if valid else 'error',
                    'Адрес и формат Responses настроены' if valid else 'Нужны base_url HTTP/HTTPS и wire_api=responses'))
        env_key = str(settings.get('env_key') or '')
        key = core.get_user_api_key() if env_key==core.API_ENV_KEY else os.environ.get(env_key)
        steps.append(_step('Ключ подключения','ok' if key else 'warning','Ключ доступен' if key else 'Ключ не найден в окружении'))
    steps.append(_step('Модель','ok' if isinstance(model,str) and model.strip() else 'warning',
                    str(model) if model else 'Модель явно не выбрана; сетевой доступ пока не проверен'))
    for name,expected in [('hybridWorkers',core._worker_tools()),('hybridComputer',core._computer_tools())]:
        settings = parsed.get('mcp_servers',{}).get(name,{})
        if not settings or settings.get('enabled') is False:
            steps.append(_step(name,'warning','Мост не включён в конфигурации'));continue
        try:
            env = dict(os.environ)
            env.update(USERPROFILE=str(core._home()),HOME=str(core._home()),CODEX_HOME=str(core.codex_dir()))
            env.update({str(k):str(v) for k,v in settings.get('env',{}).items()})
            result = mcp_probe(settings['command'],settings.get('args',[]),[tool['name'] for tool in expected],env=env)
            version_matches = result.get('version') == core.APP_VERSION
            steps.append(_step(name,'ok' if version_matches else 'warning',
                        f"initialize/ping/tools/list: {result['tool_count']} инструментов · версия {result.get('version')}",**result))
        except Exception as error:
            steps.append(_step(name,'error',redact(str(error),(core.get_user_api_key(),))))
    changed |= bool(previous.get('desktop_version') and desktop_version and previous['desktop_version'] != desktop_version)
    payload = {'ok':not any(s['status']=='error' for s in steps),'steps':steps,
               'cli_version':version,'desktop_version':desktop_version,'version_changed':changed,'checked_at':core.now_iso(),
               'scope':'CLI и локальные мосты. Работа уже открытого сеанса Codex и живой API проверяются отдельно.'}
    core.write_json_atomic(core.control_dir()/'compatibility.json',payload)
    return payload


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise RuntimeError('API вернул перенаправление; запрос с ключом не пересылался')


def _http(base,key,path,body=None,stream=False,timeout=18):
    request = urllib.request.Request(base.rstrip('/')+path,
          data=json.dumps(body).encode('utf-8') if body is not None else None,
          headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'text/event-stream' if stream else 'application/json'})
    deadline = time.monotonic()+timeout
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=timeout) as response:
            def chunks():
                size=0
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('Ответ API не завершился вовремя')
                    try:response.fp.raw._sock.settimeout(remaining)
                    except AttributeError:pass
                    block=response.read1(65536)
                    if not block:break
                    size+=len(block)
                    if size>2_000_000:raise ValueError('Ответ API превышает лимит диагностики')
                    yield block
            if stream:
                events=[];pending=b''
                for block in chunks():
                    pending+=block
                    pending=pending.replace(b'\r\n',b'\n')
                    while b'\n\n' in pending:
                        raw,pending=pending.split(b'\n\n',1)
                        data=[line[5:].strip() for line in raw.decode('utf-8').splitlines() if line.startswith('data:')]
                        if not data:continue
                        value='\n'.join(data)
                        if value=='[DONE]':return events
                        event=json.loads(value);events.append(event)
                        if event.get('type') in {'response.completed','response.failed','response.incomplete','error'}:return events
                return events
            raw=b''.join(chunks())
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        reasons={400:'провайдер отклонил формат запроса или возможности модели',401:'ключ не принят',403:'нет доступа',
                 404:'адрес API или модель не найдены',429:'лимит запросов или баланса',500:'ошибка провайдера',502:'ошибка шлюза',503:'провайдер недоступен'}
        raise RuntimeError(f'HTTP {error.code}: {reasons.get(error.code,"запрос отклонён")}') from None


def _answer(response):
    return ''.join(part.get('text','') for item in response.get('output',[]) for part in item.get('content',[]) if part.get('type')=='output_text').strip()


def api_diagnostics(core, base_url, model, key=None):
    key = key or core.get_user_api_key()
    if not key: raise RuntimeError('Сначала укажите API-ключ')
    parsed=urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Неверный базовый адрес API')
    if parsed.scheme!='https' and parsed.hostname not in {'localhost','127.0.0.1','::1'}:
        raise ValueError('Для отправки ключа нужен HTTPS')
    if not model.strip(): raise ValueError('Выберите модель')
    steps=[]
    def probe(name, fn):
        start=time.monotonic()
        try:
            result=fn()
            if not result:raise RuntimeError('Ответ не подтвердил проверяемую возможность')
            steps.append(_step(name,'ok','Подтверждено тестовым запросом',elapsed_ms=round((time.monotonic()-start)*1000)))
            return result
        except Exception as error:
            steps.append(_step(name,'error',redact(str(error),(key,)),elapsed_ms=round((time.monotonic()-start)*1000)))
            return None
    models=probe('Список моделей',lambda:_http(base_url,key,'/models'))
    listed = model in core.extract_model_ids(models) if models else False
    if models and not listed: steps.append(_step('Модель в каталоге','warning','Модель отсутствует в списке; доступ проверяется реальным запросом'))
    nonce=uuid.uuid4().hex[:8]
    def streaming():
        events=_http(base_url,key,'/responses',{'model':model,'input':'Return exactly '+nonce,
                        'stream':True,'store':False,'max_output_tokens':256},stream=True)
        completed=next((e.get('response') for e in events if e.get('type')=='response.completed'),None)
        delta=''.join(e.get('delta','') for e in events if e.get('type')=='response.output_text.delta')
        return bool(completed and completed.get('status')=='completed' and delta.strip()==nonce and _answer(completed)==nonce)
    passed=probe('Модель и потоковый ответ',streaming)
    # Do not consume more quota after failed authentication, rate limit or base
    # protocol failure. Image/tool checks remain explicitly unconfirmed.
    if not passed:
        for name in ['Вызов инструмента','Изображения']:
            steps.append(_step(name,'skipped','Проверка не выполнялась после сбоя основного запроса'))
    else:
        def tool():
            prompt='Call diagnostic_echo with nonce '+nonce+'. After the result return only that nonce.'
            response=_http(base_url,key,'/responses',{'model':model,'input':prompt,
                'store':False,'max_output_tokens':256,'tools':[{'type':'function','name':'diagnostic_echo','description':'A harmless diagnostic echo',
                    'parameters':{'type':'object','properties':{'nonce':{'type':'string'}},'required':['nonce'],'additionalProperties':False},'strict':True}],
                'tool_choice':{'type':'function','name':'diagnostic_echo'}})
            if response.get('status')!='completed':return False
            call=next((item for item in response.get('output',[]) if item.get('type')=='function_call'
                       and item.get('name')=='diagnostic_echo' and item.get('call_id')
                       and json.loads(item.get('arguments','{}')).get('nonce')==nonce),None)
            if not call:return False
            followup=_http(base_url,key,'/responses',{'model':model,'store':False,'max_output_tokens':256,
                'input':[{'role':'user','content':prompt}]+response['output']+
                        [{'type':'function_call_output','call_id':call['call_id'],'output':nonce}]})
            return followup.get('status')=='completed' and _answer(followup)==nonce
        probe('Вызов инструмента',tool)
        def image():
            from PIL import Image,ImageDraw,ImageFont
            challenge=str(int(uuid.uuid4().hex[:4],16)%9000+1000)
            picture=Image.new('RGB',(240,100),'white')
            try:font=ImageFont.truetype('arial.ttf',62)
            except OSError:font=ImageFont.load_default(size=54)
            ImageDraw.Draw(picture).text((15,10),challenge,font=font,fill='black')
            buffer=io.BytesIO();picture.save(buffer,format='PNG')
            response=_http(base_url,key,'/responses',{'model':model,'store':False,'max_output_tokens':256,
                'input':[{'role':'user','content':[{'type':'input_text','text':'Return only the four digits shown in the image.'},
                    {'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}]}]})
            return response.get('status')=='completed' and _answer(response)==challenge
        probe('Изображения',image)
    payload={'ok':all(step['status']=='ok' for step in steps),'steps':steps,'model':model,
             'checked_at':core.now_iso(),'scope':'Прямые запросы Responses к выбранному провайдеру; не сквозной тест уже открытого Codex.'}
    core.write_json_atomic(core.control_dir()/'api-diagnostics.json',redact(payload,(key,)))
    return payload


def export_report(core, config_path, destination):
    from hybrid_bridge_host import bridge_states
    key=core.get_user_api_key()
    try: config=core.validate_toml(core.read_text_preserve_bom(Path(config_path))[0])
    except Exception as error: config={'parse_error':str(error)}
    # Whitelist configuration fields rather than copying arbitrary headers,
    # plugin arguments or environment tables that can contain unknown secrets.
    summary={name:config.get(name) for name in ['model','model_provider','model_reasoning_effort','parse_error'] if name in config}
    summary['providers']={name:{k:v for k,v in value.items() if k in {'name','base_url','wire_api','env_key','requires_openai_auth'}}
        for name,value in config.get('model_providers',{}).items() if isinstance(value,dict)}
    summary['mcp_servers']={name:{'command':value.get('command'),'enabled':value.get('enabled',True),
            'argument_count':len(value.get('args',[])),'environment_names':list(value.get('env',{}))}
        for name,value in config.get('mcp_servers',{}).items() if isinstance(value,dict)}
    data={'generated_at':core.now_iso(),'app_version':core.APP_VERSION,'configuration':redact(summary,(key,)),
          'compatibility':core.read_json(core.control_dir()/'compatibility.json',{}),
          'api':core.read_json(core.control_dir()/'api-diagnostics.json',{}),'bridges':bridge_states(core),
          'workers':[{'id':row.get('id'),'status':row.get('status'),'last_error':row.get('last_error')}
                     for row in core.refresh_worker_registry()],
          'actions':[{'action_id':row.get('action_id'),'state':row.get('state'),'name':row.get('name'),'completed_steps':row.get('completed_steps')}
                for path in (core.control_dir()/'actions').glob('*.json') if isinstance((row:=core.read_json(path,{})),dict)]}
    # Include summaries of logs, never raw model prompts, HTTP bodies, screenshots
    # or cookies: generic redaction cannot reliably identify arbitrary secrets.
    summaries=[]
    for path in sorted(core.logs_dir().glob('*'),key=lambda p:p.stat().st_mtime,reverse=True)[:12]:
        if not path.is_file():continue
        raw=path.read_bytes()[-200000:].decode('utf-8','replace')
        summaries.append({'file':path.name,'bytes':path.stat().st_size,
             'http_statuses':sorted(set(re.findall(r'\b(?:400|401|403|404|429|500|502|503)\b',raw))),
             'timeouts':len(re.findall(r'timeout|timed.out|таймаут',raw,re.I)),
             'raw_content_included':False})
    data['log_summaries']=summaries
    errors=[s for source in [data['compatibility'],data['api']] for s in source.get('steps',[]) if s.get('status')=='error']
    local_issues=[s for s in data['compatibility'].get('steps',[])
                  if s.get('status') in {'warning','error'} and s.get('name') in
                  {'Локальный маршрут и прокси','Маршрут API-шлюза','Контроль активных API-запросов'}]
    data['problem_layers']={'configuration':any(e['name'] in {'Конфигурация','Провайдер','Параметры запуска','Маршрут API-шлюза'} for e in errors),
       'bridge':any(e['name'].startswith('hybrid') for e in errors),'provider':any(e in data['api'].get('steps',[]) for e in errors),
       'local_connection':bool(local_issues)}
    core.write_json_atomic(Path(destination),redact(data,(key,)))
    return {'ok':True,'path':str(destination),'raw_logs_included':False}
