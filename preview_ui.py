"""Isolated local UI preview; never reads or changes the real Codex configuration."""
import sys
import tempfile
from pathlib import Path
import codex_hybrid_control as core
from hybrid_ui import install


def main():
    with tempfile.TemporaryDirectory(prefix='hybrid-ui-') as temporary:
        core._home=lambda:Path(temporary)
        core.get_user_api_key=lambda:None
        core.user_api_key_present=lambda:False
        core.enable_windows_dpi_awareness()
        install(core)
        app=core.SwitcherApp(startup_check=True)
        errors=[]
        app.report_callback_exception=lambda *args:errors.append(str(args))
        app.geometry('1180x820+40+40')
        app.deiconify()
        app.update()
        out=Path('artifacts');out.mkdir(exist_ok=True)
        for index,name in enumerate(['overview','api','agents','tools','recovery']):
            app.notebook.select(index)
            app.update()
            app.after(180)
            app.update()
            hwnd=core.ctypes.windll.user32.GetParent(app.winfo_id())
            data=core._capture_window_png(hwnd)
            if not data:raise RuntimeError('Window capture failed')
            (out/f'{name}.png').write_bytes(data)
        app.geometry('840x620+40+40');app.notebook.select(0);app.update();app.after(180)
        (out/'overview-small.png').write_bytes(core._capture_window_png(hwnd))
        app.geometry('1180x820+40+40')
        for name,action in [('browser',app.open_agent_browser),('computer',app.open_computer_bridge),('worker-monitor',app.open_worker_center),('chat',app.open_hybrid_chat),
                            ('connections',app.open_connections),('checkpoints',app.open_checkpoints),('preview',lambda:app._apply(False))]:
            before=set(app.winfo_children())
            action();app.update()
            windows=[w for w in app.winfo_children() if isinstance(w,core.tk.Toplevel) and w not in before]
            for window in windows:
                app.after(120);app.update()
                target=core.ctypes.windll.user32.GetParent(window.winfo_id())
                data=core._capture_window_png(target)
                if data:(out/f'{name}.png').write_bytes(data)
                window.destroy()
        app.destroy()
        if errors:raise RuntimeError('\n'.join(errors))
        print('UI preview: five pages, compact layout and seven tool/settings windows rendered without callback errors')


if __name__=='__main__':main()
