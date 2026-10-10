"""Codex-inspired desktop shell. No network or configuration writes at import."""
import tkinter as tk
import queue
import threading
from tkinter import ttk, messagebox
from hybrid_widgets import GradientFrame, GradientLabel, RoundFrame, RoundButton, choose_fonts, install_chrome, gradient_ancestor


def install(core):
    cls = core.SwitcherApp
    if getattr(cls,'_shell_installed',False):return
    cls._shell_installed=True
    cls.BG = '#181818'
    cls.PANEL = '#202020'
    cls.PANEL2 = '#272727'
    cls.PANEL3 = '#303030'
    cls.PANEL4 = '#383838'
    cls.FG = '#eeeeee'
    cls.MUTED = '#a2a2a2'
    cls.DIM = '#777777'
    cls.BORDER = '#303030'
    cls.BORDER2 = '#444444'
    cls.GOLD = '#e5e5e5'
    cls.GOLD2 = '#eeeeee'
    cls.GREEN = '#8db99c'
    cls.BLUE = '#477bce'
    cls.BODY_FONT='Segoe UI'
    cls.HEADING_FONT='Segoe UI Semibold'
    original_refresh = cls.refresh
    original_apply = cls._apply
    original_activate = cls.activate_api
    original_usage = cls.refresh_api_usage_async

    def label(parent, text='', size=10, fg=None, bold=False, **kw):
        current=parent
        while current is not None and not isinstance(current,GradientFrame):current=getattr(current,'master',None)
        kind=GradientLabel if current is not None else tk.Label
        return kind(parent, text=text, bg=parent.cget('bg'), fg=fg or cls.FG,
                    font=(cls.HEADING_FONT if bold else cls.BODY_FONT, size), **kw)

    def button(self, parent, text, command, primary=False):
        b = RoundButton(parent, text=text, command=command, anchor='center',
                      bg='#dbe2e9' if primary else '#303338',
                      fg=self.BG if primary else self.FG, relief='flat', bd=0,
                      activebackground='#ffffff' if primary else '#3b3b3b',
                      activeforeground=self.BG if primary else self.FG,
                      font=(cls.BODY_FONT, 10), padx=17, pady=10, cursor='hand2')
        return b

    def section(self, parent, title, subtitle='', accent=False):
        card = RoundFrame(parent, bg=self.PANEL, border=self.BORDER, radius=14)
        card.pack(fill='x', padx=28, pady=(0, 16))
        label(card, title, 12, bold=True).pack(anchor='w', padx=20, pady=(18, 5 if subtitle else 16))
        if subtitle:
            hint = label(card, subtitle, 9, self.MUTED, justify='left', wraplength=660)
            hint.pack(anchor='w', padx=20, pady=(0, 16))
            card.bind('<Configure>', lambda e: hint.configure(wraplength=max(180, e.width-44)), add='+')
        return card

    def heading(page, title, description):
        label(page, title, 24, bold=True).pack(anchor='w', padx=28, pady=(28, 6))
        lab = label(page, description, 10, cls.MUTED, justify='left', wraplength=700)
        lab.pack(anchor='w', padx=28, pady=(0, 26))
        page.bind('<Configure>', lambda e: lab.configure(wraplength=max(180,e.width-60)) if e.widget is page else None, add='+')

    def action_row(self, parent, actions):
        row = tk.Frame(parent, bg=parent.cget('bg'))
        row.pack(fill='x', padx=20, pady=(0, 18))
        for text, command, primary in actions:
            button(self, row, text, command, primary).pack(side='left', padx=(0, 8))
        return row

    def build(self):
        self._close_requested=False
        def request_close():
            if self._busy:
                self._close_requested=True
                self.status.set('Завершим текущую операцию и закроем программу. Настройки будут сохранены.')
            else:self.destroy()
        self._request_close=request_close
        self.protocol('WM_DELETE_WINDOW',request_close)
        self._scroll_targets = []
        self.tabs, self.tab_buttons = {}, {}
        cls.BODY_FONT,cls.HEADING_FONT=choose_fonts(self)
        install_chrome(self,'Codex Hybrid Control',cls.BODY_FONT)
        try:
            assets=core.Path(getattr(core.sys,'_MEIPASS',core.Path(__file__).parent))/'assets'
            self._app_icon=tk.PhotoImage(file=str(assets/'app.png'))
            self.iconphoto(True,self._app_icon)
        except tk.TclError:pass
        self.option_add('*Font', (cls.BODY_FONT, 10))
        self.option_add('*TCombobox*Listbox.background', self.PANEL2)
        self.option_add('*TCombobox*Listbox.foreground', self.FG)
        self.option_add('*TCombobox*Listbox.selectBackground', self.PANEL4)
        style=ttk.Style(self)
        style.configure('Shell.Vertical.TScrollbar',background='#424242',troughcolor=self.BG,
                        bordercolor=self.BG,arrowcolor=self.MUTED,lightcolor=self.BG,darkcolor=self.BG,
                        gripcount=0,arrowsize=10,width=10)
        style.layout('Shell.Vertical.TScrollbar', [('Vertical.Scrollbar.trough',{'sticky':'ns','children':[
            ('Vertical.Scrollbar.thumb',{'expand':'1','sticky':'nswe'})]})])
        def titlebar():
            try:
                hwnd=core.ctypes.windll.user32.GetParent(self.winfo_id())
                enabled=core.ctypes.c_int(1)
                core.ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd,20,core.ctypes.byref(enabled),4)
                caption=core.ctypes.c_uint(0x202020)
                text_color=core.ctypes.c_uint(0xEEEEEE)
                core.ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd,35,core.ctypes.byref(caption),4)
                core.ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd,36,core.ctypes.byref(text_color),4)
            except (AttributeError,OSError):pass
        self.after(50,titlebar)
        def reflow():
            def visit(parent):
                for child in parent.winfo_children():
                    if isinstance(child,tk.Label) and int(child.cget('wraplength'))>0:
                        child.configure(wraplength=max(160,parent.winfo_width()-44))
                    visit(child)
            visit(self.tab_container)
        def resized(event):
            if event.widget is self:
                if hasattr(self,'_reflow_id'):self.after_cancel(self._reflow_id)
                self._reflow_id=self.after(100,reflow)
        self.bind('<Configure>',resized,add='+')
        self.sidebar = GradientFrame(self, colors=('#232a30','#1a1d21'), width=218)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        tk.Frame(self, bg=self.BORDER, width=1).pack(side='left', fill='y')
        brand = tk.Frame(self.sidebar, bg='#1e1e1e')
        brand.pack(fill='x', padx=20, pady=(26, 30))
        label(brand, 'Codex', 20, bold=True).pack(anchor='w')
        label(brand, 'HYBRID CONTROL', 8, self.DIM).pack(anchor='w', pady=(5,0))
        label(self.sidebar, 'РАБОЧЕЕ ПРОСТРАНСТВО', 8, self.DIM).pack(anchor='w', padx=20, pady=(0,12))
        nav = tk.Frame(self.sidebar, bg='#1e1e1e')
        nav.pack(fill='x', padx=10)
        bottom = tk.Frame(self.sidebar, bg='#1e1e1e')
        bottom.pack(side='bottom', fill='x', padx=20, pady=20)
        label(bottom, 'Локально на вашем ПК', 9, self.MUTED).pack(anchor='w')
        label(bottom, 'Версия ' + core.APP_VERSION, 8, self.DIM).pack(anchor='w', pady=(5,0))
        tk.Frame(self.sidebar, bg=self.BORDER, height=1).pack(side='bottom', fill='x', padx=20)
        self.workspace = tk.Frame(self, bg=self.BG)
        self.workspace.pack(side='left', fill='both', expand=True)
        top = GradientFrame(self.workspace, colors=('#22272c','#1b1e22'), horizontal=True, height=55)
        top.pack(fill='x')
        top.pack_propagate(False)
        self.page_caption = label(top, 'Обзор', 10, self.MUTED)
        self.page_caption.pack(side='left', padx=28)
        self.mode_badge = label(top, 'Проверка', 9, self.MUTED)
        self.mode_badge.pack(side='right', padx=28)
        tk.Frame(self.workspace, bg=self.BORDER, height=1).pack(fill='x')
        footer = tk.Frame(self.workspace, bg=self.BG)
        footer.pack(side='bottom', fill='x', padx=28, pady=12)
        self.footer_dot = label(footer, '●', 8, self.GREEN)
        self.footer_dot.pack(side='left', padx=(0,8))
        status_label = tk.Label(footer, textvariable=self.status, bg=self.BG, fg=self.MUTED,
                               font=(cls.BODY_FONT, 9), anchor='w', justify='left', wraplength=700)
        status_label.pack(side='left', fill='x', expand=True)
        footer.bind('<Configure>', lambda e: status_label.configure(wraplength=max(180,e.width-30)))
        self.tab_container = tk.Frame(self.workspace, bg=self.BG)
        self.tab_container.pack(fill='both', expand=True)

        def select(index):
            for i,(name,frame) in enumerate(self.tabs.items()):
                if i == index:
                    frame.pack(fill='both', expand=True)
                    self.tab_buttons[name].configure(bg='#323b44',fg=self.FG,transparent=False)
                    self.page_caption.configure(text=titles[i][1])
                else:
                    frame.pack_forget()
                    self.tab_buttons[name].configure(bg='#303841',fg=self.MUTED,transparent=True)
        class Navigation:
            def select(_, index):
                select(index)
        self.notebook = Navigation()
        titles = [('home','Обзор','⌂'),('api','Подключение API','◇'),('workers','Агенты','♧'),
                  ('tools','Инструменты','⊞'),('recovery','Восстановление','↺')]
        pages = {}
        for index,(name,title,icon) in enumerate(titles):
            b = RoundButton(nav, text=f'  {icon}    {title}', command=lambda i=index:select(i),
                          bg='#1e1e1e',fg=self.MUTED, activebackground='#303030',activeforeground=self.FG,
                          bd=0,relief='flat',anchor='w',font=(cls.BODY_FONT,11),padx=10,pady=11,cursor='hand2',radius=10,transparent=True)
            b.pack(fill='x',pady=2)
            self.tab_buttons[name]=b
            pages[name]=self._create_scrollable_tab(self.tab_container,title,name)

        home=pages['home']
        heading(home,'Всё готово к работе?','Управляйте подключением, агентами и инструментами из одного места.')
        hero=section(self,home,'Текущее подключение')
        self.hero_title=label(hero,'—',18,bold=True,wraplength=650,justify='left')
        self.hero_title.pack(anchor='w',padx=20,pady=(0,7))
        self.hero_subtitle=label(hero,'',9,self.MUTED,wraplength=650,justify='left')
        self.hero_subtitle.pack(anchor='w',padx=20,pady=(0,20))
        hero.bind('<Configure>',lambda e:(self.hero_title.configure(wraplength=max(180,e.width-44)),self.hero_subtitle.configure(wraplength=max(180,e.width-44))),add='+')
        quick=tk.Frame(home,bg=self.BG)
        quick.pack(fill='x',padx=28,pady=(0,18))
        self.repair_button=button(self,quick,'Проверить и исправить всё',self.repair_everything,True)
        self.repair_button.pack(side='left')
        label(quick,'Все компоненты одной кнопкой',9,self.DIM).pack(side='left',padx=16)
        modes=section(self,home,'Как должен работать Codex?','Выберите подключение и примените настройки. Для нового режима потребуется новый сеанс Codex.')
        self.official_card=tk.Frame(modes,bg=self.PANEL)
        self.api_card=tk.Frame(modes,bg=self.PANEL)
        for frame,value,title,desc in [(self.official_card,'official','Через аккаунт OpenAI','Официальное подключение с инструментами Hybrid Control'),(self.api_card,'api','Через ваш API','Выбранная модель, API-агенты и локальное управление ПК')]:
            frame.pack(fill='x',padx=20,pady=(0,10))
            tk.Radiobutton(frame,text=title,variable=self.selected_mode,value=value,bg=self.PANEL,fg=self.FG,
                           selectcolor=self.PANEL3,activebackground=self.PANEL,activeforeground=self.FG,
                           font=(cls.HEADING_FONT,11),anchor='w',command=self._selection_changed).pack(anchor='w')
            label(frame,desc,9,self.MUTED,wraplength=580,justify='left').pack(anchor='w',padx=25,pady=(2,6))
        self.pending_label=label(modes,'',9,self.MUTED)
        self.pending_label.pack(anchor='w',padx=20,pady=(0,12))
        row=tk.Frame(modes,bg=self.PANEL);row.pack(fill='x',padx=20,pady=(0,20))
        self.apply_button=button(self,row,'Применить',self.apply_only,True);self.apply_button.pack(side='left')
        self.restart_button=button(self,row,'Применить и перезапустить',self.apply_restart);self.restart_button.pack(side='left',padx=8)
        self.refresh_button=button(self,row,'Обновить',self.refresh);self.refresh_button.pack(side='left')
        health=section(self,home,'Инструменты и компоненты','Статус локальной конфигурации; доступность провайдера проверяется отдельно.')
        for attr,title in [('cap_computer','Управление компьютером'),('cap_browser','Браузер'),('cap_workers','API-агенты'),('cap_native','Нативные агенты'),('cap_setup','Настройка API'),('cap_local_computer','Локальный мост')]:
            row=tk.Frame(health,bg=self.PANEL);row.pack(fill='x',padx=20,pady=6)
            label(row,title,10,self.MUTED).pack(side='left')
            item=label(row,'—',8);item.pack(side='right');setattr(self,attr,item)
        tk.Frame(health,bg=self.PANEL,height=12).pack()

        api=pages['api'];heading(api,'Подключение API','Ключ, модель и использование вашего пакета.')
        setup=section(self,api,'API-ключ','Ключ скрыт при вводе. Сохранённый ключ не отображается в интерфейсе.')
        row=tk.Frame(setup,bg=self.PANEL);row.pack(fill='x',padx=20,pady=(0,14))
        self.token_entry=tk.Entry(row,textvariable=self.token_var,show='•',bg=self.PANEL2,fg=self.FG,insertbackground=self.FG,
                                  relief='flat',font=(cls.BODY_FONT,11))
        self.token_entry.pack(side='left',fill='x',expand=True,ipady=11,padx=(0,8))
        button(self,row,'Вставить',self.paste_token).pack(side='right')
        row=tk.Frame(setup,bg=self.PANEL);row.pack(fill='x',padx=20,pady=(0,12))
        self.activate_button=button(self,row,'Сохранить и настроить',self.activate_api,True);self.activate_button.pack(side='left')
        button(self,row,'Удалить ключ',self.remove_token).pack(side='left',padx=8)
        self.api_activation_status=label(setup,'',9,self.MUTED);self.api_activation_status.pack(anchor='w',padx=20,pady=(0,16))
        options=section(self,api,'Модель и рассуждение')
        self.model_combo=ttk.Combobox(options,textvariable=self.api_model,state='normal')
        self.model_combo.pack(fill='x',padx=20,pady=(0,12))
        self.reason_combo=ttk.Combobox(options,textvariable=self.reasoning_ui,state='readonly',values=list(core.REASONING_EN))
        self.reason_combo.pack(fill='x',padx=20,pady=(0,16))
        self.reason_combo.bind('<<ComboboxSelected>>',lambda e:self.reasoning.set(core.REASONING_EN.get(self.reasoning_ui.get(),'high')))
        action_row(self,options,[('Обновить список моделей',self.refresh_catalog_async,False)])
        usage=section(self,api,'Использование API')
        self.usage_updated_label=label(usage,'Ещё не обновлялось',9,self.MUTED);self.usage_updated_label.pack(anchor='w',padx=20)
        stats=tk.Frame(usage,bg=self.PANEL);stats.pack(fill='x',padx=20,pady=14)
        for attr,title,r,col in [('usage_remaining','ОСТАЛОСЬ ТОКЕНОВ',0,0),('usage_used','ИСПОЛЬЗОВАНО',0,1),('usage_requests','ЗАПРОСОВ',1,0),('usage_gateway','ПРОВАЙДЕР',1,1)]:
            setattr(self,attr,self._stat_card(stats,title,'—',r,col))
        stats.columnconfigure((0,1),weight=1)
        self.usage_progress=ttk.Progressbar(usage,style='Gold.Horizontal.TProgressbar',maximum=100)
        self.usage_progress.pack(fill='x',padx=20,pady=8)
        self.usage_pct_label=label(usage,'Пакет токенов: —',10);self.usage_pct_label.pack(anchor='w',padx=20)
        self.usage_detail_label=label(usage,'',9,self.MUTED,wraplength=600,justify='left');self.usage_detail_label.pack(anchor='w',padx=20,pady=12)
        action_row(self,usage,[('Обновить использование',self.refresh_api_usage_async,False)])

        workers=pages['workers'];heading(workers,'Агенты','Отдельные API-исполнители для реализации, анализа и исследования.')
        profiles=section(self,workers,'Профили агентов')
        self.worker_summary_label=label(profiles,'—',10,self.MUTED);self.worker_summary_label.pack(anchor='w',padx=20,pady=(0,14))
        self.worker_cards={}
        self.worker_model_labels={}
        for name,cfg in core.worker_settings().items():
            row=RoundFrame(profiles,bg=self.PANEL2,border=self.BORDER,radius=11);row.pack(fill='x',padx=20,pady=(0,10))
            label(row,name.capitalize(),12,bold=True).pack(anchor='w',padx=14,pady=(12,3))
            model_label=label(row,cfg['model'],9,self.MUTED);model_label.pack(anchor='w',padx=14)
            self.worker_model_labels[name]=model_label
            status=label(row,'—',9,self.MUTED);status.pack(anchor='w',padx=14,pady=(7,12));self.worker_cards[name]=status
        action_row(self,profiles,[('Открыть монитор агентов',self.open_worker_center,True)])
        delegation=section(self,workers,'Делегирование')
        for text,value in [('Только API-агенты','api_only'),('Разрешить нативных агентов в официальном режиме','hybrid')]:
            tk.Radiobutton(delegation,text=text,variable=self.delegation_policy,value=value,command=self._selection_changed,
                           bg=self.PANEL,fg=self.FG,selectcolor=self.PANEL3,activebackground=self.PANEL,activeforeground=self.FG).pack(anchor='w',padx=20,pady=5)
        self.delegation_hint=label(delegation,'',9,self.MUTED,wraplength=600,justify='left');self.delegation_hint.pack(anchor='w',padx=20,pady=(8,18))

        tools=pages['tools'];heading(tools,'Ваши инструменты','Локальная работа с компьютером, чтение страниц и чат с продолжением.')
        for title,desc,caption,command in [
            ('Управление компьютером','Снимки экрана, окна, мышь и клавиатура через локальный Windows-мост.','Открыть управление ПК',self.open_computer_bridge),
            ('Браузер для агента','Загрузка текста и ссылок страниц. Страницы с JavaScript и входом открывайте в обычном браузере через управление ПК.','Открыть браузер',self.open_agent_browser),
            ('Чат с продолжением','Сохранение истории и ограниченное восстановление при сбоях API. Ошибка провайдера остаётся видимой, если восстановление не помогло.','Открыть чат',self.open_hybrid_chat)]:
            card=section(self,tools,title,desc);action_row(self,card,[(caption,command,False)])

        recovery=pages['recovery'];heading(recovery,'Восстановление','Проверка всей настройки и обратимое отключение Hybrid Control.')
        service=section(self,recovery,'Диагностика и исправление','В API-режиме контроль ограничивает запрос 180 секундами, тишину — 60 секундами. Ответ появляется после проверки целиком. Результат каждого шага ремонта появится ниже.')
        action_row(self,service,[('Проверить и исправить всё',self.repair_everything,True),('Экспорт отчёта',self.export_diagnostics,False)])
        self.repair_report=tk.Text(service,bg=self.PANEL,fg=self.MUTED,relief='flat',height=9,font=(cls.BODY_FONT,10),wrap='word',padx=20,pady=10)
        self.repair_report.pack(fill='x',pady=(0,14));self.repair_report.insert('1.0','Проверка ещё не запускалась.');self.repair_report.configure(state='disabled')
        stock=section(self,recovery,'Обычный Codex','Отключить настройки, мосты и инструкции Hybrid Control. История чатов и вход в аккаунт сохраняются. Для возврата используется снимок настроек.')
        self.stock_hint=label(stock,'',9,self.MUTED,wraplength=620,justify='left');self.stock_hint.pack(anchor='w',padx=20,pady=(0,12))
        action_row(self,stock,[('Вернуть обычный Codex',self.switch_stock,False),('Восстановить Hybrid',self.switch_hybrid,False)])
        env=section(self,recovery,'Состояние настройки')
        for attr in ['key_label','workers_label','worker_bridge_label','catalog_label','config_label']:
            item=label(env,'',9,self.MUTED,wraplength=620,justify='left');item.pack(anchor='w',padx=20,pady=(0,10));setattr(self,attr,item)
        action_row(self,env,[('Открыть папку настроек',core.open_codex_folder,False)])
        from hybrid_service_ui import build_services
        build_services(core,self,pages,section,action_row,label)
        for variable in [self.selected_mode,self.api_model,self.reasoning,self.delegation_policy]:
            variable.trace_add('write',lambda *_:self._selection_changed())
        self.bind_all('<MouseWheel>',self._global_mousewheel,add='+')
        self.bind('<Control-r>',lambda e:self.refresh())
        for index in range(5):
            self.bind(f'<Control-Key-{index+1}>',lambda e,i=index:select(i))
        select(0)

    def update_cards(self):
        # Mode radios already expose selection; avoid repainting the page tree.
        self._update_pending_state()

    def scrollable(self, parent, title, name=None):
        outer=tk.Frame(parent,bg=self.BG)
        self.tabs[name]=outer
        canvas=tk.Canvas(outer,bg=self.BG,highlightthickness=0,bd=0)
        bar=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview,style='Shell.Vertical.TScrollbar')
        body=tk.Frame(canvas,bg=self.BG)
        item=canvas.create_window((0,0),window=body,anchor='nw')
        def sync(event=None):
            region=canvas.bbox('all')
            canvas.configure(scrollregion=region)
            if region and region[3]>canvas.winfo_height()+1:
                if not bar.winfo_manager():bar.pack(side='right',fill='y',before=canvas)
            else:bar.pack_forget()
        body.bind('<Configure>',sync)
        def resize(event):
            canvas.itemconfigure(item,width=max(1,event.width))
            sync()
        canvas.bind('<Configure>',resize)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side='left',fill='both',expand=True)
        self._scroll_targets.append((body,canvas))
        return body

    def pending(self):
        if not self._actual_info:return
        applied=self._selection_is_applied()
        self.pending_label.configure(text='Настройки применены' if applied else 'Есть неприменённые изменения',fg=self.MUTED if applied else self.AMBER)
        self.restart_button.configure(text='Перезапустить Codex' if applied else 'Применить и перезапустить')

    def refresh(self):
        original_refresh(self)
        for name,cfg in core.worker_settings().items():self.worker_model_labels[name].configure(text=cfg['model'])
        stock=getattr(core,'is_stock_mode',lambda:False)()
        self.stock_hint.configure(text='Сейчас включён обычный Codex. Hybrid Control отключён.' if stock else 'Hybrid Control включён. Перед отключением будет сохранён снимок.')
        self.activate_button.configure(text='Сохранить и настроить')
        if stock:
            import hybrid_recovery
            phase=hybrid_recovery.stock_state(core).get('phase','stock')
            self.hero_title.configure(text='Обычный Codex')
            self.hero_subtitle.configure(text='Настройки Hybrid Control отключены. Снимок доступен в разделе восстановления.')
            self.mode_badge.configure(text='Обычный Codex')
            self.status.set('Обычный Codex · интеграции Hybrid Control отключены')
            if phase!='stock':
                self.hero_title.configure(text='Переключение было прервано')
                self.hero_subtitle.configure(text='Исходные файлы сохранены. Откройте восстановление и нажмите «Восстановить Hybrid».')
                self.status.set('Требуется восстановить прерванное переключение')
            for attr in ['cap_computer','cap_browser','cap_workers','cap_setup','cap_local_computer']:
                self._set_cap(getattr(self,attr),'ОТКЛЮЧЕНО', 'muted')
        elif self._actual_info.get('provider')==core.API_PROVIDER:
            self.hero_title.configure(text=self._actual_info.get('model','API'))
            self.hero_subtitle.configure(text='Подключение через ваш API · локальные инструменты Hybrid Control')
            self.mode_badge.configure(text='Через API')
        else:
            self.hero_title.configure(text='Аккаунт OpenAI')
            self.hero_subtitle.configure(text='Официальное подключение · инструменты Hybrid Control')
            self.mode_badge.configure(text='Через OpenAI')
            if not self._busy:self.status.set('Подключение через OpenAI · настройки доступны в разделах слева')

    def report(self,text):
        self.repair_report.configure(state='normal');self.repair_report.delete('1.0','end')
        self.repair_report.insert('1.0',text);self.repair_report.configure(state='disabled')

    def repair(self):
        if self._busy:return
        self.notebook.select(4)
        report(self,'Проверяем конфигурацию, профили, инструкции и локальные мосты…')
        def done(result):
            lines=[]
            for step in result.get('steps',[]):
                lines.append(f"{step.get('name','Проверка')} · {step.get('status','')}\n{step.get('detail','')}\n")
            report(self,'\n'.join(lines) or str(result))
            self.refresh()
            self.status.set('Проверка завершена.' if result.get('ok') else 'Проверка завершена: есть пункты, требующие внимания.')
        self._run_background('Проверка и восстановление…',lambda:core.repair_all(self.state_obj.config_path),done)

    def stock(self):
        if self._busy:return
        if not messagebox.askyesno('Обычный Codex','Сохранить снимок и отключить интеграции Hybrid Control?\n\nЧаты и авторизация сохранятся. После этого перезапустите Codex.',parent=self):return
        def done(result):
            if isinstance(result,dict) and result.get('ok') is False:
                report(self,str(result));self.status.set('Отключение не завершено. Подробности в отчёте.');return
            self.refresh();report(self,'Настройки Hybrid Control сохранены в снимке. Интеграции отключены.\n\nПерезапустите Codex и создайте новый сеанс. Для возврата используйте «Восстановить Hybrid».');self.status.set('Обычный Codex настроен. Перезапустите Codex и создайте новый сеанс.')
        self._run_background('Сохранение снимка и отключение интеграций…',lambda:core.enter_stock_mode(self.state_obj.config_path),done)

    def restore(self):
        if self._busy:return
        def done(result):
            if isinstance(result,dict) and result.get('ok') is False:
                report(self,str(result));self.status.set('Восстановление не завершено. Подробности в отчёте.');return
            self.refresh();report(self,'Сохранённые настройки Hybrid Control восстановлены.\n\nПерезапустите Codex и создайте новый сеанс.');self.status.set('Hybrid Control восстановлен. Перезапустите Codex и создайте новый сеанс.')
        self._run_background('Восстановление Hybrid Control…',lambda:core.restore_hybrid_mode(self.state_obj.config_path),done)

    def background(self, start_message, fn, done):
        if self._busy:
            return
        self._busy=True
        self.status.set(start_message)
        self.footer_dot.configure(fg=self.AMBER)
        controls=[self.activate_button,self.apply_button,self.restart_button,self.repair_button]
        for widget in controls:widget.configure(state='disabled')
        results=queue.Queue()
        def run():
            try:results.put((True,fn()))
            except Exception as error:results.put((False,error))
        def poll():
            try:ok,result=results.get_nowait()
            except queue.Empty:
                self.after(80,poll)
                return
            self._busy=False
            for widget in controls:widget.configure(state='normal')
            self.footer_dot.configure(fg=self.GREEN if ok else self.RED)
            if ok:
                try:done(result)
                except Exception as error:
                    self.status.set(f'Ошибка обновления интерфейса: {error}')
                    report(self,str(error))
            else:
                self.status.set(f'Не удалось завершить: {result}')
                report(self,str(result))
                if not self._close_requested:messagebox.showerror('Не удалось завершить действие',str(result),parent=self)
            if self._close_requested:self.destroy()
        threading.Thread(target=run,daemon=True).start()
        self.after(80,poll)

    def guarded_apply(self, restart):
        if getattr(core,'is_stock_mode',lambda:False)():
            self.notebook.select(4)
            self.status.set('Сначала восстановите Hybrid Control из снимка.')
            return False
        return original_apply(self,restart)

    def guarded_activate(self):
        if getattr(core,'is_stock_mode',lambda:False)():
            self.notebook.select(4)
            self.status.set('Сначала восстановите Hybrid Control из снимка.')
            return
        return original_activate(self)

    def usage(self):
        if getattr(core,'is_stock_mode',lambda:False)():
            self._render_usage_unavailable('Hybrid Control отключён', 'muted')
            return
        return original_usage(self)

    def browser(parent=None):
        win=tk.Toplevel(parent) if parent else tk.Tk()
        win.title('Браузер для агента · Hybrid Control')
        win.configure(bg=cls.BG);win.geometry('920x680');win.minsize(640,440)
        install_chrome(win,'Браузер для агента',cls.BODY_FONT)
        label(win,'Браузер для агента',22,bold=True).pack(anchor='w',padx=24,pady=(24,7))
        label(win,'Читайте страницы и переходите по ссылкам. Без JavaScript и входа в аккаунты.',10,cls.MUTED).pack(anchor='w',padx=24,pady=(0,20))
        bar=tk.Frame(win,bg=cls.BG);bar.pack(fill='x',padx=24,pady=(0,16))
        url=tk.StringVar(win,value='https://example.com')
        entry=tk.Entry(bar,textvariable=url,bg=cls.PANEL2,fg=cls.FG,insertbackground=cls.FG,bd=0,font=(cls.BODY_FONT,11))
        entry.pack(side='left',fill='x',expand=True,ipady=12,padx=(0,10))
        status=tk.StringVar(win,value='Введите адрес страницы')
        busy=[False]
        body=tk.Frame(win,bg=cls.PANEL);body.pack(fill='both',expand=True,padx=24,pady=(0,12))
        output=tk.Text(body,bg=cls.PANEL,fg=cls.FG,insertbackground=cls.FG,relief='flat',bd=0,
                       wrap='word',padx=20,pady=20,font=(cls.BODY_FONT,11),state='disabled')
        sb=ttk.Scrollbar(body,orient='vertical',command=output.yview,style='Shell.Vertical.TScrollbar')
        sb.pack(side='right',fill='y');output.pack(fill='both',expand=True);output.configure(yscrollcommand=sb.set)
        output.tag_configure('title',font=(cls.HEADING_FONT,18),spacing3=18)
        output.tag_configure('meta',foreground=cls.MUTED,spacing3=18)
        output.tag_configure('link',foreground='#8ab4f8',spacing1=8)
        tk.Label(win,textvariable=status,bg=cls.BG,fg=cls.MUTED,font=(cls.BODY_FONT,9),anchor='w').pack(fill='x',padx=24,pady=(0,16))
        def fetch():
            if busy[0]:return
            target=url.get().strip()
            if not target:return
            busy[0]=True;load.configure(state='disabled');status.set('Загружаем страницу…')
            results=queue.Queue()
            def work():
                try:results.put(core.browser_fetch(target))
                except Exception as error:results.put({'ok':False,'error':str(error)})
            def poll():
                if not win.winfo_exists():return
                try:result=results.get_nowait()
                except queue.Empty:
                    win.after(80,poll);return
                busy[0]=False;load.configure(state='normal')
                output.configure(state='normal');output.delete('1.0','end')
                for tag in output.tag_names():
                    if tag.startswith('url_'):output.tag_delete(tag)
                if result.get('ok'):
                    url.set(result.get('url',target))
                    output.insert('end',(result.get('title') or 'Страница')+'\n','title')
                    output.insert('end',result.get('url',target)+'\n','meta')
                    output.insert('end',result.get('text',''))
                    links=result.get('links',[])
                    if links:output.insert('end','\n\nСсылки\n','title')
                    for i,href in enumerate(links):
                        tag=f'url_{i}';output.insert('end',href+'\n',('link',tag))
                        output.tag_bind(tag,'<Button-1>',lambda event,address=href:(url.set(address),fetch()))
                        output.tag_bind(tag,'<Enter>',lambda event:output.configure(cursor='hand2'))
                        output.tag_bind(tag,'<Leave>',lambda event:output.configure(cursor='xterm'))
                    status.set(f"Загружено · {result.get('chars',0):,} символов · HTTP {result.get('status','—')}")
                else:
                    output.insert('end','Не удалось загрузить страницу\n','title')
                    output.insert('end',result.get('error','Неизвестная ошибка'))
                    status.set('Проверьте адрес и подключение, затем повторите загрузку')
                output.configure(state='disabled')
            threading.Thread(target=work,daemon=True).start();win.after(80,poll)
        load=RoundButton(bar,text='Открыть',command=fetch,bg=cls.FG,fg=cls.BG,bd=0,padx=20,pady=11,font=(cls.BODY_FONT,10))
        load.pack(side='right');entry.bind('<Return>',lambda event:fetch())
        if parent is None:win.mainloop()
        return win

    def computer(self):
        win=tk.Toplevel(self);win.title('Управление компьютером · Hybrid Control')
        win.configure(bg=self.BG);win.geometry('820x760');win.minsize(620,540)
        install_chrome(win,'Управление компьютером',cls.BODY_FONT)
        shell=tk.Frame(win,bg=self.BG);shell.pack(fill='both',expand=True)
        canvas=tk.Canvas(shell,bg=self.BG,bd=0,highlightthickness=0)
        scrollbar=ttk.Scrollbar(shell,orient='vertical',command=canvas.yview,style='Shell.Vertical.TScrollbar')
        scrollbar.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        body=tk.Frame(canvas,bg=self.BG);item=canvas.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        win.bind('<MouseWheel>',lambda e:(canvas.yview_scroll(-int(e.delta/120),'units'),'break')[1])
        heading(body,'Управление компьютером','Разрешения локального моста для API-агента на этом компьютере.')
        card=section(self,body,'Разрешения')
        policy=core.computer_policy()
        flags={}
        for key,text in [('enabled','Включить локальный мост'),('allow_screenshot','Снимки экрана'),('allow_input','Управление мышью и клавиатурой'),('allow_launch','Запуск приложений')]:
            var=tk.BooleanVar(win,value=bool(policy.get(key)))
            flags[key]=var
            tk.Checkbutton(card,text=text,variable=var,bg=self.PANEL,fg=self.FG,selectcolor=self.PANEL3,
                           activebackground=self.PANEL,activeforeground=self.FG,font=(cls.BODY_FONT,11),pady=7).pack(anchor='w',padx=20)
        control_mode=tk.StringVar(win,value=policy.get('control_mode','auto'))
        for value,text in [('auto','Авто · элементы Windows и браузера, мышь и клавиатура'),('mouse','Только настоящая мышь и клавиатура')]:
            tk.Radiobutton(card,text=text,variable=control_mode,value=value,bg=self.PANEL,fg=self.FG,selectcolor=self.PANEL3,
                           activebackground=self.PANEL,activeforeground=self.FG,font=(cls.BODY_FONT,10)).pack(anchor='w',padx=20,pady=5)
        def save():
            try:
                core.save_computer_policy({**policy,**{key:var.get() for key,var in flags.items()},'control_mode':control_mode.get()})
                self.refresh();local_status.set('Разрешения сохранены')
            except Exception as error:local_status.set(str(error))
        action_row(self,card,[('Сохранить разрешения',save,True)])
        check=section(self,body,'Подключение и проверка','Восстановление использует общую проверку всех компонентов. Снимок экрана выполняется только при запуске проверки.')
        def repair_from_window():
            win.destroy();self.repair_everything()
        def verify():
            def done(result):
                import json
                if win.winfo_exists():local_status.set(json.dumps(result,ensure_ascii=False,indent=2))
            self._run_background('Проверка локального моста…',lambda:core.computer_bridge_self_test(self.state_obj.config_path),done)
        action_row(self,check,[('Проверить и исправить всё',repair_from_window,False),('Проверить мост',verify,False)])
        local_status=tk.StringVar(win,value='Разрешения применяются к локальным инструментам Hybrid Control.')
        tk.Label(win,textvariable=local_status,bg=self.BG,fg=self.MUTED,font=(cls.BODY_FONT,9),justify='left',wraplength=710).pack(anchor='w',padx=28,pady=(0,20))
        return win

    def polish_window(win):
        first=next(iter(win.pack_slaves()),None)
        if not hasattr(win,'_custom_chrome'):
            chrome=install_chrome(win,win.title(),cls.BODY_FONT)
            if first:chrome.pack_configure(before=first)
        replacements={
            'МОНИТОР API-ВОРКЕРОВ':'Агенты и задачи',
            'ГИБРИДНЫЙ ЧАТ С НЕПРЕРЫВНОСТЬЮ':'Чат с продолжением',
            'ЗАПУСТИТЬ ВОРКЕРА':'Запустить агента',
            'ОТПРАВИТЬ ЧЕРЕЗ CODEX':'Отправить',
            'Ограниченная инструкция для воркера':'Задание для агента',
            'ЧАТЫ':'Ваши чаты',
        }
        def walk(parent):
            for widget in list(parent.winfo_children()):
                try:
                    if 'text' in widget.keys() and widget.cget('text') in replacements:
                        widget.configure(text=replacements[widget.cget('text')])
                    if isinstance(widget,tk.Text) and widget.cget('bg')=='#111114':widget.configure(bg=cls.BG)
                    if isinstance(widget,tk.Scrollbar) and not isinstance(widget,ttk.Scrollbar) and widget.winfo_manager()=='pack':
                        parts=widget.tk.splitlist(widget.cget('command'))
                        info=widget.pack_info();info.pop('in',None)
                        siblings=widget.master.pack_slaves();idx=siblings.index(widget)
                        bar=ttk.Scrollbar(widget.master,orient=widget.cget('orient'),command=widget.cget('command'),
                                          style='Shell.Vertical.TScrollbar' if widget.cget('orient')=='vertical' else 'Horizontal.TScrollbar')
                        if idx+1<len(siblings):info['before']=siblings[idx+1]
                        widget.pack_forget();bar.pack(**info)
                        if len(parts)==2:
                            target=win.nametowidget(parts[0])
                            target.configure(**{'yscrollcommand' if parts[1]=='yview' else 'xscrollcommand':bar.set})
                        else:
                            option='yscrollcommand' if widget.cget('orient')=='vertical' else 'xscrollcommand'
                            for target in widget.master.winfo_children():
                                if option in target.keys():target.configure(**{option:bar.set})
                    else:walk(widget)
                except tk.TclError:pass
        walk(win)

    def legacy_button(self,parent,text,command,bg,fg,padx=14,pady=7):
        return RoundButton(parent,text=text,command=command,bg=bg,fg=fg,activeforeground=fg,
                           activebackground='#454c55' if fg!=self.BG and fg!='#111' else '#f0f3f6',
                           font=(cls.BODY_FONT,10),padx=padx,pady=pady,radius=9)

    cls._build_ui=build
    cls._create_scrollable_tab=scrollable
    cls._section=section
    cls._button=legacy_button
    cls._update_cards=update_cards
    cls._update_pending_state=pending
    cls.refresh=refresh
    cls.repair_everything=repair
    cls.switch_stock=stock
    cls.switch_hybrid=restore
    cls._run_background=background
    cls._apply=guarded_apply
    cls.activate_api=guarded_activate
    cls.refresh_api_usage_async=usage
    core.open_browser_window=browser
    cls.open_computer_bridge=computer
    for method in ['open_worker_center','open_computer_bridge','open_hybrid_chat']:
        original=getattr(cls,method)
        def guarded_tool(self,callback=original):
            if getattr(core,'is_stock_mode',lambda:False)():
                self.notebook.select(4)
                self.status.set('Инструменты Hybrid Control отключены. Сначала восстановите сохранённую настройку.')
                return
            before=set(self.winfo_children())
            result=callback(self)
            for window in self.winfo_children():
                if isinstance(window,tk.Toplevel) and window not in before:polish_window(window)
            return result
        setattr(cls,method,guarded_tool)
    from hybrid_service_ui import install_services
    install_services(core)
