"""Smoke-test packaged executables in a disposable Codex home, without API calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import queue
import threading
import ctypes
import shutil
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def verify_direct_tools(folder,env,temporary):
    home=Path(temporary)/'.codex'/'hybrid-control'
    home.mkdir(parents=True,exist_ok=True)
    (home/'computer-policy.json').write_text(json.dumps({'enabled':True,'allow_input':True,
                'allow_launch':True,'allow_screenshot':True,'control_mode':'auto'}),encoding='utf-8')
    process=subprocess.Popen([str(folder/'Codex-Hybrid-Computer-Bridge.exe')],stdin=subprocess.PIPE,
                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,text=True,encoding='utf-8')
    replies=queue.Queue()
    def reader():
        for line in process.stdout:
            replies.put(json.loads(line))
    threading.Thread(target=reader,daemon=True).start()
    serial=0
    def request(method,params=None):
        nonlocal serial
        serial+=1
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':serial,'method':method,'params':params or {}})+'\n');process.stdin.flush()
        result=replies.get(timeout=35)
        assert result['id']==serial and 'result' in result,result
        assert not result['result'].get('isError'),result
        return result['result']
    def tool(name,arguments):
        result=request('tools/call',{'name':name,'arguments':arguments})
        return json.loads(result['content'][0]['text'])
    native=None;hwnd=None;browser_started=False;server=None
    try:
        request('initialize')
        native=subprocess.Popen([sys.executable,str(Path(__file__).parent/'tests'/'native_control_fixture.py')],stdout=subprocess.PIPE,text=True)
        hwnd=int(native.stdout.readline())
        elements=tool('computer_elements',{'hwnd':hwnd})['elements']
        edit=next(e for e in elements if e['type']=='ControlType.Edit')
        result=tool('computer_element_action',{'element_id':edit['element_id'],'operation':'set_value','value':'Packaged test','action_id':'packaged-edit'})
        assert result['verified']
        again=tool('computer_element_action',{'element_id':edit['element_id'],'operation':'set_value','value':'Packaged test','action_id':'packaged-edit'})
        assert not again['replayed']
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                html=b'<input aria-label="Field"><button onclick="document.body.append(\'Package verified\')">Run</button>'
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(html)));self.end_headers();self.wfile.write(html)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        result=tool('browser_control',{'operation':'start'});browser_started=True
        tab=result['tabs'][0]['tab_id']
        assert tool('browser_control',{'operation':'navigate','tab_id':tab,'url':f'http://127.0.0.1:{server.server_port}/'})['verified']
        elements=tool('browser_control',{'operation':'inspect','tab_id':tab})['elements']
        field=next(e for e in elements if e['tag']=='input')
        assert tool('browser_control',{'operation':'fill','tab_id':tab,'element_id':field['element_id'],'value':'Package test'})['verified']
        elements=tool('browser_control',{'operation':'inspect','tab_id':tab})['elements']
        button=next(e for e in elements if e['tag']=='button')
        assert tool('browser_control',{'operation':'click','tab_id':tab,'element_id':button['element_id']})['dispatched']
        assert 'Package verified' in tool('browser_control',{'operation':'inspect','tab_id':tab})['text']
        print('Packaged MCP: real UIA field + durable receipt + Edge DOM/fill/click/result OK.')
    finally:
        if browser_started:assert tool('browser_control',{'operation':'close'})['verified']
        if hwnd:ctypes.windll.user32.PostMessageW(hwnd,0x0010,0,0)
        if native:
            try:native.wait(timeout=5)
            except subprocess.TimeoutExpired:native.kill();native.wait()
        if server:server.shutdown();server.server_close()
        process.stdin.close()
        try:process.wait(timeout=12)
        except subprocess.TimeoutExpired:process.kill();process.wait()


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    default=Path(__file__).resolve().parent/'dist'/'7.3.2'
    if not default.is_dir():default=default.parent
    parser.add_argument('--dist',type=Path,default=default)
    folder=parser.parse_args().dist.resolve()
    with tempfile.TemporaryDirectory(prefix='hybrid-release-') as temporary:
        env=dict(os.environ,USERPROFILE=temporary,HOME=temporary,CODEX_HOME=str(Path(temporary)/'.codex'),PYTHONIOENCODING='cp1251')
        env.pop('FUNPAY_API_KEY',None)
        gui=subprocess.run([str(folder/'Codex-Hybrid-Control.exe'),'--startup-check'],env=env,
                           capture_output=True,timeout=90)
        assert gui.returncode==0,gui.stderr.decode('utf-8','replace')
        assert (Path(temporary)/'.codex'/'config.toml').exists()
        from hybrid_catalog import validate
        catalog_path=Path(temporary)/'.codex'/'funpay-models.json'
        validate(json.loads(catalog_path.read_text(encoding='utf-8')))
        cli=shutil.which('codex.cmd') or shutil.which('codex.exe') or shutil.which('codex')
        assert cli,'Codex CLI is required for the final catalog compatibility check'
        catalog_check=subprocess.run([cli,'debug','prompt-input','-c','model_provider="funpay"',
            '-c','model="gpt-5.6-sol"','-c','model_catalog_json='+json.dumps(str(catalog_path)),'PACKAGED_CATALOG_OK'],
            env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert catalog_check.returncode==0,catalog_check.stderr
        assert 'PACKAGED_CATALOG_OK' in catalog_check.stdout
        interactions=subprocess.run([str(folder/'Codex-Hybrid-Control.exe'),'--ui-interaction-check'],env=env,
                                    capture_output=True,timeout=45)
        assert interactions.returncode==0,interactions.stderr.decode('utf-8','replace')
        request='\n'.join(json.dumps(row) for row in [
            {'jsonrpc':'2.0','id':1,'method':'initialize'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'}])+'\n'
        counts={}
        for name in ['Worker','Computer']:
            result=subprocess.run([str(folder/f'Codex-Hybrid-{name}-Bridge.exe')],input=request.encode('utf-8'),
                                  capture_output=True,env=env,timeout=30)
            assert result.returncode==0,result.stderr.decode('utf-8','replace')
            rows=[json.loads(line) for line in result.stdout.decode('utf-8').splitlines()]
            counts[name]=len(rows[1]['result']['tools'])
        assert counts=={'Worker':4,'Computer':20},counts
        verify_direct_tools(folder,env,temporary)
        outcome=Path(temporary)/'deadline.json'
        subprocess.run([str(folder/'Codex-Hybrid-Worker-Bridge.exe'),'--supervise-worker','.5',str(outcome),'--',
                        sys.executable,'-c','import time; time.sleep(30)'],env=env,capture_output=True,timeout=20)
        assert json.loads(outcome.read_text(encoding='utf-8'))['status']=='TIMED_OUT'
        print('Packaged GUI startup + real drag/computer click OK; Worker MCP 4 tools; Computer MCP 20 tools; supervisor deadline OK.')


if __name__=='__main__':main()
