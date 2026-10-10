"""Connection profiles and encrypted, conflict-aware settings checkpoints."""
import base64
import ctypes
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.parse
import uuid
from hybrid_storage import file_transaction
from hybrid_diagnostics import redact


class Blob(ctypes.Structure):
    _fields_ = [('size',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data, decrypt=False):
    if os.name != 'nt': raise RuntimeError('Хранение ключей и снимков требует Windows DPAPI')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise RuntimeError('Windows не смог защитить или открыть данные этого пользователя')
    try: return ctypes.string_at(target.data,target.size)
    finally: ctypes.windll.kernel32.LocalFree(target.data)


def protect(data): return base64.b64encode(_crypt(data)).decode('ascii')
def unprotect(data): return _crypt(base64.b64decode(data),decrypt=True)
def digest(data): return hashlib.sha256(data).hexdigest() if data is not None else None


def validate_key(value):
    value=value.strip()
    if not value or len(value)>4096 or any(character.isspace() or ord(character)<32 for character in value):
        raise ValueError('Введите только API-ключ, без пробелов, переносов строк и префикса Bearer')
    return value


def active_connection(core):
    path = core.control_dir()/'active-connection.json'
    if not path.exists():
        return {'name':'Tokify / Funpay','base_url':core.API_BASE+'/v1','model':'',
                'reasoning':'high','worker_models':{}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        validate(data)
        return data
    except (ValueError,OSError,TypeError) as error:
        raise RuntimeError('Профиль подключения повреждён; восстановите снимок или выберите профиль заново') from error


def validate(data):
    if not isinstance(data,dict): raise ValueError('Некорректный профиль')
    if not str(data.get('name','')).strip(): raise ValueError('Укажите название профиля')
    url = urllib.parse.urlsplit(str(data.get('base_url','')))
    if url.scheme not in {'https','http'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Укажите базовый URL API без логина, пароля и параметров запроса')
    if url.scheme=='http' and url.hostname not in {'127.0.0.1','localhost','::1'}:
        raise ValueError('Для удалённого API нужен HTTPS')
    if data.get('reasoning','high') not in {'low','medium','high'}: raise ValueError('Неверный уровень рассуждений')
    if not isinstance(data.get('worker_models',{}),dict):raise ValueError('Некорректные модели агентов')
    for value in [data.get('model','')]+list(data.get('worker_models',{}).values()):
        if not isinstance(value,str) or len(value)>200 or any(ord(c)<32 for c in value): raise ValueError('Неверное имя модели')


class Connections:
    def __init__(self,core):
        self.core=core
        self.path=core.control_dir()/'connections.json'

    def _load(self):
        if not self.path.exists(): return []
        try: rows=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError) as error: raise RuntimeError('Файл профилей повреждён; изменения остановлены') from error
        if not isinstance(rows,list):raise RuntimeError('Файл профилей повреждён')
        try:
            identifiers=set()
            for row in rows:
                validate(row)
                if not re.fullmatch('[a-f0-9]{32}',str(row.get('id',''))) or row['id'] in identifiers:
                    raise ValueError('Invalid profile ID')
                if row.get('encrypted_key') is not None and not isinstance(row['encrypted_key'],str):
                    raise ValueError('Invalid protected key')
                identifiers.add(row['id'])
        except (ValueError,TypeError,KeyError) as error:
            raise RuntimeError('Файл профилей повреждён; изменения остановлены') from error
        return rows

    def list(self):
        return [{key:value for key,value in row.items() if key!='encrypted_key'} |
                {'key_present':bool(row.get('encrypted_key'))} for row in self._load()]

    def save(self,name,base_url,model,reasoning='high',key=None,worker_models=None,profile_id=None):
        row={'id':profile_id or uuid.uuid4().hex,'name':name.strip(),'base_url':base_url.rstrip('/'),
             'model':model.strip(),'reasoning':reasoning,'worker_models':worker_models or {}}
        validate(row)
        with file_transaction(self.path.with_suffix('.lock')):
            rows=self._load()
            existing=next((r for r in rows if r['id']==row['id']),{})
            if key is not None:
                row['encrypted_key']=protect(validate_key(key).encode('utf-8')) if key else None
            elif existing.get('encrypted_key'):row['encrypted_key']=existing['encrypted_key']
            rows=[r for r in rows if r['id']!=row['id']]+[row]
            self.core.write_json_atomic(self.path,rows)
        return {k:v for k,v in row.items() if k!='encrypted_key'}

    def get(self,profile_id):
        row=next((r for r in self._load() if r['id']==profile_id),None)
        if row is None:raise ValueError('Профиль не найден')
        validate(row)
        return row

    def delete(self,profile_id):
        with file_transaction(self.path.with_suffix('.lock')):
            self.core.write_json_atomic(self.path,[r for r in self._load() if r['id']!=profile_id])

    def preview(self,profile_id,config_path):
        row=self.get(profile_id)
        current,_=self.core.read_text_preserve_bom(Path(config_path))
        result=mode_text(self.core,current,'api',row['model'],row['reasoning'],'api_only',row)
        return {'profile':{k:v for k,v in row.items() if k!='encrypted_key'},
                'diff':redact('\n'.join(difflib.unified_diff(current.splitlines(),result.splitlines(),fromfile='Сейчас',tofile='После применения',lineterm='')),
                              (self.core.get_user_api_key(),)),
                'source_hash':digest(Path(config_path).read_bytes()),
                'profile_hash':digest(json.dumps(row,sort_keys=True,ensure_ascii=False).encode('utf-8')),
                'key_present':bool(row.get('encrypted_key')),
                'notes':['Будут обновлены API-модель, endpoint и ключ активного подключения.',
                         'При применении Codex подключается через локальный шлюз защиты; его адрес назначается автоматически. Адрес провайдера сохраняется в профиле.',
                         'Профили агентов и инструкции обновятся; для Codex нужен новый сеанс.',
                         'Включатся снимки экрана, ввод и запуск приложений через локальный мост.']}

    def apply(self,profile_id,config_path,expected_hash=None,expected_profile_hash=None):
        with file_transaction(self.path.with_suffix('.lock')):
            return self._apply(profile_id,config_path,expected_hash,expected_profile_hash)

    def _apply(self,profile_id,config_path,expected_hash=None,expected_profile_hash=None):
        if self.core.is_stock_mode():raise RuntimeError('Сначала восстановите Hybrid Control')
        row=self.get(profile_id)
        if expected_profile_hash is not None and digest(json.dumps(row,sort_keys=True,ensure_ascii=False).encode('utf-8'))!=expected_profile_hash:
            raise RuntimeError('Профиль изменился после предпросмотра; откройте его заново')
        if not row.get('model'):raise ValueError('Укажите модель в профиле')
        key=unprotect(row['encrypted_key']).decode('utf-8') if row.get('encrypted_key') else None
        if not key:raise ValueError('В профиле нет ключа; сохраните ключ перед переключением')
        def work():
            self.core.write_json_atomic(self.core.control_dir()/'active-connection.json',
                                        {k:v for k,v in row.items() if k!='encrypted_key'})
            self.core.set_user_api_key(key)
            if row['base_url'].rstrip('/') != self.core.API_BASE+'/v1':
                models = sorted({row['model'], *row.get('worker_models',{}).values()} - {''})
                from hybrid_catalog import catalog
                self.core.write_json_atomic(self.core.default_catalog_path(),
                    catalog(models,'Hybrid connection profile'))
            self.core.apply_mode(Path(config_path),'api',row['model'],row['reasoning'],'api_only')
            self.core.repair_worker_profiles(self.core.codex_dir(),self.core.default_catalog_path())
            self.core.prepare_api_autonomy(Path(config_path))
            self.core.update_global_mode('api',self.core.API_PROVIDER,row['model'],'api_only')
            return {'ok':True,'profile':row['name'],'model':row['model']}
        return SettingsTransaction(self.core,config_path).execute(work,'Смена подключения',expected_hash)


def mode_text(core,text,mode,model,reasoning,delegation,connection=None):
    core.validate_toml(text)
    connection=connection or active_connection(core)
    from hybrid_api_guard import endpoint
    if mode=='api':
        if not model.strip():raise ValueError('Выберите модель')
        values={'model_provider':core._toml_string(core.API_PROVIDER),'model':core._toml_string(model),
                'review_model':core._toml_string(model),'model_reasoning_effort':core._toml_string(reasoning),
                'model_catalog_json':core._toml_string(core.default_catalog_path().as_posix())}
        result=core.edit_root_keys(text,values)
    elif mode=='official':
        values={'model_provider':core._toml_string(core.OFFICIAL_PROVIDER),'model':core._toml_string(core.OFFICIAL_MODEL),
                'review_model':core._toml_string(core.OFFICIAL_MODEL),'model_reasoning_effort':core._toml_string(reasoning)}
        result=core.edit_root_keys(text,values,remove_keys={'model_catalog_json'})
    else:raise ValueError('Неизвестный режим')
    result=core.patch_table_keys(result,'agents',{'enabled':'false' if mode=='api' or delegation=='api_only' else 'true'})
    result=core.patch_table_keys(result,'model_providers.funpay',{'name':core._toml_string(connection['name']),
             'base_url':core._toml_string(endpoint(core,connection['base_url'])),'wire_api':'"responses"','supports_websockets':'false',
             'env_key':core._toml_string(core.API_ENV_KEY),'requires_openai_auth':'false',
             'request_max_retries':'0','stream_max_retries':'1','stream_idle_timeout_ms':'300000'})
    for kind,table,startup in [('Worker','hybridWorkers',15),('Computer','hybridComputer',20)]:
        if kind=='Computer' and mode!='api':continue
        if getattr(core.sys,'frozen',False):
            command=str(core.control_dir()/'bin'/f'Codex-Hybrid-{kind}-Bridge-v{core.APP_VERSION}.exe');args=[]
        else:
            command=core._stdio_python_executable();args=[str(Path(core.__file__).resolve()),'--mcp-workers' if kind=='Worker' else '--mcp-computer']
        result=core.patch_table_keys(result,'mcp_servers.'+table,{'command':core._toml_string(command),
                'args':core._toml_array(args),'startup_timeout_sec':str(startup),'tool_timeout_sec':'120','enabled':'true'})
    core.validate_toml(result)
    return result


def preview_mode(core,config_path,mode,model,reasoning,delegation='api_only'):
    path=Path(config_path)
    text,_=core.read_text_preserve_bom(path)
    result=mode_text(core,text,mode,model,reasoning,delegation)
    return {'diff':redact('\n'.join(difflib.unified_diff(text.splitlines(),result.splitlines(),fromfile='Сейчас',tofile='После применения',lineterm='')),(core.get_user_api_key(),)),
            'source_hash':digest(path.read_bytes()),'notes':['Настройки MCP, профили агентов и инструкции проверяются при применении.',
                'Для API включается локальный шлюз: 180 с на запрос, 60 с тишины, одна сетевая повторная попытка. Ответ показывается после проверки целиком.',
                'В API-режиме в hooks.json добавляется проверка раннего завершения. Новый обработчик требует доверия в Codex (/hooks).',
                'Будет сохранён зашифрованный снимок затронутых файлов. История чатов и auth.json не входят в изменения.',
                'В API-режиме включаются снимки, ввод мышью/клавиатурой и запуск приложений через локальный мост.' if mode=='api' else 'Локальные разрешения остаются согласно текущей политике.']}


class SettingsTransaction:
    def __init__(self,core,config_path):
        self.core=core
        self.config_path=Path(config_path)
        self.folder=core.control_dir()/'checkpoints'

    def paths(self):
        return list(dict.fromkeys([self.config_path,self.core.default_config_path(),self.core.app_state_path(),self.core.global_agents_path(),self.core.computer_policy_path(),
                self.config_path.parent/'hooks.json',self.core.default_catalog_path(),self.core.codex_env_path(),self.core.control_dir()/'active-connection.json',self.core.control_dir()/'api-guard.json',
                *[self.core.codex_dir()/f'{name}.config.toml' for name in self.core.WORKER_PROFILES]]))

    @staticmethod
    def read(path):return path.read_bytes() if path.exists() else None

    def execute(self,work,label,expected_hash=None):
        if self.core.is_stock_mode():raise RuntimeError('Hybrid Control отключён')
        with file_transaction(self.core.control_dir()/'settings.lock'):
            if self.core.is_stock_mode():raise RuntimeError('Hybrid Control отключён')
            if expected_hash is not None and digest(self.read(self.config_path))!=expected_hash:
                raise RuntimeError('Конфигурация изменилась после предпросмотра; откройте его заново')
            checkpoint=uuid.uuid4().hex
            files=[{'path':str(p),'before':base64.b64encode(data).decode() if (data:=self.read(p)) is not None else None}
                   for p in self.paths()]
            payload={'id':checkpoint,'label':label,'created_at':self.core.now_iso(),'files':files,
                     'before_key':self.core.get_user_api_key(),'state':'applying'}
            # Durable encrypted checkpoint exists before the first mutation.
            self._save(payload)
            try:
                result=work()
                self._finish(payload,'applied')
            except Exception as error:
                # The encrypted before-snapshot is durable, but finishing its
                # metadata can fail too. Restore from memory without relying on
                # another successful checkpoint write first.
                try:self._restore(payload)
                except Exception as restore_error:
                    raise RuntimeError('Изменение настроек не завершено; автоматический откат тоже не удался. '
                                       'Исходный снимок сохранён: '+checkpoint) from restore_error
                payload['state']='rolled_back'
                try:self._save(payload)
                except Exception:
                    raise RuntimeError(str(error)+'; исходные настройки восстановлены, '
                                       'но обновить запись снимка не удалось: '+checkpoint) from error
                raise
            return {'checkpoint_id':checkpoint,'result':result}

    def _restore(self,payload):
        from hybrid_recovery import write_bytes
        for file in payload['files']:
            write_bytes(self.core,Path(file['path']),base64.b64decode(file['before'],validate=True) if file['before'] is not None else None)
        if self.core.get_user_api_key()!=payload['before_key']:
            if payload['before_key']:self.core.set_user_api_key(payload['before_key'])
            else:self.core.remove_user_api_key()
        # The key setter may patch .env; keep its exact original bytes.
        env=next(file for file in payload['files'] if file['path']==str(self.core.codex_env_path()))
        write_bytes(self.core,self.core.codex_env_path(),base64.b64decode(env['before'],validate=True) if env['before'] is not None else None)

    def _finish(self,payload,state):
        for file in payload['files']:file['after_hash']=digest(self.read(Path(file['path'])))
        payload['after_key_hash']=digest((self.core.get_user_api_key() or '').encode())
        payload['state']=state
        self._save(payload)

    def _save(self,payload):
        encrypted=protect(json.dumps(payload,ensure_ascii=False).encode('utf-8'))
        self.core.write_json_atomic(self.folder/(payload['id']+'.json'),{'id':payload['id'],'label':payload['label'],
                  'created_at':payload['created_at'],'state':payload['state'],'encrypted':encrypted})

    def list(self):
        return sorted([{k:v for k,v in self.core.read_json(p,{}).items() if k!='encrypted'}
                       for p in self.folder.glob('*.json')],key=lambda row:row.get('created_at',''),reverse=True)

    def rollback(self,checkpoint_id):
        if self.core.is_stock_mode():raise RuntimeError('Сначала восстановите Hybrid Control из снимка отключения')
        if not re.fullmatch('[a-f0-9]{32}',str(checkpoint_id)):raise ValueError('Неверный идентификатор снимка')
        with file_transaction(self.core.control_dir()/'settings.lock'):
            if self.core.is_stock_mode():raise RuntimeError('Сначала восстановите Hybrid Control из снимка отключения')
            wrapper=self.core.read_json(self.folder/(checkpoint_id+'.json'),{})
            payload=json.loads(unprotect(wrapper['encrypted']).decode('utf-8'))
            if payload['state']=='rolled_back':raise RuntimeError('Снимок уже восстановлен')
            if payload['state']=='applying':raise RuntimeError('Операция прервалась до фиксации результата. Нужна проверка файлов; автоматический откат остановлен.')
            allowed={str(p) for p in self.paths()}
            for file in payload['files']:
                if file['path'] not in allowed:raise RuntimeError('Снимок относится к другой папке настроек')
                if digest(self.read(Path(file['path'])))!=file.get('after_hash'):
                    raise RuntimeError('После применения файл изменён вручную: '+Path(file['path']).name)
            if digest((self.core.get_user_api_key() or '').encode())!=payload.get('after_key_hash'):
                raise RuntimeError('После применения изменён API-ключ; автоматический откат остановлен')
            current={'before_key':self.core.get_user_api_key(),'files':[
                {'path':file['path'],'before':base64.b64encode(data).decode() if (data:=self.read(Path(file['path']))) is not None else None}
                for file in payload['files']]}
            try:
                self._restore(payload)
                payload['state']='rolled_back';self._save(payload)
            except Exception:
                # Failed rollback must not leave an unrecorded half-restored state.
                self._restore(current)
                raise
            return {'ok':True,'checkpoint_id':checkpoint_id}
