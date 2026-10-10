import time
import pytest
import codex_hybrid_control as c
import hybrid_accessibility as a
from hybrid_browser_control import BrowserControl,safe_url


@pytest.fixture
def home(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    c.save_computer_policy({'enabled':True,'allow_input':True,'allow_screenshot':True,'allow_launch':True})
    return tmp_path


def test_windows_element_is_invalidated_before_dispatch(home,monkeypatch):
    requests=[]
    def request(data,**kw):
        requests.append(data)
        if data.get('operation'):return {'ok':True,'verified':True}
        return {'ok':True,'pid':123,'started':'456','elements':[{'runtime_id':'1.2.3','name':'Edit','type':'ControlType.Edit','automation_id':'edit'}]}
    monkeypatch.setattr(a,'_request',request)
    controls=a.Accessibility(c)
    snapshot=controls.inspect(123)
    element_id=snapshot['elements'][0]['element_id']
    assert controls.act(element_id,'set_value','hello')['verified']
    with pytest.raises(RuntimeError,match='устарел'):controls.act(element_id,'set_value','again')
    assert len(requests)==2


def test_read_and_input_policies_are_enforced(home,monkeypatch):
    monkeypatch.setattr(a,'_request',lambda *args,**kw:pytest.fail('Bypassed policy'))
    c.save_computer_policy({'enabled':False})
    with pytest.raises(RuntimeError,match='отключён'):a.Accessibility(c).inspect(123)
    with pytest.raises(RuntimeError,match='отключён'):BrowserControl(c).start()
    c.save_computer_policy({'enabled':True,'allow_input':True,'control_mode':'mouse'})
    with pytest.raises(RuntimeError,match='мыши'):a.Accessibility(c).inspect(123)
    with pytest.raises(RuntimeError,match='мыши'):BrowserControl(c).tabs()


def test_browser_rejects_script_and_credential_urls():
    for url in ['javascript:alert(1)','file:///C:/secret.txt','https://user:pass@example.com']:
        with pytest.raises(ValueError):safe_url(url)
    assert safe_url('https://example.com')=='https://example.com'


def test_mcp_action_receipts_integrate_with_existing_cursor_tools(home,monkeypatch):
    monkeypatch.setattr(c,'is_stock_mode',lambda:False)
    calls=[]
    monkeypatch.setattr(c,'_mouse_click',lambda *args:calls.append(args) or (10,20))
    import json
    args={'action_id':'click1','x':10,'y':20,'coordinate_space':'desktop'}
    c._computer_call('computer_click',args)
    result=json.loads(c._computer_call('computer_click',args))
    assert len(calls)==1 and not result['replayed']
    status=json.loads(c._computer_call('computer_action_status',{'action_id':'click1'}))
    assert status['state']=='completed'


def test_legacy_calls_also_return_durable_receipts(home,monkeypatch):
    import json
    monkeypatch.setattr(c,'is_stock_mode',lambda:False)
    monkeypatch.setattr(c,'_mouse_click',lambda *args:(10,20))
    result=json.loads(c._computer_call('computer_click',{'x':10,'y':20,'coordinate_space':'desktop'}))
    assert result['action_id']
    latest=json.loads(c._computer_call('computer_action_status',{}))
    assert latest['actions'][0]['action_id']==result['action_id']


def test_full_repair_preserves_mouse_only_mode(home):
    c.save_computer_policy({'enabled':True,'control_mode':'mouse'})
    c.enable_full_api_computer_policy()
    assert c.computer_policy()['control_mode']=='mouse'


def test_browser_failure_does_not_leave_owned_process(home,monkeypatch):
    import hybrid_browser_control as b
    import sys
    stopped=[]
    class Process:
        pid=123
        def poll(self):return None
        def terminate(self):stopped.append('terminate')
        def wait(self,timeout):return 0
    monkeypatch.setattr(b,'browser_executable',lambda:sys.executable)
    monkeypatch.setattr(b.subprocess,'Popen',lambda *args,**kw:Process())
    ticks=iter([0,20])
    monkeypatch.setattr(b.time,'monotonic',lambda:next(ticks))
    with pytest.raises(RuntimeError,match='процесс остановлен'):b.BrowserControl(c).start()
    assert stopped==['terminate']


def test_browser_shell_profile_is_not_diagnostic_home(home,monkeypatch):
    import os
    from hybrid_browser_control import browser_environment
    if os.name!='nt':pytest.skip('Windows shell profile')
    monkeypatch.setenv('USERPROFILE',str(home))
    monkeypatch.setenv('HOME',str(home))
    env=browser_environment()
    assert env['USERPROFILE']!=str(home)
    assert os.environ['USERPROFILE']==str(home)


def test_browser_does_not_confirm_old_page_as_navigation_result(home,monkeypatch):
    import hybrid_browser_control as b
    browser=b.BrowserControl(c)
    class Socket:
        def close(self):pass
    monkeypatch.setattr(browser,'_socket',lambda tab:Socket())
    monkeypatch.setattr(browser,'_rpc',lambda *args:{})
    monkeypatch.setattr(browser,'_evaluate',lambda *args:{'url':'https://old.example/','ready':'complete'})
    ticks=iter([0,1,9])
    monkeypatch.setattr(b.time,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(b.time,'sleep',lambda *args:None)
    assert not browser.navigate('tab','https://target.example/')['verified']
