import subprocess
import sys
import threading
import time
import pytest
from hybrid_storage import file_transaction


def test_lock_is_reentrant(tmp_path):
    path=tmp_path/'state.lock'
    with file_transaction(path):
        with file_transaction(path):
            assert path.exists()


def test_transactions_serialize_independent_processes(tmp_path):
    counter=tmp_path/'counter.txt';counter.write_text('0')
    script="""
from pathlib import Path
import sys,time
from hybrid_storage import file_transaction
p=Path(sys.argv[1])
for i in range(12):
    with file_transaction(p.with_suffix('.lock')):
        value=int(p.read_text());time.sleep(.002);p.write_text(str(value+1))
"""
    jobs=[subprocess.Popen([sys.executable,'-c',script,str(counter)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
    for job in jobs:
        _,err=job.communicate(timeout=10)
        assert job.returncode==0,err
    assert counter.read_text()=='24'


def test_thread_contention_honors_deadline(tmp_path):
    ready=threading.Event();release=threading.Event()
    def holder():
        with file_transaction(tmp_path/'busy.lock'):
            ready.set();release.wait(timeout=3)
    thread=threading.Thread(target=holder);thread.start()
    try:
        assert ready.wait(timeout=2)
        started=time.monotonic()
        with pytest.raises(RuntimeError,match='Другая операция'):
            with file_transaction(tmp_path/'busy.lock',timeout=.1):pytest.fail('Acquired busy lock')
        assert time.monotonic()-started<.8
        # A computer action must not delay unrelated settings/status work.
        with file_transaction(tmp_path/'other.lock',timeout=.1):pass
    finally:
        release.set();thread.join(timeout=2)
    assert not thread.is_alive()
