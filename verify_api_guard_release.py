"""Offline smoke check of the packaged gateway and GUI, with isolated settings."""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from hybrid_process import kill_tree
from hybrid_api_guard import VERSION
from hybrid_bridge_host import BridgeHost


def verify_transport_ownership(folder, env):
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    kernel.OpenProcess.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_uint]
    kernel.OpenProcess.restype=ctypes.c_void_p
    previous=dict(os.environ)
    try:
        os.environ.update(env)
        for kind in ['Worker','Computer']:
            host=BridgeHost([str(folder/f'Codex-Hybrid-{kind}-Bridge.exe'),
                             '--bridge-child-'+kind.lower()],timeout=15)
            observed=None
            try:
                reply=host.handle({'jsonrpc':'2.0','id':1,'method':'initialize'})
                assert 'result' in reply,reply
                assert host.transport_handle,'Packaged transport did not announce its owned process'
                # A second handle observes the same process object after close.
                kernel.GetProcessId.argtypes=[ctypes.c_void_p]
                pid=kernel.GetProcessId(host.transport_handle)
                observed=kernel.OpenProcess(0x100000,False,pid)
                assert observed
                host.close()
                assert kernel.WaitForSingleObject(observed,5000)==0,'Transport survived close'
            finally:
                host.close()
                if observed:kernel.CloseHandle(observed)
    finally:
        os.environ.clear();os.environ.update(previous)


def main():
    parser=argparse.ArgumentParser()
    default=Path(__file__).resolve().parent/'dist'/'7.3.2'
    if not default.is_dir():default=default.parent
    parser.add_argument('--dist',default=str(default))
    folder=Path(parser.parse_args().dist).resolve()
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            self.wfile.write(b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n')
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=upstream.serve_forever,daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='hybrid-gateway-release-') as temp:
            home=Path(temp);control=home/'.codex/hybrid-control';control.mkdir(parents=True)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            (control/'api-guard.json').write_text(json.dumps({'enabled':True,'port':port,'access':'release-test'}))
            (control/'active-connection.json').write_text(json.dumps({'name':'Test','base_url':f'http://127.0.0.1:{upstream.server_port}/v1'}))
            env=dict(os.environ,USERPROFILE=temp,HOME=temp,CODEX_HOME=str(home/'.codex'))
            verify_transport_ownership(folder,env)
            process=subprocess.Popen([str(folder/'Codex-Hybrid-Worker-Bridge.exe'),'--api-guard'],env=env,
                                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                deadline=time.monotonic()+15
                while True:
                    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
                    try:
                        connection.request('GET','/release-test/health');response=connection.getresponse()
                        assert response.status==200 and json.loads(response.read())['version']==VERSION
                        break
                    except OSError:
                        if time.monotonic()>deadline:raise
                        time.sleep(.1)
                    finally:connection.close()
                connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                connection.request('POST','/release-test/v1/responses','{"stream":true}',{'Authorization':'Bearer test-only'})
                response=connection.getresponse()
                assert response.status==200 and b'response.completed' in response.read()
                connection.close()
                result=subprocess.run([str(folder/'Codex-Hybrid-Control.exe'),'--startup-check'],env=env,
                                      capture_output=True,timeout=30)
                assert result.returncode==0,result.returncode
            finally:
                kill_tree(process);process.wait(timeout=10)
    finally:
        upstream.shutdown();upstream.server_close()
    print('Packaged gateway, isolated provider request, GUI startup: PASS')


if __name__=='__main__':main()
