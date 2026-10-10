import json
from pathlib import Path
import pytest
import codex_hybrid_control as c
import hybrid_recovery as recovery


@pytest.fixture
def home(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    monkeypatch.setattr(c,'user_api_key_present',lambda:False)
    c.bootstrap_codex_files()
    c.apply_mode(c.default_config_path(),'api','test-model','high')
    c.prepare_api_autonomy(c.default_config_path())
    return tmp_path


def test_stock_roundtrip_preserves_user_content_and_bootstrap_stays_disabled(home):
    config=c.default_config_path()
    config.write_text(config.read_text(encoding='utf-8')+'\n[custom]\nvalue = "keep"\n',encoding='utf-8')
    agents=c.global_agents_path()
    agents.write_text('# Personal instructions\n'+agents.read_text(encoding='utf-8'),encoding='utf-8')
    auth=c.codex_dir()/'auth.json';auth.write_text('private-auth',encoding='utf-8')
    paths=recovery.managed_paths(c,config)
    before={path:path.read_bytes() if path.exists() else None for path in paths}
    c.enter_stock_mode(config)
    assert c.is_stock_mode()
    parsed=c.validate_toml(config.read_text(encoding='utf-8'))
    assert parsed['custom']['value']=='keep'
    assert 'model_provider' not in parsed
    assert 'hybridComputer' not in parsed.get('mcp_servers',{})
    assert 'funpay' not in parsed.get('model_providers',{})
    assert 'enabled' not in parsed.get('agents',{})
    assert 'Personal instructions' in agents.read_text(encoding='utf-8')
    assert c.WORKER_INSTRUCTIONS_BEGIN not in agents.read_text(encoding='utf-8')
    assert not c.computer_policy()['enabled']
    after={path:path.read_bytes() if path.exists() else None for path in paths}
    c.bootstrap_codex_files();c.repair_all(config);c.enter_stock_mode(config)
    assert after=={path:path.read_bytes() if path.exists() else None for path in paths}
    c.restore_hybrid_mode(config)
    assert not c.is_stock_mode()
    assert before=={path:path.read_bytes() if path.exists() else None for path in paths}
    assert auth.read_text(encoding='utf-8')=='private-auth'


def test_restore_refuses_to_overwrite_new_user_edits(home):
    config=c.default_config_path();c.enter_stock_mode(config)
    config.write_text(config.read_text(encoding='utf-8')+'\n# new edit\n',encoding='utf-8')
    with pytest.raises(RuntimeError,match='изменены файлы'):c.restore_hybrid_mode(config)
    assert '# new edit' in config.read_text(encoding='utf-8')
    assert c.is_stock_mode()


def test_rotated_codex_pipe_does_not_block_restore_and_new_path_survives(home):
    config=c.default_config_path()
    text=c.patch_table_keys(config.read_text(encoding='utf-8'),'mcp_servers.node_repl.env',
                           {'SKY_CUA_NATIVE_PIPE_DIRECTORY':'"old-runtime-pipe"'})
    config.write_text(text,encoding='utf-8')
    original=c.validate_toml(text)
    c.enter_stock_mode(config)
    config.write_text(c.patch_table_keys(config.read_text(encoding='utf-8'),'mcp_servers.node_repl.env',
                      {'SKY_CUA_NATIVE_PIPE_DIRECTORY':'"new-runtime-pipe"'}),encoding='utf-8')
    result=c.repair_all(config)
    assert result['ok'] and 'служебный путь' in result['steps'][-1]['detail']
    assert c.is_stock_mode()
    c.restore_hybrid_mode(config)
    original['mcp_servers']['node_repl']['env']['SKY_CUA_NATIVE_PIPE_DIRECTORY']='new-runtime-pipe'
    assert c.validate_toml(config.read_text(encoding='utf-8'))==original
    assert not c.is_stock_mode()


def test_rotated_pipe_does_not_hide_other_config_edits(home):
    config=c.default_config_path()
    config.write_text(c.patch_table_keys(config.read_text(encoding='utf-8'),'mcp_servers.node_repl.env',
                      {'SKY_CUA_NATIVE_PIPE_DIRECTORY':'"old-pipe"'}),encoding='utf-8')
    c.enter_stock_mode(config)
    changed=c.patch_table_keys(config.read_text(encoding='utf-8'),'mcp_servers.node_repl.env',
                             {'SKY_CUA_NATIVE_PIPE_DIRECTORY':'"new-pipe"'})+'\n# user edit\n'
    config.write_text(changed,encoding='utf-8')
    assert not c.repair_all(config)['ok']
    with pytest.raises(RuntimeError,match='изменены файлы'):c.restore_hybrid_mode(config)
    assert config.read_text(encoding='utf-8')==changed


def test_stock_check_explains_that_api_restore_is_separate(home):
    config=c.default_config_path();c.enter_stock_mode(config)
    result=c.repair_all(config)
    assert result['ok']
    assert 'Восстановить Hybrid' in result['steps'][-1]['detail']


def test_stock_failure_rolls_back_every_touched_file(home,monkeypatch):
    config=c.default_config_path()
    paths=recovery.managed_paths(c,config)
    before={p:p.read_bytes() if p.exists() else None for p in paths}
    original=recovery.write_bytes
    calls=[0]
    def fail_once(core,path,data):
        calls[0]+=1
        if calls[0]==3:raise OSError('simulated write failure')
        return original(core,path,data)
    monkeypatch.setattr(recovery,'write_bytes',fail_once)
    with pytest.raises(OSError):c.enter_stock_mode(config)
    assert not c.is_stock_mode()
    assert before=={p:p.read_bytes() if p.exists() else None for p in paths}


def test_repair_reports_missing_key_and_preserves_invalid_config(home):
    result=c.repair_all(c.default_config_path())
    assert not result['ok']
    assert any(row['name']=='API-ключ' and row['status']=='warning' for row in result['steps'])
    c.default_config_path().write_text('[broken',encoding='utf-8')
    result=c.repair_all(c.default_config_path())
    assert not result['ok']
    assert c.default_config_path().read_text(encoding='utf-8')=='[broken'


def test_worker_timeout_uses_timezone_and_keeps_terminal_status(home,monkeypatch):
    from datetime import datetime,timedelta,timezone
    row={'id':'timeout-test','pid':123,'status':'RUNNING','started_at':(datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat(),'timeout_seconds':60}
    assert c._worker_elapsed_seconds(row)>=119
    c._save_workers([row])
    monkeypatch.setattr(c,'pid_alive',lambda pid:True)
    stopped=[]
    monkeypatch.setattr(c,'stop_worker',lambda worker_id:stopped.append(worker_id) or True)
    result=c.refresh_worker_registry()
    assert stopped==['timeout-test']
    assert result[0]['status']=='TIMED_OUT'
    assert c._load_workers()[0]['status']=='TIMED_OUT'


def test_interrupted_switch_can_restore_mixed_files(home):
    import base64
    config=c.default_config_path()
    before=config.read_bytes()
    c.enter_stock_mode(config)
    state=recovery.stock_state(c)
    state['phase']='disabling'
    # Simulate power loss before this file was replaced by stock content.
    config.write_bytes(base64.b64decode(state['files'][str(config.resolve())]['before']))
    c.write_json_atomic(recovery.state_path(c),state)
    c.restore_hybrid_mode(config)
    assert config.read_bytes()==before and not c.is_stock_mode()


def test_nonstandard_toml_cannot_silently_leave_hybrid_enabled(home):
    config=c.default_config_path()
    text='model_provider="funpay"\nmcp_servers={hybridComputer={enabled=true}}\n'
    config.write_text(text,encoding='utf-8')
    with pytest.raises(RuntimeError,match='Нестандартная'):c.enter_stock_mode(config)
    assert config.read_text(encoding='utf-8')==text
    assert not c.is_stock_mode()


def test_result_refreshes_supervisor_status_without_list_call(home):
    outcome=c.logs_dir()/'completed.result.json'
    c.write_json_atomic(outcome,{'status':'TIMED_OUT','error':'timeout detail'})
    c._save_workers([{'id':'finished','pid':0,'status':'RUNNING','result_path':str(outcome)}])
    result=c._worker_result_payload('finished')
    assert result['status']=='TIMED_OUT' and result['last_error']=='timeout detail'


def test_worker_launch_includes_independent_supervisor(home,monkeypatch):
    from types import SimpleNamespace
    commands=[];environments=[]
    def popen(command,**kwargs):
        commands.append(command);environments.append(kwargs.get('env'));return SimpleNamespace(pid=98765)
    monkeypatch.setattr(c.subprocess,'Popen',popen)
    row=c.launch_api_worker('opus',home,'test-only prompt',timeout_seconds=45)
    command=commands[0]
    assert '--supervise-worker' in command and '45' in command
    assert '--sandbox' in command and 'workspace-write' in command
    assert row['pid_kind']=='supervisor' and row['result_path'].endswith('.result.json')
    assert {'127.0.0.1','localhost','::1'} <= set(environments[0]['NO_PROXY'].split(','))
