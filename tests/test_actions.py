import json
import pytest
import codex_hybrid_control as c
from hybrid_actions import ActionJournal


@pytest.fixture
def journal(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    return ActionJournal(c)


def test_completed_action_is_not_replayed_after_new_bridge(journal):
    calls=[]
    journal.execute('save1','click',{'x':5},lambda:calls.append('click'))
    next_bridge=ActionJournal(c)
    result=next_bridge.execute('save1','click',{'x':5},lambda:pytest.fail('Replayed'))
    assert result['state']=='completed' and not result['replayed']
    assert calls==['click']


def test_unknown_outcome_requires_inspection(journal):
    def fail():raise TimeoutError('Unknown')
    with pytest.raises(TimeoutError):journal.execute('action1','click',{},fail)
    assert journal.status('action1')['state']=='unknown'
    with pytest.raises(RuntimeError,match='неизвестен'):
        journal.execute('action1','click',{},lambda:pytest.fail('Replayed'))


def test_secret_arguments_are_hashed_not_stored(journal):
    journal.execute('text1','type',{'text':'secret-test-value'},lambda:{'ok':True})
    assert 'secret-test-value' not in journal.path('text1').read_text(encoding='utf-8')
    with pytest.raises(RuntimeError,match='другого'):
        journal.execute('text1','type',{'text':'new'},lambda:None)


def test_batch_can_continue_completed_prefix_without_replay(journal,monkeypatch):
    actions=[{'type':'click','x':1},{'type':'click','x':2}]
    first_id=__import__('hashlib').sha256(b'batch1:0').hexdigest()
    journal.execute(first_id,'computer_step',actions[0],lambda:None)
    calls=[]
    results=journal.batch('batch1',actions,lambda a:calls.append(a['x']))
    assert calls==[2] and len(results)==2
    assert journal.status('batch1')['completed_steps']==2


def test_legacy_json_error_is_not_recorded_as_success(journal):
    with pytest.raises(RuntimeError):
        journal.execute('blocked','click',{},lambda:json.dumps({'error':'loop_detected'}))
    assert journal.status('blocked')['state']=='unknown'


@pytest.mark.parametrize('contents',['{broken','null','{}','{"action_id":"wrong","state":"completed"}'])
def test_corrupted_receipt_never_reexecutes_action(journal,contents):
    journal.directory.mkdir(parents=True,exist_ok=True)
    journal.path('once').write_text(contents,encoding='utf-8')
    with pytest.raises(RuntimeError,match='повреждён'):
        journal.execute('once','click',{},lambda:pytest.fail('Replayed after corrupted receipt'))
