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
