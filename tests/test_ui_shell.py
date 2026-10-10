import time
import pytest
import codex_hybrid_control as c
import hybrid_ui


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(c, '_home', lambda: tmp_path)
    monkeypatch.setattr(c, 'get_user_api_key', lambda: None)
    monkeypatch.setattr(c, 'user_api_key_present', lambda: False)
    hybrid_ui.install(c)
    instance = c.SwitcherApp(startup_check=True)
    instance.update_idletasks()
    yield instance
    for pending in instance.tk.call('after', 'info'):
        instance.after_cancel(pending)
    instance.destroy()


def drain(app):
    deadline = time.monotonic() + 4
    while app._busy and time.monotonic() < deadline:
        app.update()
        time.sleep(.01)
    assert not app._busy


def test_navigation_and_pending_mode(app):
    assert list(app.tabs) == ['home', 'api', 'workers', 'tools', 'recovery']
    for index, name in enumerate(app.tabs):
        app.notebook.select(index)
        assert app.tabs[name].winfo_manager() == 'pack'
        assert sum(bool(frame.winfo_manager()) for frame in app.tabs.values()) == 1
    app.selected_mode.set('api')
    assert 'неприменённые' in app.pending_label.cget('text')
    assert app.delegation_policy.get() == 'api_only'


def test_background_failure_is_reported_and_controls_reenabled(app, monkeypatch):
    errors=[]
    monkeypatch.setattr(hybrid_ui.messagebox,'showerror',lambda *a,**kw:errors.append(a))
    def fail():raise RuntimeError('test failure')
    app._run_background('Testing',fail,lambda _:pytest.fail('Unexpected success'))
    drain(app)
    assert errors and 'test failure' in app.status.get()
    assert app.activate_button.cget('state') == 'normal'
    assert 'test failure' in app.repair_report.get('1.0','end')


def test_repair_partial_result_visible(app,monkeypatch):
    monkeypatch.setattr(c,'repair_all',lambda path:{'ok':False,'steps':[
        {'name':'API-ключ','status':'warning','detail':'Ключ не задан'}]},raising=False)
    app.repair_everything()
    drain(app)
    assert 'Ключ не задан' in app.repair_report.get('1.0','end')
    assert 'внимания' in app.status.get()


def test_stock_ui_cannot_reenable_integrations(app,monkeypatch):
    monkeypatch.setattr(c,'is_stock_mode',lambda:True,raising=False)
    monkeypatch.setattr(c,'apply_mode',lambda *a,**k:pytest.fail('Changed stock mode'))
    app.refresh()
    app.apply_only()
    app.activate_api()
    app.open_computer_bridge()
    app.open_worker_center()
    assert 'отключены' in app.status.get()
    assert app.hero_title.cget('text') == 'Обычный Codex'


def test_browser_fetch_runs_off_ui_thread_and_renders_links(app,monkeypatch):
    import threading
    threads=[]
    def fetch(url):
        threads.append(threading.current_thread().name)
        return {'ok':True,'title':'Test page','url':url,'status':200,'chars':5,'text':'Hello',
                'links':['https://example.com/next']}
    monkeypatch.setattr(c,'browser_fetch',fetch)
    win=c.open_browser_window(app)
    def descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from descendants(child)
    widgets=list(descendants(win))
    load=next(w for w in widgets if isinstance(w,c.tk.Button) and w.cget('text')=='Открыть')
    output=next(w for w in widgets if isinstance(w,c.tk.Text))
    load.invoke()
    deadline=time.monotonic()+3
    while load.cget('state')=='disabled' and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    assert threads and threads[0] != threading.main_thread().name
    assert 'Test page' in output.get('1.0','end')
    assert 'url_0' in output.tag_names()
    assert output.cget('state')=='disabled'
    win.destroy()


def test_api_failure_callback_releases_refresh_flag(app,monkeypatch):
    monkeypatch.setattr(c,'get_user_api_key',lambda:'fake-test-token')
    def fail(*args,**kwargs):raise RuntimeError('provider unavailable')
    monkeypatch.setattr(c,'validate_api_key',fail)
    app.refresh_api_usage_async()
    deadline=time.monotonic()+3
    while app._usage_refreshing and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    assert not app._usage_refreshing
    assert 'provider unavailable' in app.status.get()


def test_close_waits_for_config_operation_to_finish(app,monkeypatch):
    import threading
    release=threading.Event();events=[]
    monkeypatch.setattr(app,'destroy',lambda:events.append('closed'))
    def work():
        release.wait(timeout=2);events.append('saved');return True
    app._run_background('Saving',work,lambda _:events.append('done'))
    app._request_close()
    assert not events and app.winfo_exists()
    release.set();drain(app)
    assert events==['saved','done','closed']


def test_auxiliary_window_cancels_its_timer_on_close(app):
    before=set(app.winfo_children())
    app.open_worker_center()
    window=next(w for w in app.winfo_children() if isinstance(w,c.tk.Toplevel) and w not in before)
    identifier=window.after(500,lambda:pytest.fail('Callback after window closed'))
    window.destroy()
    assert identifier not in app.tk.call('after','info')


@pytest.mark.skipif(c.os.name!='nt',reason='Windows chrome integration')
def test_native_resize_maximize_and_minimize_are_preserved(app):
    app.deiconify();app.update()
    user32=c.ctypes.windll.user32
    hwnd=user32.GetParent(app.winfo_id())
    style=user32.GetWindowLongW(hwnd,-16)
    assert style & 0x00C00000 == 0
    assert style & 0x00040000
    app._chrome_maximize();app.update()
    assert user32.IsZoomed(hwnd)
    app._chrome_minimize();app.update()
    assert user32.IsIconic(hwnd)
    user32.ShowWindow(hwnd,9);app.update()
    assert not user32.IsIconic(hwnd)


def test_repeated_widget_paint_reuses_images_but_updates_state(app):
    control=app.apply_button;control.repaint();image=control._photo
    for _ in range(30):control.repaint()
    assert control._photo is image
    control.configure(state='disabled')
    assert control._photo is not image
    control.configure(state='normal')
