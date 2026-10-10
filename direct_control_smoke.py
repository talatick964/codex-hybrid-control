"""Real Windows/Edge checks against disposable local fixtures; no external API."""
import ctypes
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
import codex_hybrid_control as core
from hybrid_accessibility import Accessibility
from hybrid_browser_control import BrowserControl


FORM = r'''
Add-Type -AssemblyName System.Windows.Forms
$form=[Windows.Forms.Form]::new()
$form.Text='Hybrid UIA test fixture'
$form.Width=420;$form.Height=240
$edit=[Windows.Forms.TextBox]::new();$edit.Name='hybridEdit';$edit.Left=20;$edit.Top=25;$edit.Width=300
$button=[Windows.Forms.Button]::new();$button.Text='Run test';$button.Name='hybridButton';$button.Left=20;$button.Top=70
$label=[Windows.Forms.Label]::new();$label.Text='Waiting';$label.Name='hybridResult';$label.Left=20;$label.Top=120;$label.Width=300
$button.Add_Click({$label.Text='Verified result'})
$form.Controls.AddRange(@($edit,$button,$label))
[Console]::WriteLine($form.Handle.ToInt64())
$form.ShowDialog() | Out-Null
'''


def main():
    with tempfile.TemporaryDirectory(prefix='hybrid-direct-smoke-') as temporary:
        core._home=lambda:Path(temporary)
        core.save_computer_policy({'enabled':True,'allow_input':True,'allow_screenshot':True,'allow_launch':True})
        script=Path(__file__).parent/'tests'/'native_control_fixture.py'
        form=subprocess.Popen([sys.executable,str(script)],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        hwnd=None
        try:
            hwnd=int(form.stdout.readline().strip())
            time.sleep(.3)
            uia=Accessibility(core)
            snapshot=uia.inspect(hwnd)
            edit=next(e for e in snapshot['elements'] if e['type']=='ControlType.Edit')
            assert uia.act(edit['element_id'],'set_value','Local test')['verified']
            snapshot=uia.inspect(hwnd)
            button=next(e for e in snapshot['elements'] if e['name']=='Run test')
            assert uia.act(button['element_id'],'invoke')['dispatched']
            snapshot=uia.inspect(hwnd)
            assert any(e['name']=='Verified result' for e in snapshot['elements'])
            print('Windows UI Automation: real text field, button invoke, result verification OK',flush=True)
        finally:
            if hwnd:ctypes.windll.user32.PostMessageW(hwnd,0x0010,0,0)
            try:form.wait(timeout=5)
            except subprocess.TimeoutExpired:form.kill();form.wait()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                html=b'''<!doctype html><html><body><h1>Local fixture</h1><input aria-label="Test field" id="entry"><button onclick="document.getElementById('result').textContent='Verified DOM result'">Run local test</button><p id="result">Waiting</p></body></html>'''
                self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(html)))
                self.end_headers();self.wfile.write(html)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        browser=BrowserControl(core)
        started=False
        try:
            result=browser.start();started=True
            tab=result['tabs'][0]['tab_id']
            assert browser.navigate(tab,f'http://127.0.0.1:{server.server_port}/')['verified']
            snapshot=browser.inspect(tab)
            entry=next(e for e in snapshot['elements'] if e['tag']=='input')
            assert browser.act(tab,entry['element_id'],'fill','Local browser test')['verified']
            snapshot=browser.inspect(tab)
            button=next(e for e in snapshot['elements'] if e['tag']=='button')
            assert browser.act(tab,button['element_id'],'click')['dispatched']
            assert 'Verified DOM result' in browser.inspect(tab)['text']
            print('Browser CDP: real Edge page, DOM inspection, fill, click and result verification OK',flush=True)
        finally:
            if started:
                result=browser.close()
                if not result.get('ok'):raise RuntimeError('Could not close owned browser fixture')
            server.shutdown();server.server_close()


if __name__=='__main__':main()
