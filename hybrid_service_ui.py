"""Connection management, previews and diagnostics within the existing shell."""
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from hybrid_widgets import RoundButton, RoundFrame, install_chrome


def install_services(core):
    cls=core.SwitcherApp

    def preview(self, payload, apply, title='Предпросмотр настроек'):
        win=tk.Toplevel(self);win.title(title);win.configure(bg=self.BG)
        win.geometry('880x650');win.minsize(660,480)
        install_chrome(win,title,cls.BODY_FONT)
        tk.Label(win,text=title,bg=self.BG,fg=self.FG,font=(cls.HEADING_FONT,20)).pack(anchor='w',padx=24,pady=(20,10))
        tk.Label(win,text='\n'.join(payload.get('notes',[])),bg=self.BG,fg=self.MUTED,font=(cls.BODY_FONT,10),
                 wraplength=790,justify='left').pack(anchor='w',padx=24,pady=(0,14))
        body=tk.Frame(win,bg=self.PANEL);body.pack(fill='both',expand=True,padx=24,pady=(0,16))
        output=tk.Text(body,bg=self.PANEL,fg=self.FG,font=('Consolas',10),wrap='none',bd=0,padx=14,pady=14)
        scroll=ttk.Scrollbar(body,orient='vertical',command=output.yview,style='Shell.Vertical.TScrollbar');scroll.pack(side='right',fill='y')
        output.pack(fill='both',expand=True);output.configure(yscrollcommand=scroll.set)
        output.insert('1.0',payload.get('diff') or 'Основная конфигурация уже соответствует выбранным настройкам.')
        output.configure(state='disabled')
        row=tk.Frame(win,bg=self.BG);row.pack(fill='x',padx=24,pady=(0,18))
        def commit():
            win.destroy();apply(payload.get('source_hash'))
        RoundButton(row,text='Применить',command=commit,bg='#dbe2e9',fg=self.BG,font=(cls.BODY_FONT,10)).pack(side='left',padx=(0,8))
        RoundButton(row,text='Отмена',command=win.destroy,fg=self.FG,font=(cls.BODY_FONT,10)).pack(side='left')
        return win

    def apply_mode_preview(self,restart=False):
        if self._busy:return
        if core.is_stock_mode():
            self.notebook.select(4);self.status.set('Сначала восстановите Hybrid Control');return
        from hybrid_connections import preview_mode,SettingsTransaction
        mode=self.selected_mode.get();model=self.api_model.get().strip();reasoning=self.reasoning.get();delegation=self.delegation_policy.get()
        try:
            payload=preview_mode(core,self.state_obj.config_path,mode,model,reasoning,delegation)
            if mode=='api' and not core.user_api_key_present():payload['notes'].append('API-ключ не задан: запросы модели не заработают до его сохранения.')
            if restart:payload['notes'].append('После применения Codex будет перезапущен. Создайте новый сеанс.')
        except Exception as error:
            messagebox.showerror('Предпросмотр',str(error),parent=self);return
        def commit(expected_hash):
            def work():
                def mutate():
                    core.bootstrap_codex_files()
                    _,parsed=core.apply_mode(self.state_obj.config_path,mode,model,reasoning,delegation)
                    if mode=='api':core.prepare_api_autonomy(self.state_obj.config_path)
                    core.update_global_mode(mode,parsed['model_provider'],parsed['model'],
                                             'api_only' if mode=='api' else delegation)
                    return parsed
                result=SettingsTransaction(core,self.state_obj.config_path).execute(mutate,'Применение режима',expected_hash)
                if restart:result['restart']=core.restart_codex_desktop()
                return result
            def done(result):
                self.refresh()
                self.status.set('Настройки применены; снимок для отката сохранён. Для нового режима нужен новый сеанс Codex.')
                if restart and not result['restart'][0]:messagebox.showwarning('Перезапуск',result['restart'][1],parent=self)
            self._run_background('Применяем настройки и сохраняем снимок…',work,done)
        return preview(self,payload,commit)

    def show_check(self,result):
        lines=[f"{step['name']} · {step['status']}\n{step['detail']}" for step in result.get('steps',[])]
        if result.get('scope'):lines.append(result['scope'])
        self.service_report.configure(state='normal');self.service_report.delete('1.0','end')
        self.service_report.insert('1.0','\n\n'.join(lines));self.service_report.configure(state='disabled')
        self.status.set('Проверка завершена' if result.get('ok') else 'Проверка завершена: есть ошибки или неподтверждённые пункты')

    def check_compatibility(self):
        self._diagnostics_revision+=1
        from hybrid_diagnostics import compatibility
        config_path=self.state_obj.config_path
        self.notebook.select(1)
        self._run_background('Проверяем совместимость Codex и мостов…',
                     lambda:compatibility(core,config_path),lambda result:show_check(self,result))

    def check_api(self):
        self._diagnostics_revision+=1
        from hybrid_diagnostics import api_diagnostics
        from hybrid_connections import active_connection
        if core.is_stock_mode():self.status.set('Сначала восстановите Hybrid Control');return
        connection=active_connection(core);model=self.api_model.get().strip()
        # The user explicitly invokes the diagnostic; these requests are small,
        # paid requests to the selected provider, never to a different account.
        self._run_background('Проверяем API: модель, поток, инструменты, изображения…',
            lambda:api_diagnostics(core,connection['base_url'],model),lambda result:show_check(self,result))

    def export(self):
        from hybrid_diagnostics import export_report
        destination=filedialog.asksaveasfilename(parent=self,title='Сохранить отчёт без ключей',defaultextension='.json',
                           initialfile='Hybrid-Control-report.json',filetypes=[('JSON','*.json')])
        if not destination:return
        self._run_background('Собираем отчёт без ключей и содержимого чатов…',
            lambda:export_report(core,self.state_obj.config_path,destination),
            lambda result:self.status.set('Отчёт сохранён: '+result['path']))

    def checkpoints(self):
        from hybrid_connections import SettingsTransaction
        transaction=SettingsTransaction(core,self.state_obj.config_path)
        win=tk.Toplevel(self);win.title('Откат настроек');win.configure(bg=self.BG);win.geometry('760x450')
        install_chrome(win,'Откат настроек',cls.BODY_FONT)
        tk.Label(win,text='Снимки перед изменениями',bg=self.BG,fg=self.FG,font=(cls.HEADING_FONT,20)).pack(anchor='w',padx=24,pady=20)
        rows=transaction.list()
        listbox=tk.Listbox(win,bg=self.PANEL,fg=self.FG,bd=0,font=(cls.BODY_FONT,11),selectbackground='#3c4651')
        listbox.pack(fill='both',expand=True,padx=24,pady=(0,16))
        for row in rows:listbox.insert('end',f"{row['created_at']} · {row['label']} · {row['state']}")
        tk.Label(win,text='При ручных изменениях после применения откат остановится и покажет конфликт.',bg=self.BG,fg=self.MUTED,
                 wraplength=700,font=(cls.BODY_FONT,10)).pack(anchor='w',padx=24,pady=(0,14))
        def rollback():
            selected=listbox.curselection()
            if not selected:return
            row=rows[selected[0]]
            if not messagebox.askyesno('Откат','Восстановить настройки до операции «'+row['label']+'»?',parent=win):return
            win.destroy()
            self._run_background('Восстанавливаем снимок…',lambda:transaction.rollback(row['id']),
                                  lambda result:(self.refresh(),self.status.set('Настройки восстановлены. Создайте новый сеанс Codex.')))
        RoundButton(win,text='Восстановить выбранный снимок',command=rollback,fg=self.FG,font=(cls.BODY_FONT,10)).pack(anchor='w',padx=24,pady=(0,18))
        return win

    def connections(self):
        from hybrid_connections import Connections,active_connection
        store=Connections(core)
        try:current=active_connection(core)
        except RuntimeError:
            current={'name':'Новое подключение','base_url':core.API_BASE+'/v1','model':'','worker_models':{}}
        win=tk.Toplevel(self);win.title('Профили подключения');win.configure(bg=self.BG);win.geometry('850x740');win.minsize(700,660)
        install_chrome(win,'Профили подключения',cls.BODY_FONT)
        tk.Label(win,text='Ваши подключения',bg=self.BG,fg=self.FG,font=(cls.HEADING_FONT,20)).pack(anchor='w',padx=24,pady=(20,12))
        content=tk.Frame(win,bg=self.BG);content.pack(fill='both',expand=True,padx=24)
        selector=ttk.Combobox(content,state='readonly');selector.pack(fill='x',pady=(0,12))
        fields={};entries={}
        specs=[('name','Название',current['name']),('base_url','Базовый URL API, включая /v1',current['base_url']),
               ('model','Модель главного агента',self.api_model.get()),('key','API-ключ · хранится с защитой Windows','')]
        for key,title,value in specs:
            tk.Label(content,text=title,bg=self.BG,fg=self.MUTED,font=(cls.BODY_FONT,10)).pack(anchor='w',pady=(0,3))
            fields[key]=tk.StringVar(win,value=value)
            entry=tk.Entry(content,textvariable=fields[key],bg=self.PANEL2,fg=self.FG,insertbackground=self.FG,bd=0,
                           show='•' if key=='key' else '',font=(cls.BODY_FONT,11))
            entry.pack(fill='x',ipady=9,pady=(0,12));entries[key]=entry
        workers=tk.Frame(content,bg=self.BG);workers.pack(fill='x',pady=(0,12))
        for name in core.WORKER_PROFILES:
            box=tk.Frame(workers,bg=self.BG);box.pack(side='left',fill='x',expand=True,padx=(0,8))
            tk.Label(box,text='Модель '+name,bg=self.BG,fg=self.MUTED,font=(cls.BODY_FONT,9)).pack(anchor='w')
            fields[name]=tk.StringVar(win,value=current.get('worker_models',{}).get(name,core.worker_settings()[name]['model']))
            tk.Entry(box,textvariable=fields[name],bg=self.PANEL2,fg=self.FG,insertbackground=self.FG,bd=0,
                     font=(cls.BODY_FONT,9)).pack(fill='x',ipady=8)
        hint=tk.StringVar(win,value='Профили не меняют текущую настройку до применения. Пустой ключ сохраняет прежний ключ выбранного профиля.')
        tk.Label(content,textvariable=hint,bg=self.BG,fg=self.MUTED,wraplength=760,justify='left',font=(cls.BODY_FONT,9)).pack(anchor='w',pady=(0,14))
        selected=[None];rows=[]
        def refresh():
            rows[:]=store.list();selector.configure(values=['Новое подключение']+[r['name'] for r in rows])
            selector.current(next((i+1 for i,r in enumerate(rows) if r['id']==selected[0]),0))
        def choose(event=None):
            index=selector.current()
            if index<=0:selected[0]=None;fields['key'].set('');return
            row=rows[index-1];selected[0]=row['id']
            for key in ('name','base_url','model'):fields[key].set(row[key])
            fields['key'].set('')
            for name in core.WORKER_PROFILES:fields[name].set(row.get('worker_models',{}).get(name,row['model']))
            hint.set('Ключ сохранён и скрыт' if row.get('key_present') else 'В профиле нет ключа')
        selector.bind('<<ComboboxSelected>>',choose)
        def save():
            try:
                saved=store.save(fields['name'].get(),fields['base_url'].get(),fields['model'].get(),
                     self.reasoning.get(),key=fields['key'].get() or None,profile_id=selected[0],
                     worker_models={n:fields[n].get().strip() or fields['model'].get().strip() for n in core.WORKER_PROFILES})
                selected[0]=saved['id'];fields['key'].set('');refresh();hint.set('Профиль сохранён; текущее подключение ещё не изменено')
            except Exception as error:hint.set(str(error))
        def save_current():
            key=core.get_user_api_key()
            if not key:hint.set('У текущего подключения нет ключа');return
            try:
                saved=store.save(current['name'],current['base_url'],self.api_model.get(),self.reasoning.get(),key,
                               {n:v['model'] for n,v in core.worker_settings().items()})
                selected[0]=saved['id'];refresh();choose()
            except Exception as error:hint.set(str(error))
        def apply_profile():
            if not selected[0]:hint.set('Сначала сохраните профиль');return
            profile_id=selected[0]
            try:payload=store.preview(profile_id,self.state_obj.config_path)
            except Exception as error:hint.set(str(error));return
            def commit(expected_hash):
                if win.winfo_exists():win.destroy()
                self._run_background('Переключаем подключение и сохраняем снимок…',
                    lambda:store.apply(profile_id,self.state_obj.config_path,expected_hash,payload['profile_hash']),
                    lambda result:(self.refresh(),self.status.set('Подключение применено. Перезапустите Codex и создайте новый сеанс.')))
            preview(self,payload,commit,'Предпросмотр подключения')
        row=tk.Frame(content,bg=self.BG);row.pack(fill='x')
        for text,callback in [('Сохранить профиль',save),('Сохранить текущее',save_current),('Предпросмотр и применение',apply_profile)]:
            RoundButton(row,text=text,command=callback,fg=self.FG,font=(cls.BODY_FONT,9),padx=12).pack(side='left',padx=(0,6))
        refresh();return win

    def start_browser(self):
        from hybrid_browser_control import BrowserControl
        browser=BrowserControl(core)
        self._run_background('Запускаем отдельную сессию Chrome/Edge…',browser.start,
            lambda result:self.status.set('Браузер открыт. В Codex доступны browser_control: tabs, inspect, click, fill.'))

    cls._apply=apply_mode_preview
    cls.apply_restart=lambda self:self._apply(True)
    cls.check_compatibility=check_compatibility
    cls.check_api=check_api
    cls.export_diagnostics=export
    cls.open_checkpoints=checkpoints
    cls.open_connections=connections
    cls.start_managed_browser=start_browser


def build_services(core,self,pages,section,action_row,label):
    self._diagnostics_revision=0
    api=pages['api']
    profiles=section(self,api,'Профили подключения','Сохранённые провайдеры, модели и защищённые ключи. Перед переключением — предпросмотр и снимок для отката.')
    action_row(self,profiles,[('Ваши подключения',self.open_connections,False),('Откат настроек',self.open_checkpoints,False)])
    checks=section(self,api,'Совместимость и диагностика API','Локальная проверка после обновления Codex. Диагностика API отправляет небольшие платные запросы выбранному провайдеру.')
    action_row(self,checks,[('Проверить совместимость',self.check_compatibility,False),('Проверить API',self.check_api,False)])
    self.service_report=tk.Text(checks,bg=self.PANEL,fg=self.MUTED,font=(self.BODY_FONT,10),height=10,
                                wrap='word',bd=0,padx=20,pady=12,state='disabled')
    self.service_report.pack(fill='x',pady=(0,14))
    browser=section(self,pages['tools'],'Браузер с прямым управлением','Отдельная сессия Chrome/Edge для вкладок, элементов страницы и ввода. Обычные клики мышью также доступны. Снимки и текстовый браузер остаются в своих инструментах.')
    action_row(self,browser,[('Открыть управляемый браузер',self.start_managed_browser,False)])
    monitor=section(self,pages['tools'],'Состояние мостов','Хост отслеживает дочерний процесс, заменяет его после сбоя и сохраняет соединение MCP. Запрос, оборвавшийся во время действия, автоматически не повторяется.')
    bridge_label=label(monitor,'Ожидаем данные мостов…',9,self.MUTED,wraplength=680,justify='left')
    bridge_label.pack(anchor='w',padx=20,pady=(0,18))
    def poll():
        from hybrid_bridge_host import bridge_states
        rows=[r for r in bridge_states(core) if r.get('alive')]
        text='\n'.join(f"{r['kind']} · {r['state']} · восстановлений: {max(0,r.get('generation',1)-1)}" for r in rows)
        bridge_label.configure(text=text or 'Активных мостов нет. Они запускаются при подключении нового сеанса Codex.')
        self.after(3000,poll)
    self.after(1000,poll)
    # Read-only check in the background on each app launch also catches updates
    # without silently rewriting configuration or sending model requests.
    def auto_check():
        if self._busy:
            self.after(2000,auto_check);return
        from hybrid_diagnostics import compatibility
        path=self.state_obj.config_path
        revision=self._diagnostics_revision
        original=path.read_bytes() if path.exists() else None
        def done(result):
            if (revision!=self._diagnostics_revision or self._busy or
                    (path.read_bytes() if path.exists() else None)!=original):return
            self.service_report.configure(state='normal')
            self.service_report.delete('1.0','end')
            self.service_report.insert('1.0','\n\n'.join(f"{s['name']} · {s['status']}\n{s['detail']}" for s in result.get('steps',[])))
            self.service_report.configure(state='disabled')
            if result.get('version_changed'):
                self.status.set('Обнаружено обновление Codex. Результат проверки — в разделе «Подключение API».')
        from hybrid_tasks import dispatch
        dispatch(self,lambda:compatibility(core,path),done,lambda error:None)
    if not self._startup_check:self.after(1600,auto_check)
