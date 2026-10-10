"""Transactional, reversible removal of Hybrid Control integration files."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading
from hybrid_storage import file_transaction

_LOCK=threading.RLock()


def state_path(core):
    return core.control_dir()/'restore-point.json'


def stock_state(core):
    path=state_path(core)
    if not path.exists():return {}
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:
        raise RuntimeError('Не удалось прочитать снимок восстановления. Автоматическая настройка остановлена.') from exc
    if not isinstance(value,dict):raise RuntimeError('Некорректный снимок восстановления.')
    if 'active' in value and not isinstance(value['active'],bool):raise RuntimeError('Некорректное состояние снимка восстановления.')
    return value


def is_stock_mode(core):
    return stock_state(core).get('active',False) is True


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def read_bytes(path):
    return path.read_bytes() if path.exists() else None


def write_bytes(core,path,data):
    if data is None:
        if path.exists():path.unlink()
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.hybrid-tmp')
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            if temporary.exists():temporary.unlink()


def without_tables(text,names):
    result=[];skip=False
    for line in text.splitlines(keepends=True):
        match=re.match(r'^\s*\[([^\[\]]+)\]\s*(?:#.*)?$',line.strip())
        if match:
            table=match.group(1).strip()
            skip=any(table==name or table.startswith(name+'.') for name in names)
        elif re.match(r'^\s*\[\[',line):skip=False
        if not skip:result.append(line)
    return ''.join(result)


def without_table_key(text,table,key):
    result=[];inside=False
    for line in text.splitlines(keepends=True):
        match=re.match(r'^\s*\[([^\[\]]+)\]\s*(?:#.*)?$',line.strip())
        if match:inside=match.group(1).strip()==table
        elif re.match(r'^\s*\[',line):inside=False
        if inside and re.match(r'^\s*'+re.escape(key)+r'\s*=',line):continue
        result.append(line)
    return ''.join(result)


def clean_config(core,text):
    expected=copy.deepcopy(core.validate_toml(text))
    for key in ('model_provider','model','review_model','model_reasoning_effort','model_catalog_json'):expected.pop(key,None)
    for table,names in [('model_providers',[core.API_PROVIDER]),('mcp_servers',['hybridWorkers','hybridComputer']),('agents',['enabled'])]:
        if isinstance(expected.get(table),dict):
            for key in names:expected[table].pop(key,None)
    out=core.edit_root_keys(text,{},remove_keys={'model_provider','model','review_model','model_reasoning_effort','model_catalog_json'})
    out=without_tables(out,{'model_providers.'+core.API_PROVIDER,'mcp_servers.hybridWorkers','mcp_servers.hybridComputer'})
    out=without_table_key(out,'agents','enabled')
    parsed=core.validate_toml(out)
    def prune(value):
        if isinstance(value,dict):return {key:prune(item) for key,item in value.items() if item!={}}
        return value
    if prune(parsed)!=prune(expected):
        raise RuntimeError('Нестандартная запись TOML не позволяет безопасно отключить интеграции. Конфигурация сохранена без изменений.')
    return out


def clean_agents(core,text):
    for begin,end in [(core.WORKER_INSTRUCTIONS_BEGIN,core.WORKER_INSTRUCTIONS_END),
                      (core.COMPUTER_INSTRUCTIONS_BEGIN,core.COMPUTER_INSTRUCTIONS_END)]:
        if text.count(begin)!=text.count(end):raise RuntimeError('Повреждён управляемый блок AGENTS.md. Файл не изменён.')
        text=re.sub(re.escape(begin)+r'.*?'+re.escape(end)+r'\r?\n?', '',text,flags=re.S)
        if begin in text or end in text:raise RuntimeError('Нарушен порядок управляемых блоков AGENTS.md. Файл не изменён.')
    return text


def managed_paths(core,config):
    return [Path(config),Path(config).parent/'hooks.json',core.global_agents_path(),core.computer_policy_path(),core.app_state_path(),
            *[core.codex_dir()/f'{name}.config.toml' for name in core.WORKER_PROFILES]]


def restore_candidate(core, path, row, current, config_path):
    """Preserve a rotated Codex pipe path; reject every other changed byte."""
    before=base64.b64decode(row['before'],validate=True) if row.get('before') is not None else None
    if digest(current)==row.get('stock_hash'):
        return before
    if Path(path).resolve()!=Path(config_path).resolve() or before is None or current is None:
        raise ValueError('Changed file')
    bom=b'\xef\xbb\xbf' if before.startswith(b'\xef\xbb\xbf') else b''
    original=before.decode('utf-8-sig')
    baseline=clean_config(core,original)
    if digest(bom+baseline.encode('utf-8'))!=row.get('stock_hash'):
        raise ValueError('Unknown stock baseline')
    text=current.decode('utf-8-sig')
    table='mcp_servers.node_repl.env'
    key='SKY_CUA_NATIVE_PIPE_DIRECTORY'
    def pipe_value(source):
        value=core.validate_toml(source).get('mcp_servers',{}).get('node_repl',{}).get('env',{}).get(key)
        if not isinstance(value,str) or not value:
            raise ValueError('Missing pipe path')
        return value
    pipe_value(baseline)
    value=pipe_value(text)
    marker={key:core._toml_string('hybrid-compare-pipe-path')}
    if core.patch_table_keys(text,table,marker)!=core.patch_table_keys(baseline,table,marker):
        raise ValueError('Other config edits')
    result=core.patch_table_keys(original,table,{key:core._toml_string(value)})
    expected=copy.deepcopy(core.validate_toml(original))
    expected['mcp_servers']['node_repl']['env'][key]=value
    if core.validate_toml(result)!=expected:
        raise ValueError('Pipe patch changed other settings')
    return bom+result.encode('utf-8')


def enter_stock_mode(core,config_path):
    with _LOCK, file_transaction(core.control_dir()/'settings.lock'), file_transaction(core.control_dir()/'recovery.lock'):
        config_path=Path(config_path).resolve()
        previous=stock_state(core)
        if previous.get('active'):
            if previous.get('config_path')!=str(config_path):raise RuntimeError('Уже отключена другая конфигурация.')
            if previous.get('phase','stock')!='stock':raise RuntimeError('Предыдущее переключение прервано. Нажмите «Восстановить Hybrid» для возврата исходных файлов.')
            return {'ok':True,'already_stock':True}
        if not config_path.exists():raise RuntimeError('Конфигурация не найдена; отключать нечего.')
        paths=managed_paths(core,config_path)
        originals={str(path.resolve()):read_bytes(path) for path in paths}
        targets=dict(originals)
        config_raw=originals[str(config_path)]
        bom=config_raw.startswith(b'\xef\xbb\xbf')
        targets[str(config_path)]=(b'\xef\xbb\xbf' if bom else b'')+clean_config(core,config_raw.decode('utf-8-sig')).encode('utf-8')
        from hybrid_stop_guard import clean_hooks
        hooks=str((config_path.parent/'hooks.json').resolve())
        if originals[hooks] is not None:
            original_hooks=json.loads(originals[hooks].decode('utf-8-sig'))
            cleaned=clean_hooks(original_hooks)
            if cleaned!=original_hooks:
                targets[hooks]=json.dumps(cleaned,ensure_ascii=False,indent=2).encode('utf-8')
        agents=str(core.global_agents_path().resolve())
        if originals[agents] is not None:
            raw=originals[agents]
            targets[agents]=(b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+clean_agents(core,raw.decode('utf-8-sig')).encode('utf-8')
        policy=str(core.computer_policy_path().resolve())
        targets[policy]=json.dumps({'enabled':False,'allow_screenshot':False,'allow_input':False,'allow_launch':False}).encode('utf-8')
        targets[str(core.app_state_path().resolve())]=json.dumps({'root_mode':'STOCK','updated_at':core.now_iso()},ensure_ascii=False).encode('utf-8')
        for name in core.WORKER_PROFILES:
            path=str((core.codex_dir()/f'{name}.config.toml').resolve())
            raw=originals[path]
            if raw is not None and core.GENERATED_MARKER in raw.decode('utf-8-sig'):
                targets[path]=None
        # A pre-existing running process has loaded its own config. Do not falsely
        # promise that changing a file terminates it or revoke its work silently.
        running=[r for r in core._load_workers() if r.get('status')=='RUNNING' and core.pid_alive(int(r.get('pid') or 0))]
        if running:raise RuntimeError('Сначала остановите работающих API-агентов в мониторе, затем повторите отключение.')
        snapshot={'version':1,'active':True,'phase':'disabling','config_path':str(config_path),'created_at':core.now_iso(),
                  'files':{path:{'before':base64.b64encode(data).decode('ascii') if data is not None else None,
                                 'stock_hash':digest(targets[path])} for path,data in originals.items()}}
        old_snapshot=read_bytes(state_path(core))
        written=[]
        try:
            core.write_json_atomic(state_path(core),snapshot)
            for path,data in targets.items():
                write_bytes(core,Path(path),data);written.append(path)
            core.write_json_atomic(state_path(core),{**snapshot,'phase':'stock'})
        except Exception:
            for path in reversed(written):write_bytes(core,Path(path),originals[path])
            write_bytes(core,state_path(core),old_snapshot)
            raise
        return {'ok':True,'snapshot':str(state_path(core)),'restart_required':True}


def restore_hybrid_mode(core,config_path):
    with _LOCK, file_transaction(core.control_dir()/'settings.lock'), file_transaction(core.control_dir()/'recovery.lock'):
        state=stock_state(core)
        if not state.get('active'):raise RuntimeError('Нет активного снимка для возврата из обычного Codex.')
        if state.get('config_path')!=str(Path(config_path).resolve()):raise RuntimeError('Снимок относится к другой конфигурации.')
        files=state.get('files',{})
        allowed={str(p.resolve()) for p in managed_paths(core,config_path)}
        if not files or set(files) not in (allowed,allowed-{str((Path(config_path).parent/'hooks.json').resolve())}):raise RuntimeError('Состав файлов снимка не прошёл проверку.')
        current={path:read_bytes(Path(path)) for path in files}
        restored={path:base64.b64decode(row['before'],validate=True) if row.get('before') is not None else None for path,row in files.items()}
        interrupted=state.get('phase') in {'disabling','restoring'}
        conflicts=[]
        for path,row in files.items():
            if interrupted and digest(current[path])==digest(restored[path]):continue
            try:restored[path]=restore_candidate(core,path,row,current[path],config_path)
            except (ValueError,UnicodeError,TypeError,KeyError):conflicts.append(Path(path).name)
        if conflicts:raise RuntimeError('После отключения изменены файлы: '+', '.join(conflicts)+'. Возврат остановлен, чтобы не потерять изменения. Снимок сохранён.')
        core.validate_toml(restored[str(Path(config_path).resolve())].decode('utf-8-sig'))
        written=[]
        try:
            core.write_json_atomic(state_path(core),{**state,'phase':'restoring'})
            for path,data in restored.items():write_bytes(core,Path(path),data);written.append(path)
            core.write_json_atomic(state_path(core),{**state,'active':False,'phase':'hybrid','restored_at':core.now_iso()})
        except Exception:
            for path in reversed(written):write_bytes(core,Path(path),current[path])
            core.write_json_atomic(state_path(core),state)
            raise
        return {'ok':True,'restart_required':True}


def repair_all(core,config_path):
    with _LOCK, file_transaction(core.control_dir()/'settings.lock'), file_transaction(core.control_dir()/'recovery.lock'):
        steps=[]
        def step(name,fn):
            try:
                detail=fn()
                steps.append({'name':name,'status':'ok','detail':str(detail or 'Готово')})
                return True
            except Exception as exc:
                steps.append({'name':name,'status':'error','detail':str(exc)})
                return False
        config_path=Path(config_path)
        if is_stock_mode(core):
            step('Обычный Codex',lambda:core.validate_toml(config_path.read_text(encoding='utf-8-sig')) and 'Конфигурация корректна' or 'Конфигурация корректна')
            state=stock_state(core)
            changed=[];compatible=[]
            for path,row in state.get('files',{}).items():
                current=read_bytes(Path(path))
                if digest(current)==row.get('stock_hash'):continue
                try:restore_candidate(core,path,row,current,config_path)
                except (ValueError,UnicodeError,TypeError,KeyError):changed.append(Path(path).name)
                else:compatible.append(Path(path).name)
            steps.append({'name':'Hybrid Control','status':'warning' if changed else 'ok',
                          'detail':('После отключения изменены: '+', '.join(changed)+'. Автоматический возврат остановлен, чтобы сохранить эти изменения.' if changed else
                                    'Отключён намеренно. Для работы через API нажмите «Восстановить Hybrid».'+
                                    (' Обновлённый служебный путь Codex будет сохранён при восстановлении.' if compatible else ''))})
            return {'ok':all(s['status']=='ok' for s in steps),'steps':steps}
        # Never replace a broken user config with defaults and lose unknown settings.
        if config_path.exists() and not step('Синтаксис конфигурации',lambda:core.validate_toml(config_path.read_text(encoding='utf-8-sig')) and 'Корректен' or 'Корректен'):
            return {'ok':False,'steps':steps}
        from hybrid_api_guard import install as install_api_guard
        from hybrid_stop_guard import install as install_stop_guard
        if not step('Контроль активных API-запросов',lambda:install_api_guard(core)):
            return {'ok':False,'steps':steps}
        step('Проверка завершения ответа',lambda:install_stop_guard(core,config_path))
        step('Провайдер API',lambda:core.ensure_provider_config(config_path) and 'Настройки проверены')
        def catalog():
            from hybrid_catalog import normalize, validate
            path=core.default_catalog_path()
            if path.exists():
                try:
                    value=json.loads(path.read_text(encoding='utf-8-sig'))
                    if not core.extract_model_ids(value):raise ValueError('Empty catalog')
                    normalized=validate(normalize(value,core.extract_model_ids))
                    if normalized!=value:
                        backup=path.with_name(path.name+'.legacy-'+core.datetime.now().strftime('%Y%m%d%H%M%S%f')+'.bak')
                        shutil.copy2(path,backup);core.write_json_atomic(path,normalized)
                        return 'Метаданные каталога обновлены для Codex; исходный файл сохранён'
                    return 'Каталог корректен'
                except (ValueError,UnicodeError):
                    backup=path.with_name(path.name+'.invalid-'+core.datetime.now().strftime('%Y%m%d%H%M%S%f')+'.bak')
                    shutil.copy2(path,backup)
                    path.unlink();core.seed_catalog(path)
                    return 'Повреждённый каталог сохранён в резервную копию; создан базовый список. Обновите модели для актуального списка провайдера.'
            core.seed_catalog(path)
            return 'Создан базовый список моделей'
        step('Каталог моделей',catalog)
        def profiles():
            core.repair_worker_profiles(core.codex_dir(),core.default_catalog_path())
            invalid=[name for name in core.WORKER_PROFILES if not core.inspect_worker_profile(core.codex_dir(),name).get('ready')]
            if invalid:raise RuntimeError('Профили не готовы: '+', '.join(invalid))
            return 'Все профили прошли проверку'
        step('Профили API-агентов',profiles)
        step('Инструкции агентов',lambda:core.install_worker_instructions() and 'Готово')
        step('Инструкции компьютера',lambda:core.install_computer_instructions() and 'Готово')
        step('Мост API-агентов',lambda:core.install_worker_mcp(config_path) and 'Готово')
        step('Локальный мост компьютера',lambda:core.install_computer_mcp(config_path) and 'Готово')
        if core.current_root_info(config_path).get('provider')==core.API_PROVIDER:
            step('Режим API',lambda:core.enforce_api_only_root_policy(config_path) and 'Нативные агенты отключены')
            step('Разрешения локальных инструментов',lambda:core.enable_full_api_computer_policy() and 'Мост, снимки, ввод и запуск включены')
        cli=bool(shutil.which(core.codex_command()))
        steps.append({'name':'Codex CLI','status':'ok' if cli else 'warning','detail':'Найден' if cli else 'Codex CLI не найден. Установите его и повторите проверку.'})
        key=core.user_api_key_present()
        steps.append({'name':'API-ключ','status':'ok' if key else 'warning','detail':'Сохранён. Доступность провайдера не проверялась.' if key else 'Добавьте ключ в разделе подключения API.'})
        step('Итоговая конфигурация',lambda:core.validate_toml(config_path.read_text(encoding='utf-8-sig')) and 'Корректна. Для переподключения мостов нужен новый сеанс Codex.' or 'Корректна')
        return {'ok':all(row['status']=='ok' for row in steps),'steps':steps}
