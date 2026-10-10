"""Subprocess deadlines that also terminate command wrappers and descendants."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


def kill_tree(process):
    if process.poll() is not None:return
    if os.name=='nt':
        result=subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=10)
        if result.returncode and process.poll() is None:process.kill()
    else:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass


def run_bounded(command,*,timeout,cwd=None,capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=0,env=None):
    process=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture_output else None,stderr=subprocess.PIPE if capture_output else None,
        text=text,encoding=encoding if text else None,errors=errors if text else None,
        creationflags=creationflags,start_new_session=os.name!='nt')
    try:
        out,err=process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command,process.returncode,out,err)
    except subprocess.TimeoutExpired as exc:
        kill_tree(process)
        try:out,err=process.communicate(timeout=5)
        except subprocess.TimeoutExpired:out,err=exc.output,exc.stderr
        raise subprocess.TimeoutExpired(command,timeout,output=out,stderr=err) from None


def supervisor_main(arguments=None):
    args=list(arguments if arguments is not None else sys.argv[sys.argv.index('--supervise-worker')+1:])
    timeout=float(args[0]);result_path=Path(args[1]);command=args[3:]
    if args[2]!='--' or not command:raise ValueError('Missing worker command')
    try:
        result=run_bounded(command,timeout=timeout,capture_output=False,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        payload={'status':'EXITED' if result.returncode==0 else 'FAILED','returncode':result.returncode}
    except subprocess.TimeoutExpired:
        payload={'status':'TIMED_OUT','error':'Истёк лимит времени API-агента. Дерево процессов остановлено.'}
    except Exception as error:
        payload={'status':'FAILED','error':str(error)}
    temporary=result_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    temporary.replace(result_path)
    return 0 if payload['status']=='EXITED' else 1


if __name__=='__main__':
    raise SystemExit(supervisor_main(sys.argv[1:]))
