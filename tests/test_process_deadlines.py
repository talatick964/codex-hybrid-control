import json
import subprocess
import sys
import time
from pathlib import Path
import pytest
from hybrid_process import run_bounded


def test_timeout_preserves_partial_output_and_returns_promptly():
    start=time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_bounded([sys.executable,'-u','-c',"import time; print('started',flush=True); time.sleep(30)"],timeout=.5)
    assert 'started' in caught.value.output
    assert time.monotonic()-start<8


def test_supervisor_stops_without_registry_polling(tmp_path):
    result=tmp_path/'outcome.json'
    script=Path(__file__).resolve().parents[1]/'hybrid_process.py'
    run=subprocess.run([sys.executable,str(script),'.5',str(result),'--',sys.executable,'-c','import time; time.sleep(30)'],
                       capture_output=True,timeout=10)
    assert run.returncode==1
    assert json.loads(result.read_text(encoding='utf-8'))['status']=='TIMED_OUT'


def test_supervisor_records_failed_exit(tmp_path):
    result=tmp_path/'outcome.json'
    script=Path(__file__).resolve().parents[1]/'hybrid_process.py'
    subprocess.run([sys.executable,str(script),'5',str(result),'--',sys.executable,'-c','raise SystemExit(7)'],
                   capture_output=True,timeout=10)
    data=json.loads(result.read_text(encoding='utf-8'))
    assert data['status']=='FAILED' and data['returncode']==7
