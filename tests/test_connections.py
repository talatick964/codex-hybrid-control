import json
import pytest
import codex_hybrid_control as c
from hybrid_connections import Connections,SettingsTransaction,preview_mode


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    key=[None]
    monkeypatch.setattr(c,'get_user_api_key',lambda:key[0])
    monkeypatch.setattr(c,'user_api_key_present',lambda:bool(key[0]))
    def set_key(value):key[0]=value;c._patch_codex_env_secret(value)
    def remove_key():key[0]=None;c._patch_codex_env_secret(None)
    monkeypatch.setattr(c,'set_user_api_key',set_key)
    monkeypatch.setattr(c,'remove_user_api_key',remove_key)
    c.bootstrap_codex_files()
    return Connections(c)


def test_profile_switch_encrypted_key_preview_and_rollback(setup):
    config=c.default_config_path();original=config.read_bytes()
    row=setup.save('Test provider','https://example.com/v1','test-model',key='test-secret',
                   worker_models={n:'test-worker' for n in c.WORKER_PROFILES})
    assert 'test-secret' not in setup.path.read_text(encoding='utf-8')
    before=setup.preview(row['id'],config)
    assert 'example.com/v1' in before['diff']
    assert 'test-secret' not in json.dumps(before)
    result=setup.apply(row['id'],config,before['source_hash'])
    parsed=c.validate_toml(config.read_text(encoding='utf-8'))
    assert parsed['model_providers']['funpay']['base_url'].startswith('http://127.0.0.1:')
    from hybrid_connections import active_connection
    assert active_connection(c)['base_url']=='https://example.com/v1'
    assert c.get_user_api_key()=='test-secret'
    assert all(c.inspect_worker_profile(c.codex_dir(),n)['ready'] for n in c.WORKER_PROFILES)
    SettingsTransaction(c,config).rollback(result['checkpoint_id'])
    assert config.read_bytes()==original and c.get_user_api_key() is None


def test_preview_refuses_changed_configuration(setup):
    config=c.default_config_path()
    before=preview_mode(c,config,'api','model','high')
    config.write_text(config.read_text(encoding='utf-8')+'\n# manual change\n',encoding='utf-8')
    with pytest.raises(RuntimeError,match='предпросмотра'):
        SettingsTransaction(c,config).execute(lambda:pytest.fail('Mutated'),'test',before['source_hash'])


def test_rollback_refuses_to_overwrite_manual_edits(setup):
    config=c.default_config_path()
    result=SettingsTransaction(c,config).execute(lambda:c.apply_mode(config,'api','test-model','high'),'test')
    config.write_text(config.read_text(encoding='utf-8')+'\n# manual\n',encoding='utf-8')
    with pytest.raises(RuntimeError,match='вручную'):
        SettingsTransaction(c,config).rollback(result['checkpoint_id'])
    assert '# manual' in config.read_text(encoding='utf-8')


def test_failed_setting_change_is_rolled_back(setup):
    config=c.default_config_path();before=config.read_bytes()
    def fail():config.write_text('broken');raise RuntimeError('simulated')
    with pytest.raises(RuntimeError,match='simulated'):
        SettingsTransaction(c,config).execute(fail,'failure')
    assert config.read_bytes()==before


def test_stock_prevents_profile_activation(setup):
    row=setup.save('test','https://example.com/v1','model',key='secret')
    c.enter_stock_mode(c.default_config_path())
    with pytest.raises(RuntimeError,match='восстановите'):
        setup.apply(row['id'],c.default_config_path())


def test_alternate_provider_key_never_sent_to_tokify(setup,monkeypatch):
    c.write_json_atomic(c.control_dir()/'active-connection.json',{'name':'test','base_url':'https://example.com/v1','model':'model'})
    monkeypatch.setattr(c.urllib.request,'urlopen',lambda *a,**k:pytest.fail('Sent wrong provider key'))
    with pytest.raises(RuntimeError,match='провайдера'):c.validate_api_key('private-key')


def test_preview_includes_computer_bridge_that_api_mode_will_enable(setup):
    preview=preview_mode(c,c.default_config_path(),'api','test-model','high')
    assert '[mcp_servers.hybridComputer]' in preview['diff']
    assert 'ввод' in ' '.join(preview['notes'])


def test_profile_edit_after_preview_cannot_apply_unreviewed_settings(setup):
    config=c.default_config_path();original=config.read_bytes()
    row=setup.save('test','https://example.com/v1','model',key='secret')
    preview=setup.preview(row['id'],config)
    setup.save('changed','https://other.example/v1','different-model',profile_id=row['id'])
    with pytest.raises(RuntimeError,match='Профиль изменился'):
        setup.apply(row['id'],config,preview['source_hash'],preview['profile_hash'])
    assert config.read_bytes()==original and c.get_user_api_key() is None


@pytest.mark.parametrize('rows',[[None],[{}],[{'id':'bad','name':'test','base_url':'https://example.com/v1','model':'model'}]])
def test_corrupted_profile_rows_are_preserved_without_crashing_save(setup,rows):
    setup.path.write_text(json.dumps(rows),encoding='utf-8');before=setup.path.read_bytes()
    with pytest.raises(RuntimeError,match='повреждён'):setup.save('test','https://example.com/v1','model')
    assert setup.path.read_bytes()==before


@pytest.mark.parametrize('key',['value\nOTHER_ENV=bad','Bearer value','value\x00bad'])
def test_invalid_keys_cannot_inject_environment_entries(setup,key):
    with pytest.raises(ValueError,match='только API-ключ'):
        setup.save('test','https://example.com/v1','model',key=key)
    assert setup.list()==[] and c.get_user_api_key() is None


def test_stock_switch_waits_for_settings_transaction(setup):
    import threading,time
    started=threading.Event();release=threading.Event();stock_done=threading.Event();errors=[]
    config=c.default_config_path()
    def mutate():
        started.set();release.wait(timeout=3)
        c.apply_mode(config,'api','test-model','high')
    def settings():
        try:SettingsTransaction(c,config).execute(mutate,'test')
        except Exception as error:errors.append(error)
    def stock():
        try:c.enter_stock_mode(config);stock_done.set()
        except Exception as error:errors.append(error)
    transaction=threading.Thread(target=settings);transaction.start()
    assert started.wait(timeout=2)
    switch=threading.Thread(target=stock);switch.start()
    try:
        assert not stock_done.wait(timeout=.15)
    finally:
        release.set();transaction.join(timeout=4);switch.join(timeout=4)
    assert not errors and stock_done.is_set() and c.is_stock_mode()


def test_stock_is_rechecked_after_waiting_for_settings_lock(setup,monkeypatch):
    answers=iter([False,True])
    monkeypatch.setattr(c,'is_stock_mode',lambda:next(answers))
    with pytest.raises(RuntimeError,match='отключён'):
        SettingsTransaction(c,c.default_config_path()).execute(lambda:pytest.fail('Changed stock settings'),'test')


def test_checkpoint_finish_failure_restores_configuration(setup,monkeypatch):
    config=c.default_config_path();before=config.read_bytes()
    transaction=SettingsTransaction(c,config);save=transaction._save
    def fail_finish(payload):
        if payload['state']=='applied':raise OSError('test disk error')
        return save(payload)
    monkeypatch.setattr(transaction,'_save',fail_finish)
    with pytest.raises(OSError,match='test disk error'):
        transaction.execute(lambda:config.write_text('changed'),'test')
    assert config.read_bytes()==before
    assert transaction.list()[0]['state']=='rolled_back'


def test_partial_rollback_failure_keeps_applied_files_and_can_retry(setup,monkeypatch):
    import hybrid_recovery
    config=c.default_config_path();transaction=SettingsTransaction(c,config)
    result=transaction.execute(lambda:c.apply_mode(config,'api','test-model','high'),'test')
    applied={p:transaction.read(p) for p in transaction.paths()}
    write=hybrid_recovery.write_bytes;count=[0]
    def fail_once(core,path,data):
        count[0]+=1
        if count[0]==3:raise OSError('test locked file')
        return write(core,path,data)
    monkeypatch.setattr(hybrid_recovery,'write_bytes',fail_once)
    with pytest.raises(OSError,match='test locked file'):transaction.rollback(result['checkpoint_id'])
    assert all(transaction.read(p)==data for p,data in applied.items())
    transaction.rollback(result['checkpoint_id'])
