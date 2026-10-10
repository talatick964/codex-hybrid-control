"""Exercise real Codex routing. Model requests use local fixtures and fake keys."""
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
import codex_hybrid_control as core
from hybrid_proxy import child_environment


@pytest.mark.skipif(not shutil.which(core.codex_command()),reason='Codex CLI not installed')
@pytest.mark.parametrize('proxy_names',[('HTTP_PROXY',),('http_proxy',),('ALL_PROXY',),('AG_LS_PROXY',),('HTTP_PROXY','AG_LS_PROXY')])
def test_real_codex_reaches_local_gateway_after_proxy_repair(tmp_path,proxy_names):
    local_calls=[];proxy_calls=[]
    def handler(calls,status,marker):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                calls.append(self.path)
                data=json.dumps({'error':{'message':marker}}).encode()
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
        return Handler
    local=ThreadingHTTPServer(('127.0.0.1',0),handler(local_calls,400,'LOCAL_ONLY_TEST'))
    proxy=ThreadingHTTPServer(('127.0.0.1',0),handler(proxy_calls,403,'PROXY_REJECTED'))
    for server in [local,proxy]:threading.Thread(target=server.serve_forever,daemon=True).start()
    home=tmp_path/'codex';home.mkdir()
    route='/local-only-access/v1'
    base=f'http://127.0.0.1:{local.server_port}'+route
    (home/'config.toml').write_text(
        'model="local-test"\nmodel_provider="local_test"\n[model_providers.local_test]\n'
        'name="Local test"\nbase_url='+json.dumps(base)+'\nwire_api="responses"\n'
        'env_key="LOCAL_TEST_API_KEY"\nrequest_max_retries=0\nstream_max_retries=0\n',encoding='utf-8')
    # Remove inherited proxy credentials and use a fake model key.
    env={key:value for key,value in os.environ.items() if 'proxy' not in key.lower()}
    env.update(CODEX_HOME=str(home),USERPROFILE=str(tmp_path),HOME=str(tmp_path),
               LOCAL_TEST_API_KEY='local-test-placeholder')
    for proxy_name in proxy_names:env[proxy_name]=f'http://127.0.0.1:{proxy.server_port}'
    command=[core.codex_command(),'exec','--json','--skip-git-repo-check','--sandbox','read-only',
             '-C',str(tmp_path),'Reply OK only; do not call tools.']
    try:
        blocked=core.run_bounded_process(command,env=env,timeout=15,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        assert blocked.returncode!=0
        if 'HTTP_PROXY' in proxy_names or 'http_proxy' in proxy_names:
            assert proxy_calls and not local_calls,'The baseline must reproduce proxy interception'
        else:
            # Some CLI versions use the Windows system proxy instead of these
            # variables. The baseline can be rejected before our trap sees it.
            output=blocked.stderr+blocked.stdout
            assert (bool(proxy_calls)!=bool(local_calls)) or ('403' in output and not local_calls)
        if proxy_calls:assert 'PROXY_REJECTED' in blocked.stderr+blocked.stdout
        if local_calls:assert 'LOCAL_ONLY_TEST' in blocked.stderr+blocked.stdout
        attempts=len(proxy_calls)
        local_calls.clear()
        fixed=core.run_bounded_process(command,env=child_environment(env),timeout=15,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        # A deliberate 400 ensures no model, tool, or paid request was executed.
        assert fixed.returncode!=0 and 'LOCAL_ONLY_TEST' in fixed.stderr+fixed.stdout
        assert local_calls==[route+'/responses']
        assert len(proxy_calls)==attempts
    finally:
        for server in [local,proxy]:server.shutdown();server.server_close()
