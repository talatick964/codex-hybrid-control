"""Native crash diagnostics also work in a windowed executable without stderr."""
import faulthandler
import os
from pathlib import Path
import sys
import tempfile

_LOG=None


def enable_gui_log():
    global _LOG
    if _LOG is not None:return
    folder=Path(tempfile.gettempdir())/'Codex-Hybrid-Control'
    folder.mkdir(parents=True,exist_ok=True)
    _LOG=(folder/f'gui-{os.getpid()}.log').open('a',encoding='utf-8',buffering=1)
    if sys.stderr is None:sys.stderr=_LOG
    if sys.stdout is None:sys.stdout=_LOG
    faulthandler.enable(_LOG,all_threads=True)
