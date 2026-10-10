"""Repeated GUI lifecycle and responsiveness check in a disposable home."""
import gc
import json
from pathlib import Path
import tempfile
import threading
import time
import codex_hybrid_control as core
import hybrid_diagnostics
from hybrid_ui import install


def main():
    with tempfile.TemporaryDirectory(prefix='hybrid-gui-stress-') as temporary:
        core._home=lambda:Path(temporary);core.get_user_api_key=lambda:None;core.user_api_key_present=lambda:False
        gate=threading.Event();started=threading.Event()
        def slow_check(*args):
            started.set();gate.wait(timeout=5)
            return {'ok':True,'steps':[{'name':'Тест','status':'ok','detail':'Готово'}]}
        hybrid_diagnostics.compatibility=slow_check
        install(core);app=core.SwitcherApp(startup_check=False)
        errors=[];app.report_callback_exception=lambda kind,value,trace:errors.append(str(value))
        app.update();base_images=len(app.tk.call('image','names'));ticks=0
        begin=time.monotonic()
        while time.monotonic()-begin<2.2:
            app.notebook.select(ticks%5);app.update();ticks+=1;time.sleep(.02)
        assert started.is_set() and not app._busy and app.activate_button.cget('state')=='normal'
        gate.set();app.update();app.after(120);app.update()
        windows=0
        methods=[app.open_agent_browser,app.open_computer_bridge,app.open_worker_center,
                 app.open_hybrid_chat,app.open_connections,app.open_checkpoints]
        for _ in range(5):
            for callback in methods:
                before=set(app.winfo_children());callback();app.update()
                for window in list(app.winfo_children()):
                    if isinstance(window,core.tk.Toplevel) and window not in before:
                        windows+=1;window.destroy()
                app.update()
        deadline=time.monotonic()+3.2
        while time.monotonic()<deadline:app.update();time.sleep(.02)
        gc.collect();app.update()
        final_images=len(app.tk.call('image','names'))
        assert not errors,errors
        assert not any(isinstance(w,core.tk.Toplevel) for w in app.winfo_children())
        assert final_images<=base_images+20,(base_images,final_images)
        result={'ok':True,'windows_opened_closed':windows,'navigation_updates':ticks,'automatic_check_blocks_ui':False,
                'callback_errors':errors,'images_before':base_images,'images_after':final_images,
                'elapsed_seconds':round(time.monotonic()-begin,2)}
        app.destroy()
        report=Path(__file__).parent/'artifacts'/'final-gui-stress.json'
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
