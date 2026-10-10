"""Additional MCP surface; cursor tools remain available alongside direct access."""
import json
import time
import uuid
from hybrid_actions import ActionJournal, serialized


def extend_tools(tools):
    tools = list(tools)
    tools += [
        {'name':'computer_elements','description':'Read bounded Windows UI Automation elements of a window. No screenshots or field values. Get new IDs after mutations.',
         'inputSchema':{'type':'object','properties':{'hwnd':{'type':'integer'},'limit':{'type':'integer','minimum':1,'maximum':400}},'required':['hwnd'],'additionalProperties':False}},
        {'name':'computer_element_action','description':'Invoke or set a Windows element through UI Automation. Input policy applies. Set value is verified; invoke needs a separate expected-state check.',
         'inputSchema':{'type':'object','properties':{'element_id':{'type':'string'},'operation':{'type':'string','enum':['invoke','set_value']},'value':{'type':'string'}},'required':['element_id','operation'],'additionalProperties':False}},
        {'name':'browser_control','description':'Separate Chrome/Edge session: start, tabs, navigate, inspect DOM, click/fill by fresh element ID. Cursor tools remain available. No arbitrary JavaScript. Password fields require manual input.',
         'inputSchema':{'type':'object','properties':{'operation':{'type':'string','enum':['start','close','tabs','navigate','inspect','click','fill']},'tab_id':{'type':'string'},'url':{'type':'string'},'element_id':{'type':'string'},'value':{'type':'string'}},'required':['operation'],'additionalProperties':False}},
        {'name':'computer_wait_for','description':'Wait until a window/title and optionally a UI Automation element name appear. Bounded wait; return evidence, never claim a click achieved its business goal.',
         'inputSchema':{'type':'object','properties':{'title_contains':{'type':'string'},'hwnd':{'type':'integer'},'element_name':{'type':'string'},'timeout':{'type':'number','minimum':0,'maximum':20}},'additionalProperties':False}},
        {'name':'computer_action_status','description':'Read persistent receipt after API/bridge interruption. Completed actions must not be replayed; running/unknown outcomes require inspection.',
         'inputSchema':{'type':'object','properties':{'action_id':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':30}},'additionalProperties':False}},
    ]
    mutating = {'computer_focus_window','computer_mouse_move','computer_click','computer_drag','computer_scroll',
                'computer_type','computer_hotkey','computer_key','computer_launch_app','computer_act',
                'computer_element_action','browser_control'}
    for tool in tools:
        if tool['name'] in {'computer_status','computer_list_windows','computer_screenshot','computer_elements',
                            'computer_wait','computer_wait_for','computer_action_status'}:
            tool['annotations']={'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False}
        if tool['name'] in mutating:
            tool['inputSchema']['properties']['action_id'] = {'type':'string','pattern':'^[A-Za-z0-9_-]{1,80}$',
                'description':'Stable ID for this exact action across disconnects. Reusing it never repeats a completed action.'}
    return tools


def direct_call(core, name, args):
    if name == 'computer_elements':
        from hybrid_accessibility import Accessibility
        return Accessibility(core).inspect(args['hwnd'], args.get('limit',180))
    if name == 'computer_element_action':
        from hybrid_accessibility import Accessibility
        return Accessibility(core).act(args['element_id'],args['operation'],args.get('value'))
    if name == 'browser_control':
        from hybrid_browser_control import BrowserControl
        browser = BrowserControl(core)
        operation = args['operation']
        if operation == 'start': return browser.start()
        if operation == 'close': return browser.close()
        if operation == 'tabs': return {'ok':True,'tabs':browser.tabs()}
        if operation == 'inspect': return browser.inspect(args['tab_id'])
        if operation == 'navigate': return browser.navigate(args['tab_id'],args['url'])
        return browser.act(args['tab_id'],args['element_id'],operation,args.get('value'))
    if name == 'computer_wait_for':
        if not core.computer_policy().get('enabled'): raise RuntimeError('Локальный мост отключён')
        if not args.get('hwnd') and not args.get('title_contains'):
            raise ValueError('Укажите hwnd или title_contains для проверки')
        deadline = time.monotonic()+min(20,max(0,float(args.get('timeout',10))))
        while True:
            target = core._resolve_window(args)
            if target:
                if not args.get('element_name'):
                    return {'ok':True,'verified':True,'condition':'window_exists','window':target}
                from hybrid_accessibility import Accessibility
                snapshot = Accessibility(core).inspect(target['hwnd'])
                matches = [e for e in snapshot.get('elements',[]) if e.get('name') == args['element_name']]
                if matches:
                    return {'ok':True,'verified':True,'condition':'element_exists','elements':matches}
            if time.monotonic()>=deadline:
                return {'ok':False,'verified':False,'error':'Ожидаемое состояние не появилось за указанный срок'}
            time.sleep(.15)
    raise ValueError('Unknown direct computer tool')


def call(core, legacy, name, arguments):
    args = dict(arguments)
    action_id = args.pop('action_id', None)
    if name == 'computer_action_status':
        journal=ActionJournal(core)
        return json.dumps(journal.status(action_id) if action_id else {'actions':journal.recent(args.get('limit',10))},ensure_ascii=False)
    direct = name in {'computer_elements','computer_element_action','browser_control','computer_wait_for'}
    mutating = name in {'computer_focus_window','computer_mouse_move','computer_click','computer_drag','computer_scroll',
                       'computer_type','computer_hotkey','computer_key','computer_launch_app','computer_act','computer_element_action'}
    mutating |= name=='browser_control' and args.get('operation') not in {'tabs','inspect'}
    def execute():
        if mutating and core._track_tool_call('computer:'+name,args):
            raise RuntimeError('Повторяющееся действие остановлено. Проверьте результат и измените подход.')
        result = direct_call(core,name,args) if direct else legacy(name,args)
        return result
    if mutating:
        if core.is_stock_mode(): raise RuntimeError('Hybrid Control отключён')
        action_id=action_id or uuid.uuid4().hex
        # Both legacy cursor actions and direct controls use the same process lock.
        if action_id and name != 'computer_act':
            result = ActionJournal(core).execute(action_id,name,args,execute)
        elif action_id and name == 'computer_act':
            actions = args.get('actions')
            if not isinstance(actions,list) or not 1<=len(actions)<=20:
                raise ValueError('Пакет должен содержать 1–20 действий')
            if sum(float(a.get('seconds',0)) for a in actions if a.get('type')=='wait')>45:
                raise ValueError('Ожидание в пакете превышает 45 секунд')
            def execute_step(action):
                if action.get('type')!='wait' and core._track_tool_call('computer:computer_step',action):
                    raise RuntimeError('Повторяющийся шаг пакета остановлен; проверьте окно')
                return core._execute_computer_action(action)
            results = ActionJournal(core).batch(action_id,actions,execute_step)
            # Receipts are already durable before image capture. A failed capture
            # cannot cause completed steps to run a second time.
            shot = core._screenshot_content(args.get('screenshot') or {})
            shot.insert(0,{'type':'text','text':json.dumps({'action_id':action_id,'actions':results,
                          'verification_screenshot':True},ensure_ascii=False)})
            return shot
        if isinstance(result,str):
            try:result=json.loads(result)
            except ValueError:pass
        if isinstance(result,dict):result.setdefault('action_id',action_id)
    else: result = execute()
    return json.dumps(result,ensure_ascii=False) if isinstance(result,dict) else result
