import json
import pytest
import codex_hybrid_control as c
import hybrid_stop_guard as guard


@pytest.fixture
def event(tmp_path):
    path=tmp_path/'sessions'/'turn.jsonl';path.parent.mkdir()
    path.write_text('\n'.join(json.dumps(row) for row in [
        {'type':'session_meta','payload':{'model_provider':'funpay'}},
        {'type':'event_msg','payload':{'type':'user_message','message':'Исправь программу'}},
        {'type':'response_item','payload':{'type':'function_call','name':'exec_command'}},
    ]),encoding='utf-8')
    return {'hook_event_name':'Stop','stop_hook_active':False,'session_id':'s','turn_id':'t',
            'transcript_path':str(path),'last_assistant_message':'Запущено. Проверяю:</think></arg_value>'}


def test_real_malformed_final_continues_once(event,tmp_path):
    assert guard.decide(event,tmp_path)['decision']=='block'
    assert guard.decide(event,tmp_path)=={}
    assert guard.decide({**event,'turn_id':'second','stop_hook_active':True},tmp_path)=={}


@pytest.mark.parametrize('answer',[
    'Запущено с правильным data root. Проверяю:Запущено с правильным data\n\nr\nЗапущено с правильным data root. Проверяю:</think></arg_value>',
    'Ollama app запущен, но сервер не отвечает — завис. Перезапускаю сервис:Ollama app запущен, но сервер не отвечает —\nпер\nOllama app запущен, но сервер не отвечает —\nзав',
    'Сервер не поднялся. Проверяю процессы:',
    '</think>Сервер остановлен. Перезапускаю с новыми правками и прове\n</think>Сервер остановлен. Перезапускаю с новыми правками и прове',
    '</think>Продолжаю. Перезапускаю сервер:',
    None,
    '',
])
def test_screenshot_regressions(event,tmp_path,answer):
    assert guard.decide({**event,'last_assistant_message':answer},tmp_path)['decision']=='block'


@pytest.mark.parametrize('answer',[
    'Готово. Исправление проверено, тесты прошли.',
    'В ответе был тег `</think>`.',
    'Пример:\n```xml\n</think>\n```',
    '> Проверяю:</think>',
    'Ответ содержал `</think>` в начале и `</think>` в середине.',
    'Нужно ваше подтверждение. Продолжать?',
    'Нет доступа. Проверю после подключения.',
])
def test_valid_answers_not_continued(event,tmp_path,answer):
    assert guard.decide({**event,'last_assistant_message':answer},tmp_path)=={}


def test_official_unknown_provider_and_manual_interrupt_not_continued(event,tmp_path):
    path=event['transcript_path']
    from pathlib import Path
    for provider in ['openai','unknown']:
        Path(path).write_text(json.dumps({'type':'session_meta','payload':{'model_provider':provider}}))
        assert guard.decide(event,tmp_path)=={}
    assert guard.decide({**event,'hook_event_name':'Interrupt'},tmp_path)=={}


def test_stock_disabled(event,tmp_path):
    folder=tmp_path/'hybrid-control';folder.mkdir()
    (folder/'restore-point.json').write_text('{"active":true}')
    assert guard.decide(event,tmp_path)=={}


def test_installer_preserves_other_hooks_and_is_idempotent(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    path=c.default_config_path().parent/'hooks.json';path.parent.mkdir()
    original={'hooks':{'Stop':[{'hooks':[{'type':'command','command':'echo user'}]}]}}
    path.write_text(json.dumps(original),encoding='utf-8')
    guard.install(c,c.default_config_path())
    once=path.read_bytes();guard.install(c,c.default_config_path())
    assert path.read_bytes()==once
    assert guard.clean_hooks(json.loads(once))==original


def test_malformed_hooks_not_overwritten(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    path=c.default_config_path().parent/'hooks.json';path.parent.mkdir()
    path.write_text('{broken')
    with pytest.raises(ValueError):guard.install(c,c.default_config_path())
    assert path.read_text()=='{broken'


def append_result(event, name='exec_command', arguments='{"cmd":"test"}', output='done'):
    from pathlib import Path
    with Path(event['transcript_path']).open('a', encoding='utf-8') as stream:
        for kind, extra in [('function_call', {'name':name, 'arguments':arguments}),
                            ('function_call_output', {'output':output})]:
            stream.write('\n'+json.dumps({'type':'response_item','payload':{'type':kind,'call_id':'latest',**extra}}))


def test_continuation_renews_only_with_distinct_results(event,tmp_path):
    assert guard.decide(event,tmp_path)['decision']=='block'
    active={**event,'stop_hook_active':True}
    assert guard.decide(active,tmp_path)=={}
    append_result(event, output='first result')
    assert guard.decide(active,tmp_path)['decision']=='block'
    append_result(event, output='first result')
    assert guard.decide(active,tmp_path)=={}
    for number in range(4):
        append_result(event, output=str(number))
        assert guard.decide(active,tmp_path)['decision']=='block'
    append_result(event, output='new but budget exhausted')
    assert guard.decide(active,tmp_path)=={}


def test_changing_shell_timing_is_not_progress(event,tmp_path):
    append_result(event, output=json.dumps({'output':'same','wall_time_seconds':1}))
    assert guard.decide(event,tmp_path)['decision']=='block'
    append_result(event, output=json.dumps({'output':'same','wall_time_seconds':2}))
    assert guard.decide({**event,'stop_hook_active':True},tmp_path)=={}


def test_open_plan_needs_reconciliation_and_respects_blockers(event,tmp_path):
    append_result(event, name='update_plan', arguments=json.dumps({'plan':[{'step':'Test','status':'in_progress'}]}))
    assert guard.decide({**event,'last_assistant_message':'Готово.'},tmp_path)['decision']=='block'
    assert guard.decide({**event,'turn_id':'blocked','last_assistant_message':'Нет доступа, нужно ваше подтверждение.'},tmp_path)=={}
    append_result(event, name='update_plan', arguments=json.dumps({'plan':[{'step':'Test','status':'completed'}]}))
    assert guard.decide({**event,'turn_id':'done','last_assistant_message':'Готово.'},tmp_path)=={}


@pytest.mark.parametrize('text',['Запускаю новую mission.', '**Перехожу к проверке.**', "I'll run the tests.", 'Running the final checks:'])
def test_future_action_announcements(event,tmp_path,text):
    assert guard.decide({**event,'last_assistant_message':text},tmp_path)['decision']=='block'


def test_long_transcript_does_not_reuse_old_stop_prompt(event,tmp_path):
    from pathlib import Path
    rows=[{'type':'session_meta','payload':{'model_provider':'funpay'}},
          {'type':'event_msg','payload':{'type':'user_message','message':'стоп'}},
          {'type':'event_msg','payload':{'type':'old_data','message':'x'*70000}},
          {'type':'event_msg','payload':{'type':'user_message','message':'Исправь программу'}},
          {'type':'event_msg','payload':{'type':'large_data','message':'x'*600000}},
          {'type':'response_item','payload':{'type':'function_call','name':'exec_command','call_id':'last','arguments':'{}'}}]
    Path(event['transcript_path']).write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8')
    assert guard.decide(event,tmp_path)['decision']=='block'


def test_protocol_damage_does_not_override_real_question(event,tmp_path):
    assert guard.decide({**event,'last_assistant_message':'</think>Нужно ваше подтверждение. Продолжать?'},tmp_path)=={}
