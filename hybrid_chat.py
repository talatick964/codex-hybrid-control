"""Bounded chat recovery with complete logs and conservative retry rules."""
import copy
import json
import re
import subprocess
import time
from pathlib import Path


def repeated_answer(answer, previous=''):
    normalized=' '.join(answer.casefold().split())
    if len(normalized)>=80 and normalized==' '.join(previous.casefold().split()):return True
    words=normalized.split()
    if len(words)>=12:
        for size in range(1,min(60,len(words)//4)+1):
            block=words[:size]
            count=0
            while words[count*size:(count+1)*size]==block:count+=1
            if count>=4 and count*size>=len(words)*.8:return True
    sentences=[s.strip() for s in re.split(r'[.!?\n]+',answer.casefold()) if len(s.strip())>=12]
    return len(sentences)>=4 and max(sentences.count(s) for s in set(sentences))>=len(sentences)*.8


def run_turn(core,chat,message,mode,model,reasoning,log_path,timeout=600):
    if core.is_stock_mode():raise RuntimeError('Hybrid Control отключён. Восстановите настройку перед запуском чата.')
    project=Path(chat['project'])
    if not project.is_dir():raise RuntimeError('Папка проекта больше не существует.')
    deadline=time.monotonic()+max(1,min(float(timeout),3600))
    log_path=Path(log_path);log_path.parent.mkdir(parents=True,exist_ok=True)
    flags=core._provider_exec_flags(mode,model,reasoning)
    base=[core.codex_command(),'exec','--skip-git-repo-check','--sandbox','workspace-write','-c','approval_policy="never"','-C',str(project),'--json']+flags
    old_thread=chat.get('thread_id')
    active_thread=old_thread
    previous=next((m.get('text','') for m in reversed(chat.get('messages',[])) if m.get('role')=='assistant'),'')
    chunks=[]
    parsed={}
    attempt_message=message
    failure='Ответ API не завершён.'
    safe_to_retry=False
    for attempt in range(2):
        remaining=deadline-time.monotonic()
        if remaining<=0:
            failure='Истёк общий лимит времени запроса.';break
        command=base+(['resume',str(active_thread),attempt_message] if active_thread else [attempt_message])
        timed_out=False
        try:
            cp=core.run_bounded_process(command,cwd=str(project),capture_output=True,text=True,encoding='utf-8',errors='replace',
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=remaining)
            raw=cp.stdout or '';stderr=cp.stderr or '';code=cp.returncode
        except subprocess.TimeoutExpired as error:
            def decode(value):return value.decode('utf-8','replace') if isinstance(value,bytes) else (value or '')
            raw=decode(error.stdout);stderr=decode(error.stderr);code=-1;timed_out=True
        chunks.append(json.dumps({'type':'hybrid.attempt','attempt':attempt+1,'returncode':code,'timeout':timed_out})+'\n'+raw+'\n'+json.dumps({'type':'hybrid.stderr','text':stderr},ensure_ascii=False)+'\n')
        log_path.write_text(''.join(chunks),encoding='utf-8')
        parsed=core._parse_codex_jsonl(raw)
        active_thread=parsed.get('thread_id') or active_thread
        answer=parsed['answer']
        loop=repeated_answer(answer,previous) if answer else False
        if not timed_out and code==0 and parsed.get('completed') and answer and not parsed['errors'] and not loop:
            updated=copy.deepcopy(chat)
            continuity='SAME_THREAD' if old_thread and active_thread==old_thread else ('NEW_THREAD_HANDOFF' if old_thread else 'NEW_THREAD')
            updated['thread_id']=active_thread
            updated['backend']={'mode':mode,'model':model if mode=='api' else core.OFFICIAL_MODEL,'reasoning':reasoning}
            updated.setdefault('messages',[]).extend([{'role':'user','text':message,'at':core.now_iso()},
                {'role':'assistant','text':answer,'at':core.now_iso(),'continuity':continuity}])
            updated['updated_at']=core.now_iso();updated.pop('pending_message',None);updated.pop('last_failure',None)
            core.write_json_atomic(core._chat_path(updated['id']),updated)
            chat.clear();chat.update(updated)
            return {'chat':chat,'answer':answer,'continuity':continuity,'thread_id':active_thread,'attempts':attempt+1}
        if timed_out:failure='Истёк общий лимит времени запроса. Автоповтор не выполнялся: результат действий может быть неизвестен.'
        elif loop:failure='Обнаружено повторение ответа API.'
        elif parsed['errors']:failure='\n'.join(parsed['errors'])[-2000:]
        elif code:failure=(stderr or f'Codex завершился с кодом {code}')[-2000:]
        else:failure='Провайдер не прислал подтверждённый итоговый ответ.'
        fatal=any(token in failure.casefold() for token in ['401','403','unauthorized','invalid api key','authentication'])
        safe_to_retry=bool(not timed_out and not parsed.get('activity') and parsed.get('has_events') and not parsed.get('uncertain') and not fatal)
        if attempt or not safe_to_retry:break
        missing_thread=any(token in failure.casefold() for token in ['thread not found','session not found','no conversation found','provider mismatch'])
        if old_thread and missing_thread:
            active_thread=None
            attempt_message=core._continuity_context(chat)+'\n\n[NEW USER MESSAGE]\n'+message
        else:
            attempt_message=message+'\n\nПредыдущая попытка оборвалась или повторяла текст. Дай законченный ответ. Не повторяй уже выполненные действия.'
    updated=copy.deepcopy(chat)
    updated['thread_id']=active_thread
    updated['pending_message']=message
    updated['last_failure']={'message':failure,'log':str(log_path),'at':core.now_iso(),'safe_to_retry':safe_to_retry}
    updated['updated_at']=core.now_iso()
    core.write_json_atomic(core._chat_path(updated['id']),updated)
    chat.clear();chat.update(updated)
    raise RuntimeError(f'{failure}\nДиагностика сохранена: {log_path}')
