import json
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
import codex_hybrid_control as c
import hybrid_diagnostics as d


def text_response(text):
    return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}


def test_rate_limit_is_clear_and_other_paid_probes_are_skipped(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    calls=[]
    def request(base,key,path,body=None,**kw):
        calls.append(path)
        if path=='/models':return {'data':[{'id':'test-model'}]}
        raise RuntimeError('HTTP 429: quota exhausted secret-test')
    monkeypatch.setattr(d,'_http',request)
    result=d.api_diagnostics(c,'https://example.com/v1','test-model','secret-test')
    assert not result['ok'] and calls==['/models','/responses']
    assert result['steps'][1]['status']=='error'
    assert [s['status'] for s in result['steps'][-2:]]==['skipped','skipped']
    assert 'secret-test' not in json.dumps(result)


def test_all_capabilities_require_actual_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    monkeypatch.setattr(d.uuid,'uuid4',lambda:type('UUID',(),{'hex':'12345678abcdef00'})())
    def request(base,key,path,body=None,stream=False,**kw):
        if path=='/models':return {'data':[{'id':'model'}]}
        if stream:return [{'type':'response.output_text.delta','delta':'12345678'},
                          {'type':'response.completed','response':text_response('12345678')}]
        if body.get('tools'):
            return {'status':'completed','output':[{'type':'function_call','call_id':'call1','name':'diagnostic_echo','arguments':'{"nonce":"12345678"}'}]}
        if isinstance(body.get('input'),list) and body['input'][-1].get('type')=='function_call_output':
            return text_response('12345678')
        assert body['input'][0]['content'][1]['image_url'].startswith('data:image/png;base64,')
        return text_response('5660')
    monkeypatch.setattr(d,'_http',request)
    result=d.api_diagnostics(c,'https://example.com/v1','model','secret')
    assert result['ok'] and all(step['status']=='ok' for step in result['steps'])


def test_stream_without_deltas_is_not_claimed_as_supported(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    monkeypatch.setattr(d,'_http',lambda *args,**kw: [] if kw.get('stream') else {'data':[{'id':'model'}]})
    result=d.api_diagnostics(c,'https://example.com/v1','model','secret')
    assert not result['ok'] and result['steps'][1]['status']=='error'


def test_export_omits_raw_logs_headers_environment_and_arguments(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    monkeypatch.setattr(c,'get_user_api_key',lambda:'active-secret')
    c.bootstrap_codex_files()
    config=c.default_config_path()
    with config.open('a',encoding='utf-8') as file:
        file.write('\n[private]\ncustom = "unrecognized-secret"\n')
        file.write('\n[mcp_servers.other]\ncommand = "helper"\nargs = ["--key", "unknown-key"]\nenv = { CUSTOM = "another-secret" }\n')
    (c.logs_dir()/'provider.log').write_text('Bearer active-secret unknown-log-secret HTTP 429 timeout')
    report=tmp_path/'report.json'
    d.export_report(c,config,report)
    text=report.read_text(encoding='utf-8')
    for secret in ['active-secret','unrecognized-secret','unknown-key','another-secret','unknown-log-secret']:
        assert secret not in text
    data=json.loads(text)
    assert data['log_summaries'][0]['http_statuses']==['429']


def test_redaction_covers_headers_query_and_known_values():
    text=d.redact('Bearer xyz https://host/path?token=abc&key=def\nFUNPAY_API_KEY=value\nprivate-value',('private-value',))
    assert not any(secret in text for secret in ['xyz','abc','def','value','private-value'])


def test_sse_deadline_stops_a_slow_incomplete_line():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            try:
                for _ in range(80):self.wfile.write(b'x');self.wfile.flush();time.sleep(.03)
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        start=time.monotonic()
        with pytest.raises((TimeoutError,OSError)):
            d._http(f'http://127.0.0.1:{server.server_port}','fake','/slow',stream=True,timeout=.3)
        assert time.monotonic()-start<1.5
    finally:server.shutdown();server.server_close()


def test_redirect_does_not_forward_bearer_token():
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            calls.append(self.path)
            self.send_response(302);self.send_header('Location','/target');self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with pytest.raises(RuntimeError,match='перенаправление'):
            d._http(f'http://127.0.0.1:{server.server_port}','secret','/redirect')
        assert calls==['/redirect']
    finally:server.shutdown();server.server_close()
