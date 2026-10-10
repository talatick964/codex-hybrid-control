import json
import sys
from pathlib import Path
from hybrid_bridge_host import BridgeHost


def test_blocked_write_obeys_request_deadline(tmp_path):
    import time
    child=tmp_path/'never_read.py';child.write_text('import time;time.sleep(30)')
    host=BridgeHost([sys.executable,str(child)],timeout=.2)
    try:
        begin=time.monotonic()
        assert 'error' in host.handle({'jsonrpc':'2.0','id':1,'method':'large','params':{'text':'x'*2000000}})
        assert time.monotonic()-begin<3
    finally:host.close()


def test_invalid_child_json_value_recovers(tmp_path):
    child=tmp_path/'bad_protocol.py'
    child.write_text('import sys\nfor line in sys.stdin: print("[]",flush=True)')
    host=BridgeHost([sys.executable,str(child)],timeout=.2)
    try:
        assert 'error' in host.handle({'jsonrpc':'2.0','id':1,'method':'initialize'})
    finally:host.close()


def test_owned_transport_handle_closes_wrapper_child_without_killing_launched_app(tmp_path):
    import os,pytest,time
    if os.name!='nt':pytest.skip('Windows process handles')
    child=tmp_path/'transport.py';app_pid=tmp_path/'app.pid'
    child.write_text('''import sys,json,subprocess,time
sys.path.insert(0,sys.argv[1])
from pathlib import Path
from hybrid_bridge_host import announce_transport
announce_transport()
app=subprocess.Popen([sys.executable,'-c','import time;time.sleep(4)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
Path(sys.argv[2]).write_text(str(app.pid))
for line in sys.stdin:
 row=json.loads(line)
 if row['method']=='hang':time.sleep(30)
 print(json.dumps({'jsonrpc':'2.0','id':row['id'],'result':{}}),flush=True)
''')
    wrapper=tmp_path/'wrapper.py'
    wrapper.write_text('import subprocess,sys\nraise SystemExit(subprocess.call(sys.argv[1:]))')
    host=BridgeHost([sys.executable,str(wrapper),sys.executable,str(child),str(Path(__file__).resolve().parents[1]),str(app_pid)],timeout=.5)
    handle=None
    try:
        assert 'result' in host.handle({'jsonrpc':'2.0','id':1,'method':'initialize'})
        assert host.transport_handle is not None
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_uint];kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x100001,False,int(app_pid.read_text()))
        assert handle
        assert 'error' in host.handle({'jsonrpc':'2.0','id':2,'method':'hang'})
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint]
        assert kernel.WaitForSingleObject(handle,0)==258
    finally:
        host.close()
        if handle:
            kernel.TerminateProcess.argtypes=[ctypes.c_void_p,ctypes.c_uint];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            kernel.TerminateProcess(handle,1);kernel.CloseHandle(handle)


def test_gateway_startup_failure_does_not_disable_mcp(tmp_path,monkeypatch):
    import io
    from types import SimpleNamespace
    import hybrid_api_guard
    from hybrid_bridge_host import run_host
    child=tmp_path/'stdio.py'
    child.write_text('import sys,json\nfor line in sys.stdin:\n row=json.loads(line)\n if "id" in row:print(json.dumps({"jsonrpc":"2.0","id":row["id"],"result":{}}),flush=True)')
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    core=SimpleNamespace(__file__=str(child),_configure_mcp_stdio=lambda:None,control_dir=lambda:tmp_path,
                         now_iso=lambda:'now',write_json_atomic=write)
    def fail(core):raise RuntimeError('test gateway startup failure')
    monkeypatch.setattr(hybrid_api_guard,'ensure_started',fail)
    output=io.StringIO()
    monkeypatch.setattr(sys,'stdin',io.StringIO('{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'))
    monkeypatch.setattr(sys,'stdout',output)
    run_host(core,'computer')
    assert json.loads(output.getvalue())['result']=={}
    assert json.loads((tmp_path/'api-guard-last.json').read_text())['status']=='startup_failure'


def test_status_checks_only_recent_bridge_receipts_and_tolerates_bad_rows(tmp_path):
    from types import SimpleNamespace
    from hybrid_bridge_host import bridge_states
    folder=tmp_path/'bridges';folder.mkdir();queries=[]
    for number in range(100):
        (folder/f'worker-{number}.json').write_text(json.dumps({'host_pid':number+1,'updated_at':number}))
    core=SimpleNamespace(control_dir=lambda:tmp_path,read_json=lambda p,d:json.loads(p.read_text()),
                         pid_alive=lambda pid:queries.append(pid) or False)
    rows=bridge_states(core)
    assert len(rows)==16 and len(queries)==16
    (folder/'worker-bad.json').write_text('{"host_pid":"broken","updated_at":{}}')
    assert len(bridge_states(core))<=16


def test_status_write_failure_does_not_lose_tool_reply(tmp_path):
    child=tmp_path/'reply.py'
    child.write_text('import sys,json\nfor line in sys.stdin:\n row=json.loads(line)\n if "id" in row:print(json.dumps({"jsonrpc":"2.0","id":row["id"],"result":{}}),flush=True)')
    def fail_status(row):raise OSError('test full disk')
    host=BridgeHost([sys.executable,str(child)],timeout=.5,status_callback=fail_status)
    try:
        assert 'result' in host.handle({'jsonrpc':'2.0','id':1,'method':'initialize'})
        assert 'result' in host.heartbeat()
        assert host.generation==1 and host.status_error=='OSError'
    finally:host.close()


def test_hung_child_is_replaced_without_replaying_request(tmp_path):
    marker=tmp_path/'calls.jsonl'
    child=tmp_path/'bridge.py'
    child.write_text('''import json,sys,time
from pathlib import Path
for line in sys.stdin:
 row=json.loads(line)
 with Path(sys.argv[1]).open('a') as f:f.write(row['method']+'\\n')
 if row['method']=='hang':time.sleep(30)
 if 'id' in row:print(json.dumps({'jsonrpc':'2.0','id':row['id'],'result':{}}),flush=True)
''',encoding='utf-8')
    states=[]
    host=BridgeHost([sys.executable,str(child),str(marker)],timeout=.3,status_callback=states.append)
    try:
        assert 'result' in host.handle({'jsonrpc':'2.0','id':1,'method':'initialize'})
        assert 'error' in host.handle({'jsonrpc':'2.0','id':2,'method':'hang'})
        assert 'result' in host.heartbeat()
        assert host.generation==2
        lines=marker.read_text().splitlines()
        assert lines.count('hang')==1 and lines.count('initialize')==2
        assert any(row['state']=='recovering' for row in states)
    finally:host.close()


def test_receipt_survives_lost_reply_and_actual_bridge_replacement(tmp_path):
    child=tmp_path/'receipt_bridge.py'
    child.write_text('''import json,sys,time
sys.path.insert(0,sys.argv[2])
from pathlib import Path
import codex_hybrid_control as core
from hybrid_actions import ActionJournal
root=Path(sys.argv[1]);core._home=lambda:root
counter=root/'executions.txt';lost=root/'reply-lost'
for line in sys.stdin:
 row=json.loads(line)
 if 'id' not in row:continue
 result={}
 if row['method']=='tools/call':
  def mutate():
   count=int(counter.read_text()) if counter.exists() else 0
   counter.write_text(str(count+1));return {'ok':True}
  result=ActionJournal(core).execute('stable','test_action',{},mutate)
  if not lost.exists():lost.write_text('lost');time.sleep(30)
 print(json.dumps({'jsonrpc':'2.0','id':row['id'],'result':result}),flush=True)
''',encoding='utf-8')
    host=BridgeHost([sys.executable,str(child),str(tmp_path),str(Path(__file__).resolve().parents[1])],timeout=1)
    try:
        assert 'result' in host.handle({'jsonrpc':'2.0','id':1,'method':'initialize'})
        assert 'error' in host.handle({'jsonrpc':'2.0','id':2,'method':'tools/call'})
        result=host.handle({'jsonrpc':'2.0','id':3,'method':'tools/call'})
        assert result['result']['state']=='completed' and not result['result']['replayed']
        assert (tmp_path/'executions.txt').read_text()=='1' and host.generation==2
    finally:host.close()
