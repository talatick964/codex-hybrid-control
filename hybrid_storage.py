"""Reentrant cross-process locks for small local state transactions."""
from contextlib import contextmanager
import os
from pathlib import Path
import threading
import time

_THREAD_LOCK=threading.RLock()
_PATH_LOCKS={}
_LOCAL=threading.local()


@contextmanager
def file_transaction(path,timeout=10):
    path=Path(path).resolve()
    key=os.path.normcase(str(path))
    with _THREAD_LOCK:
        lock=_PATH_LOCKS.setdefault(key,threading.RLock())
    deadline=time.monotonic()+timeout
    if not lock.acquire(timeout=max(0,timeout)):
        raise RuntimeError('Другая операция ещё изменяет настройки. Повторите через несколько секунд.')
    try:
        held=getattr(_LOCAL,'held',set())
        if key in held:
            yield
            return
        path.parent.mkdir(parents=True,exist_ok=True)
        handle=path.open('a+b')
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        acquired=False
        try:
            while not acquired:
                try:
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    acquired=True
                except OSError:
                    if time.monotonic()>=deadline:raise RuntimeError('Другая операция ещё изменяет настройки. Повторите через несколько секунд.')
                    time.sleep(.025)
            _LOCAL.held=held|{key}
            yield
        finally:
            _LOCAL.held=held
            if acquired:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
            handle.close()
    finally:
        lock.release()
