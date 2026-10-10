import os
import pytest
import hybrid_proxy as proxy


def test_worker_environment_preserves_proxy_and_all_previous_bypasses(monkeypatch):
    monkeypatch.setattr(proxy,'read_user_bypass',lambda:'corp.example,localhost')
    original={'HTTP_PROXY':'http://proxy.example:8080','AG_LS_PROXY':'http://127.0.0.1:9000',
              'NO_PROXY':'existing.example','no_proxy':'other.example','CUSTOM':'keep'}
    result=proxy.child_environment(original)
    assert result['HTTP_PROXY']==original['HTTP_PROXY']
    assert result['AG_LS_PROXY']==original['AG_LS_PROXY'] and result['CUSTOM']=='keep'
    assert set(result['NO_PROXY'].split(','))=={'existing.example','other.example','corp.example',*proxy.LOOPBACK_HOSTS}
    assert result['NO_PROXY']==result['no_proxy']
    assert original['NO_PROXY']=='existing.example'


def test_loopback_bypass_is_idempotent_and_keeps_existing_wildcard():
    value=proxy.merge_bypass('*.example,*',' LOCALHOST ')
    assert proxy.merge_bypass(value)==value and '*' in value.split(',')


@pytest.mark.parametrize('proxy_name',['HTTP_PROXY','https_proxy','ALL_PROXY','AG_LS_PROXY'])
def test_diagnostics_detects_stale_process_without_exposing_proxy_credentials(monkeypatch,proxy_name):
    monkeypatch.setattr(proxy,'read_user_bypass',lambda:'127.0.0.1,localhost,::1')
    result=proxy.loopback_status({proxy_name:'http://private-user:private-password@proxy.example:9'})
    assert not result['ok'] and result['restart_required']
    assert result['missing_hosts']==list(proxy.LOOPBACK_HOSTS)
    assert 'private' not in str(result) and 'proxy.example' not in str(result)


def test_absent_proxy_or_wildcard_bypass_needs_no_repair():
    assert proxy.loopback_status({})['ok']
    assert proxy.loopback_status({'HTTP_PROXY':'http://proxy.example','NO_PROXY':'*'})['ok']


def test_conflicting_bypass_casing_cannot_produce_false_healthy_status():
    result=proxy.loopback_status({'HTTP_PROXY':'http://proxy.example',
                                 'NO_PROXY':','.join(proxy.LOOPBACK_HOSTS),'no_proxy':''})
    assert not result['ok'] and result['missing_hosts']==list(proxy.LOOPBACK_HOSTS)


def test_windows_system_proxy_is_detected_without_environment_proxy(monkeypatch):
    monkeypatch.setattr(proxy,'read_system_proxy_enabled',lambda:True)
    result=proxy.loopback_status({})
    assert not result['ok'] and result['system_proxy_present']
    assert proxy.loopback_status({'NO_PROXY':','.join(proxy.LOOPBACK_HOSTS)})['ok']


def test_proxy_bypass_warns_when_registry_alone_cannot_fix_inherited_environment(monkeypatch):
    monkeypatch.setattr(proxy,'read_user_bypass',lambda:'')
    result=proxy.loopback_status({'HTTP_PROXY':'http://proxy.example','NO_PROXY':'localhost'})
    assert not result['ok'] and not result['restart_required']
    assert result['missing_hosts']==['127.0.0.1','::1']


@pytest.mark.skipif(os.name!='nt',reason='Windows user environment')
def test_repair_persists_bypass_and_broadcasts_once(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv('NO_PROXY','existing.example')
    saved=['corp.example'];events=[]
    monkeypatch.setattr(proxy,'read_user_bypass',lambda:saved[0])
    monkeypatch.setattr(proxy,'write_user_bypass',lambda value:saved.__setitem__(0,value))
    core=SimpleNamespace(_broadcast_environment_change=lambda:events.append('changed'))
    proxy.repair_loopback_proxy(core)
    assert set(saved[0].split(','))=={'existing.example','corp.example',*proxy.LOOPBACK_HOSTS}
    assert os.environ['NO_PROXY']==saved[0]
    proxy.repair_loopback_proxy(core)
    assert events==['changed'] if os.name=='nt' else events==[]
