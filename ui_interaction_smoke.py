"""Exercise real mouse callbacks in a disposable GUI, including frozen builds."""
import ctypes
from ctypes import wintypes
import tempfile
import threading
import time
from pathlib import Path


def run(core):
    from hybrid_ui import install
    if core.os.name != 'nt':
        raise RuntimeError('This interaction check requires Windows')
    with tempfile.TemporaryDirectory(prefix='hybrid-interactions-') as temporary:
        core._home = lambda: Path(temporary)
        core.get_user_api_key = lambda: None
        core.user_api_key_present = lambda: False
        install(core)
        app = core.SwitcherApp(startup_check=True)
        app.geometry('1000x720+80+80')
        app.deiconify()
        errors = []
        completed = []
        app.report_callback_exception = lambda kind, value, trace: errors.append(str(value))
        user32 = ctypes.windll.user32
        saved_cursor = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(saved_cursor))

        def move_mouse(x, y, drag=False):
            def work():
                user32.SetCursorPos(x, y)
                time.sleep(.08)
                user32.mouse_event(2, 0, 0, 0, 0)
                time.sleep(.15)
                if drag:
                    user32.SetCursorPos(x + 100, y + 50)
                    time.sleep(.15)
                user32.mouse_event(4, 0, 0, 0, 0)
            threading.Thread(target=work, daemon=True).start()

        def children(parent):
            for widget in parent.winfo_children():
                yield widget
                yield from children(widget)

        def start_drag():
            user32.SetForegroundWindow(user32.GetParent(app.winfo_id()))
            app._smoke_origin = (app.winfo_x(), app.winfo_y())
            bar = app._custom_chrome
            move_mouse(bar.winfo_rootx()+160, bar.winfo_rooty()+15, drag=True)
            app.after(650, open_computer)

        def open_computer():
            if (app.winfo_x(), app.winfo_y()) == app._smoke_origin:
                errors.append('Real titlebar drag did not move the window')
            else:
                completed.append('drag')
            app.notebook.select(3)
            app.update_idletasks()
            button = next(w for w in children(app) if isinstance(w, core.tk.Button)
                          and w.cget('text') == 'Открыть управление ПК')
            move_mouse(button.winfo_rootx()+button.winfo_width()//2,
                       button.winfo_rooty()+button.winfo_height()//2)
            app.after(650, check_computer)

        def check_computer():
            windows = [w for w in app.winfo_children() if isinstance(w, core.tk.Toplevel)]
            if len(windows) != 1:
                errors.append('Real computer button click did not open its window')
            else:
                completed.append('computer')
                windows[0].destroy()
            app._chrome_maximize()
            app.after(250, check_maximized)

        def check_maximized():
            if app.state() != 'zoomed': errors.append('Maximize failed')
            app._chrome_minimize()
            app.after(250, finish)

        def finish():
            if app.state() != 'iconic': errors.append('Minimize failed')
            app.deiconify()
            completed.append('window-controls')
            app.destroy()

        app.after(650, start_drag)
        app.after(8000, app.destroy)
        try:
            app.mainloop()
        finally:
            user32.mouse_event(4, 0, 0, 0, 0)
            user32.SetCursorPos(saved_cursor.x, saved_cursor.y)
        if errors or len(completed) != 3:
            raise RuntimeError('; '.join(errors) or 'Interaction check did not finish')
        print('GUI interaction check: real titlebar drag, computer click, maximize/minimize OK', flush=True)


if __name__ == '__main__':
    import codex_hybrid_control as core
    core.enable_windows_dpi_awareness()
    run(core)
