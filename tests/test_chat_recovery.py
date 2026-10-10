import json
import subprocess
from types import SimpleNamespace
import pytest
import codex_hybrid_control as c
from hybrid_chat import repeated_answer


def events(answer=None,complete=False,tool=False):
    rows=[{'type':'thread.started','thread_id':'thread-one'}]
    if tool:rows.append({'type':'item.completed','item':{'type':'command_execution','command':'modify file'}})
    if answer is not None:rows.append({'type':'item.completed','item':{'type':'agent_message','text':answer}})
    if complete:rows.append({'type':'turn.completed'})
    return '\n'.join(json.dumps(row) for row in rows)


@pytest.fixture
def chat(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    return c.new_hybrid_chat(tmp_path)


def test_empty_answer_retries_once_and_keeps_both_logs(chat,tmp_path,monkeypatch):
    replies=[events(),events('A valid answer',True)];calls=[]
    def run(*args,**kwargs):
        calls.append(kwargs['timeout']);return SimpleNamespace(returncode=0,stdout=replies.pop(0),stderr='')
    monkeypatch.setattr(c,'run_bounded_process',run)
    log=tmp_path/'turn.jsonl'
    result=c.run_hybrid_chat_turn(chat,'hello','api','model','high',log,30)
    assert result['attempts']==2 and len(chat['messages'])==2
    assert calls[1]<=calls[0]
    assert log.read_text(encoding='utf-8').count('hybrid.attempt')==2


def test_incomplete_after_tool_is_not_replayed(chat,tmp_path,monkeypatch):
    calls=[]
    def run(*args,**kwargs):
        calls.append(1);return SimpleNamespace(returncode=0,stdout=events(tool=True),stderr='')
    monkeypatch.setattr(c,'run_bounded_process',run)
    with pytest.raises(RuntimeError):c.run_hybrid_chat_turn(chat,'do work','api','model','high',tmp_path/'turn.jsonl',30)
    assert len(calls)==1
    assert chat['messages']==[] and chat['pending_message']=='do work'


def test_repeated_or_missing_final_never_becomes_success(chat,tmp_path,monkeypatch):
    calls=[]
    def run(*args,**kwargs):
        calls.append(1);return SimpleNamespace(returncode=0,stdout=events('Сейчас проверю данные. '*8,True),stderr='')
    monkeypatch.setattr(c,'run_bounded_process',run)
    with pytest.raises(RuntimeError,match='повторение'):c.run_hybrid_chat_turn(chat,'hello','api','model','high',tmp_path/'turn.jsonl',30)
    assert len(calls)==2 and not chat['messages']


def test_timeout_keeps_partial_log_without_retry(chat,tmp_path,monkeypatch):
    calls=[]
    def run(*args,**kwargs):
        calls.append(1);raise subprocess.TimeoutExpired('codex',1,output=b'partial-output')
    monkeypatch.setattr(c,'run_bounded_process',run)
    log=tmp_path/'timeout.jsonl'
    with pytest.raises(RuntimeError,match='лимит'):c.run_hybrid_chat_turn(chat,'hello','api','model','high',log,1)
    assert len(calls)==1 and 'partial-output' in log.read_text(encoding='utf-8')


def test_short_legitimate_answers_are_not_loops():
    assert not repeated_answer('Да','Да')
    assert not repeated_answer('Проверка завершена. Файл сохранён.')


def test_unknown_tool_events_are_not_retried(chat,tmp_path,monkeypatch):
    calls=[]
    raw=events()+'\n'+json.dumps({'type':'provider.tool_finished','payload':{'command':'write file'}})
    def run(*args,**kwargs):
        calls.append(1);return SimpleNamespace(returncode=1,stdout=raw,stderr='stream interrupted')
    monkeypatch.setattr(c,'run_bounded_process',run)
    with pytest.raises(RuntimeError):c.run_hybrid_chat_turn(chat,'hello','api','model','high',tmp_path/'unknown.jsonl',30)
    assert len(calls)==1 and not chat['last_failure']['safe_to_retry']
