import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace
import pytest
from hybrid_api_guard import server, ensure_started as start_guard


@pytest.mark.parametrize('path,origin,stock,status',[
    ('/wrong-access/v1/responses',None,False,403),
    ('/local-test-secret/v1/responses','https://example.com',False,403),
    ('/local-test-secret/v1/unexpected',None,False,403),
    ('/local-test-secret/v1/responses',None,True,503),
])
def test_rejected_local_requests_never_reach_provider(tmp_path,path,origin,stock,status):
    calls=[]
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            calls.append(self.path);self.send_response(500);self.end_headers()
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    core=SimpleNamespace(is_stock_mode=lambda:stock)
    gateway=server(core,{'port':0,'access':'local-test-secret'},
                   upstream=f'http://127.0.0.1:{upstream.server_port}/v1',timeout=1)
    for value in [gateway,upstream]:threading.Thread(target=value.serve_forever,daemon=True).start()
    connection=http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=2)
    try:
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        connection.request('POST',path,'{}',headers)
        response=connection.getresponse();response.read()
        assert response.status==status and calls==[]
    finally:
        connection.close()
        for value in [gateway,upstream]:value.shutdown();value.server_close()


def test_health_does_not_report_a_closed_port_as_healthy():
    import socket
    from hybrid_api_guard import health_info
    with socket.socket() as reserved:
        # A bound socket that never listens cannot be reused by another service.
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        started=time.monotonic()
        assert health_info({'port':port,'access':'test-access'})=={}
        assert time.monotonic()-started<1.5


def test_tool_cycle_uses_results_and_arguments_without_call_ids():
    from hybrid_api_guard import repeated_tool_call
    history=[]
    tool={'type':'function_call','name':'check','arguments':'{"x":1}'}
    for number in range(4):
        history += [{**tool,'call_id':str(number)},
                    {'type':'function_call_output','call_id':str(number),'output':'unchanged'}]
    assert repeated_tool_call({'input':history},tool)
    assert not repeated_tool_call({'input':history},{**tool,'arguments':'{"x":2}'})
    assert not repeated_tool_call({'input':history+ [{'role':'user','content':'Check again'}]},tool)
    history[-1]['output']='changed'
    assert not repeated_tool_call({'input':history},tool)


@pytest.mark.parametrize('launch_failure',[False,True])
def test_old_daemon_update_rotates_endpoint_and_rolls_back_failure(tmp_path,monkeypatch,launch_failure):
    import hybrid_api_guard as guard
    import sys
    original={'enabled':True,'port':12345,'access':'old-test'}
    path=tmp_path/'api-guard.json';path.write_text(json.dumps(original))
    core=SimpleNamespace(is_stock_mode=lambda:False,control_dir=lambda:tmp_path,read_json=lambda p,d:json.loads(p.read_text()),
        write_json_atomic=lambda p,v:p.write_text(json.dumps(v)),_home=lambda:tmp_path,codex_dir=lambda:tmp_path,
        _stdio_python_executable=lambda:sys.executable)
    monkeypatch.setattr(guard,'health_info',lambda s:{'version':1})
    monkeypatch.setattr(guard,'healthy',lambda s:True)
    def launch(*args,**kwargs):
        if launch_failure:raise OSError('test launch failure')
    monkeypatch.setattr(guard.subprocess,'Popen',launch)
    if launch_failure:
        with pytest.raises(OSError):start_guard(core)
        assert json.loads(path.read_text())==original
    else:
        start_guard(core)
        updated=json.loads(path.read_text())
        assert updated['port']!=original['port'] and updated['access']!=original['access']


@pytest.mark.parametrize('value',['{broken','[]','null','{"enabled":true,"port":-1,"access":"invalid"}','{"enabled":"yes"}'])
def test_corrupted_guard_settings_do_not_bypass_and_are_repairable(tmp_path,monkeypatch,value):
    import codex_hybrid_control as core
    import hybrid_api_guard as guard
    core.control_dir().mkdir(parents=True,exist_ok=True)
    path=core.control_dir()/'api-guard.json';path.write_text(value,encoding='utf-8')
    with pytest.raises(RuntimeError,match='повреждены'):guard.endpoint(core,'https://example.com/v1')
    guard.install(core)
    assert guard.load_settings(core)['enabled'] is True
    assert next(path.parent.glob('api-guard.invalid-*.json')).read_text(encoding='utf-8')==value


def test_failed_guard_repair_restores_broken_bytes(tmp_path,monkeypatch):
    import codex_hybrid_control as core
    import hybrid_api_guard as guard
    core.control_dir().mkdir(parents=True,exist_ok=True)
    path=core.control_dir()/'api-guard.json';path.write_bytes(b'{original broken settings')
    def fail(core):raise RuntimeError('test failure')
    monkeypatch.setattr(guard,'ensure_started',fail)
    with pytest.raises(RuntimeError,match='test failure'):guard.install(core)
    assert path.read_bytes()==b'{original broken settings'


def test_disabled_guard_is_enabled_by_repair(tmp_path):
    import codex_hybrid_control as core
    from hybrid_api_guard import install,load_settings
    core.control_dir().mkdir(parents=True,exist_ok=True)
    (core.control_dir()/'api-guard.json').write_text('{"enabled":false}')
    install(core)
    assert load_settings(core)['enabled']


def test_suffix_detector_matches_exhaustive_reference():
    import random
    from hybrid_api_guard import repeated_suffix
    random_source=random.Random(2)
    cases=[''.join(random_source.choices('abcdefgh ',k=length)) for length in range(20,3000,29)]
    cases += ['prefix '+(' '.join(str(n) for n in range(period))+' ')*4 for period in range(15,260,7)]
    for text in cases:
        old=any(text[-n:]*4==text[-n*4:] for n in range(24,min(1000,len(text)//4)+1))
        assert repeated_suffix(text)==old


@pytest.mark.parametrize('newline',[b'\n',b'\r\n',b'\r'])
def test_stream_accepts_separators_split_at_every_byte(newline):
    from hybrid_api_guard import read_stream
    data=b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}'+newline*2
    class Fragmented:
        def __init__(self):self.position=0
        def read1(self,size):
            chunk=data[self.position:self.position+1];self.position+=1;return chunk
    assert b'response.completed' in read_stream(Fragmented(),time.monotonic()+3)


def test_slow_request_body_is_bounded_before_provider_connection(tmp_path):
    import socket
    core=SimpleNamespace(is_stock_mode=lambda:False,control_dir=lambda:tmp_path,now_iso=lambda:'now',
                         write_json_atomic=lambda p,v:p.write_text(json.dumps(v)))
    gateway=server(core,{'port':0,'access':'test-secret'},upstream='http://127.0.0.1:1/v1',timeout=.2,idle=.1)
    threading.Thread(target=gateway.serve_forever,daemon=True).start()
    connection=socket.create_connection(('127.0.0.1',gateway.server_port));connection.settimeout(2)
    start=time.monotonic()
    try:
        connection.sendall(b'POST /test-secret/v1/responses HTTP/1.1\r\nHost: localhost\r\nContent-Length: 100\r\n\r\n{')
        response=b''
        while True:
            chunk=connection.recv(4096)
            if not chunk:break
            response+=chunk
        assert b'502' in response and time.monotonic()-start<1.5
        assert json.loads((tmp_path/'api-guard-last.json').read_text())['status']=='deadline'
    finally:connection.close();gateway.shutdown();gateway.server_close()


def test_client_cancel_does_not_consume_provider_retry_budget(tmp_path):
    import socket
    calls=[];accepted=threading.Event();release=threading.Event()
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            calls.append(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            if len(calls)==1:
                self.wfile.write(b'data: {"type":"response.created"}\n\n');self.wfile.flush()
                accepted.set();release.wait(timeout=2)
            else:self.wfile.write(b'data: {}\n\n')
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    threading.Thread(target=upstream.serve_forever,daemon=True).start()
    core=SimpleNamespace(is_stock_mode=lambda:False,control_dir=lambda:tmp_path,now_iso=lambda:'now',
                         write_json_atomic=lambda p,v:p.write_text(json.dumps(v)))
    gateway=server(core,{'port':0,'access':'test-secret'},upstream=f'http://127.0.0.1:{upstream.server_port}/v1',timeout=.8,idle=.4)
    threading.Thread(target=gateway.serve_forever,daemon=True).start()
    connection=socket.create_connection(('127.0.0.1',gateway.server_port))
    try:
        body=b'{"stream":true}'
        connection.sendall(b'POST /test-secret/v1/responses HTTP/1.1\r\nHost: localhost\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
        assert accepted.wait(timeout=2)
        connection.close()
        until=time.monotonic()+2
        while time.monotonic()<until:
            try:
                if json.loads((tmp_path/'api-guard-last.json').read_text())['status']=='client_cancelled':break
            except (OSError,ValueError):pass
            time.sleep(.01)
        else:pytest.fail('Cancellation not recorded')
        for _ in range(3):
            client=http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=2)
            try:
                client.request('POST','/test-secret/v1/responses',body)
                result=client.getresponse();assert result.status==502;result.read()
            finally:client.close()
        assert len(calls)==3
    finally:
        connection.close();release.set();gateway.shutdown();gateway.server_close();upstream.shutdown();upstream.server_close()


@pytest.mark.parametrize('case',['valid','heartbeat','partial_line','repeat','truncated','tool_then_hang','headers','circuit','invalid_event','invalid_tool','json_incomplete','terminal_tail'])
def test_gateway_bounded_no_partial_tools(tmp_path,case):
    calls=[]
    complete={'type':'response.completed','response':{'status':'completed','output':[]}}
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            calls.append(self.rfile.read(int(self.headers['Content-Length'])))
            if case=='headers':time.sleep(.8)
            self.send_response(200);self.send_header('Content-Type','application/json' if case=='json_incomplete' else 'text/event-stream');self.end_headers()
            try:
                if case=='json_incomplete':self.wfile.write(b'{"status":"incomplete","output":[]}');return
                if case=='invalid_event':self.wfile.write(b'data: []\n\n');return
                if case=='invalid_tool':
                    invalid={'type':'response.completed','response':{'status':'completed','output':[{'type':'function_call','name':'do_something','call_id':'c','arguments':'{"broken"'}]}}
                    self.wfile.write(('data: '+json.dumps(invalid)+'\n\n').encode());return
                if case=='terminal_tail':
                    self.wfile.write(('data: '+json.dumps(complete)+'\n\ndata: {"type":"response.output_item.done","item":{"type":"function_call","name":"do_something"}}\n\n').encode());return
                if case=='valid':
                    self.wfile.write(('data: '+json.dumps(complete)+'\n\n').encode());return
                if case in {'truncated','circuit'}:self.wfile.write(b'data: {}\n\n');return
                if case=='repeat':
                    for _ in range(20):
                        self.wfile.write(('data: '+json.dumps({'type':'response.output_text.delta','delta':'Checking the same thing again and again. '})+'\n\n').encode());self.wfile.flush()
                    return
                if case=='tool_then_hang':self.wfile.write(b'data: {"type":"response.output_item.done","item":{"type":"function_call","name":"do_something"}}\n\n');self.wfile.flush()
                for _ in range(30):
                    self.wfile.write(b'x' if case=='partial_line' else b': keepalive\n\n');self.wfile.flush();time.sleep(.04)
            except OSError:pass
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    threading.Thread(target=upstream.serve_forever,daemon=True).start()
    core=SimpleNamespace(is_stock_mode=lambda:False,control_dir=lambda:tmp_path,now_iso=lambda:'now',
                         write_json_atomic=lambda p,v:p.write_text(json.dumps(v)))
    gateway=server(core,{'port':0,'access':'test-secret'},upstream=f'http://127.0.0.1:{upstream.server_port}/v1',timeout=.5,idle=.2)
    threading.Thread(target=gateway.serve_forever,daemon=True).start()
    connection=http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=3)
    started=time.monotonic()
    try:
        connection.request('POST','/test-secret/v1/responses',json.dumps({'model':'fake','stream':True}),{'Authorization':'Bearer fake'})
        response=connection.getresponse();body=response.read()
        assert time.monotonic()-started<2
        assert response.status==(200 if case in {'valid','terminal_tail'} else 502),body
        assert b'do_something' not in body
        assert len(calls)==1
        until=time.monotonic()+1
        while not (tmp_path/'api-guard-last.json').exists() and time.monotonic()<until:time.sleep(.01)
        assert b'fake' not in (tmp_path/'api-guard-last.json').read_bytes()
        if case=='circuit':
            for _ in range(3):
                connection.close()
                connection=http.client.HTTPConnection('127.0.0.1',gateway.server_port,timeout=3)
                connection.request('POST','/test-secret/v1/responses',json.dumps({'model':'fake','stream':True}),{'Authorization':'Bearer fake'})
                rejected=connection.getresponse();rejected.read()
                assert rejected.status==502
            assert len(calls)==2
    finally:
        connection.close();gateway.shutdown();gateway.server_close();upstream.shutdown();upstream.server_close()
