"""Real Codex with a localhost fake provider: no API keys or paid requests."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
import codex_hybrid_control as c
from hybrid_catalog import catalog
from hybrid_stop_guard import install


@pytest.mark.skipif(not shutil.which(c.codex_command()),reason='Codex CLI not installed')
@pytest.mark.parametrize('scenario',['recovered','always_broken','after_tool','empty_after_tool','leading_tag','gateway_retry','gateway_failed','gateway_tool','promise','progress_chain','no_progress_chain','gateway_cycle'])
def test_native_stop_continuation_is_bounded(tmp_path,monkeypatch,scenario):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    home=c.codex_dir();home.mkdir()
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            broken_at = 2 if scenario.endswith('after_tool') else 1
            answer='Проверяю:</think></arg_value>' if scenario=='always_broken' or len(requests)==broken_at else 'Готово. Проверка завершена.'
            if scenario=='promise' and len(requests)==1:answer='Запускаю новую mission:'
            if scenario=='leading_tag' and len(requests)==1:answer='</think>Продолжаю. Перезапускаю сервер:'
            if scenario=='empty_after_tool' and len(requests)==2:answer=''
            if scenario.endswith('_chain') and len(requests) in {1,3,5}:answer='Запускаю следующую проверку:'
            item={'id':'msg_test','type':'message','role':'assistant','status':'completed','phase':'final_answer',
                  'content':[{'type':'output_text','text':answer,'annotations':[]}]}
            response={'id':'resp_test','object':'response','status':'completed','output':[item],
                      'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}}
            events=[{'type':'response.created','response':{**response,'status':'in_progress','output':[]}},
                    {'type':'response.output_item.added','output_index':0,'item':{**item,'content':[],'status':'in_progress'}},
                    {'type':'response.output_text.delta','item_id':'msg_test','output_index':0,'content_index':0,'delta':answer},
                    {'type':'response.output_item.done','output_index':0,'item':item},
                    {'type':'response.completed','response':response}]
            if scenario.endswith('after_tool') and len(requests)==1:
                tool={'id':'fc_test','type':'function_call','call_id':'call_test','name':'observe','namespace':'mcp__counter',
                      'arguments':'{}'}
                events=[{'type':'response.output_item.done','output_index':0,'item':tool},
                        {'type':'response.completed','response':{**response,'output':[tool]}}]
            if scenario.endswith('_chain') and len(requests) in {2,4}:
                tool={'id':'fc_test','type':'function_call','call_id':'call_'+str(len(requests)),
                      'name':'observe','namespace':'mcp__counter','arguments':'{}'}
                events=[{'type':'response.output_item.done','output_index':0,'item':tool},
                        {'type':'response.completed','response':{**response,'output':[tool]}}]
            if scenario.startswith('gateway') and scenario!='gateway_cycle' and (len(requests)==1 or scenario=='gateway_failed'):
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                try:
                    if scenario=='gateway_tool':
                        self.wfile.write(b'data: {\"type\":\"response.output_item.done\",\"item\":{\"type\":\"function_call\",\"name\":\"observe\",\"namespace\":\"mcp__counter\",\"arguments\":\"{}\",\"call_id\":\"pending\"}}\n\n');self.wfile.flush()
                    for _ in range(30):self.wfile.write(b': ping\n\n');self.wfile.flush();time.sleep(.03)
                except OSError:pass
                return
            if scenario=='gateway_tool' and len(requests)==2:
                tool={'id':'fc_test','type':'function_call','call_id':'call_test','name':'observe','namespace':'mcp__counter','arguments':'{}'}
                events=[{'type':'response.output_item.done','output_index':0,'item':tool},{'type':'response.completed','response':{**response,'output':[tool]}}]
            if scenario=='gateway_cycle':
                tool={'id':'fc_test','type':'function_call','call_id':'cycle_'+str(len(requests)),'name':'observe','namespace':'mcp__counter','arguments':'{}'}
                events=[{'type':'response.output_item.done','output_index':0,'item':tool},{'type':'response.completed','response':{**response,'output':[tool]}}]
            body=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    gateway=None
    api_base=f'http://127.0.0.1:{server.server_port}/v1'
    if scenario.startswith('gateway'):
        from hybrid_api_guard import server as guard_server
        gateway=guard_server(c,{'port':0,'access':'local-test'},upstream=api_base,timeout=.3,idle=.2)
        threading.Thread(target=gateway.serve_forever,daemon=True).start()
        api_base=f'http://127.0.0.1:{gateway.server_port}/local-test/v1'
    models=home/'models.json';models.write_text(json.dumps(catalog(['test-model'])),encoding='utf-8')
    config=home/'config.toml'
    config.write_text('model="test-model"\nmodel_provider="funpay"\nmodel_catalog_json='+c._toml_string(str(models))+f'\n[model_providers.funpay]\nname="Test"\nbase_url="{api_base}"\nwire_api="responses"\nrequires_openai_auth=false\nrequest_max_retries=0\nstream_max_retries=1\n',encoding='utf-8')
    counter=tmp_path/'invocations.txt'
    if scenario.endswith('after_tool') or scenario in {'gateway_tool','gateway_cycle'} or scenario.endswith('_chain'):
        with config.open('a',encoding='utf-8') as stream:
            stream.write('\n[mcp_servers.counter]\ncommand='+c._toml_string(sys.executable)+'\nargs='+
                c._toml_array([str(Path(__file__).with_name('stop_guard_mcp_fixture.py').resolve()),str(counter)] +
                              (['--fixed'] if scenario in {'no_progress_chain','gateway_cycle'} else []))+'\n')
    install(c,config)
    try:
        # Only the reviewed hook generated above exists in this isolated home.
        result=subprocess.run([c.codex_command(),'exec','--json','--skip-git-repo-check',
            '--dangerously-bypass-hook-trust','-s','read-only','-C',str(tmp_path),'Проверь ответ'],
            env=dict({k:v for k,v in os.environ.items() if 'proxy' not in k.lower()},CODEX_HOME=str(home),USERPROFILE=str(tmp_path),HOME=str(tmp_path),NO_PROXY='127.0.0.1,localhost'),
            capture_output=True,text=True,encoding='utf-8',timeout=45)
        if scenario=='gateway_failed':
            assert result.returncode!=0
            assert len(requests)==2
            return
        if scenario=='gateway_cycle':
            assert result.returncode!=0
            assert counter.read_text()=='4'
            assert len(requests)==6
            assert json.loads((c.control_dir()/'api-guard-last.json').read_text())['status']=='tool_loop'
            return
        assert result.returncode==0,result.stderr
        expected=6 if scenario=='progress_chain' else 5 if scenario=='no_progress_chain' else 3 if scenario.endswith('after_tool') or scenario=='gateway_tool' else 2
        assert len(requests)==expected,(len(requests),result.stdout,result.stderr)
        if not scenario.startswith('gateway'):assert 'Hybrid Control' in json.dumps(requests[-1],ensure_ascii=False)
        if scenario not in {'always_broken','no_progress_chain'}:assert 'Готово. Проверка завершена.' in result.stdout
        if scenario.endswith('after_tool') or scenario=='gateway_tool':
            assert counter.exists(),(','.join(str(t.get('name')) for t in requests[0].get('tools',[]))+'\n'+result.stderr)
            assert counter.read_text()=='1'
        if scenario.endswith('_chain'):assert counter.read_text()=='2'
    finally:
        if gateway:gateway.shutdown();gateway.server_close()
        server.shutdown();server.server_close()
