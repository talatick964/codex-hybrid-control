"""Bounded protection against duplicate mutating tool calls."""
from collections import deque
import hashlib
import json
import threading
import time


class ToolLoopGuard:
    READ_ONLY = {'computer_status','computer_list_windows','computer_screenshot',
                 'api_worker_list','api_worker_result','browser_fetch','computer_wait',
                 'computer_elements','computer_action_status','computer_wait_for'}

    def __init__(self, limit=8, window=60.0, clock=time.monotonic):
        self.limit=limit
        self.window=window
        self.clock=clock
        self.calls=deque(maxlen=128)
        self.lock=threading.Lock()

    def blocked(self, name, arguments=None):
        if name.split(':')[-1] in self.READ_ONLY:
            return False
        # Store a digest, never typed text, prompts or credentials.
        signature=hashlib.sha256(json.dumps([name,arguments or {}],sort_keys=True,
                                           ensure_ascii=False,default=str).encode('utf-8')).digest()
        now=self.clock()
        with self.lock:
            while self.calls and now-self.calls[0][0]>=self.window:
                self.calls.popleft()
            matches=sum(item==signature for _,item in self.calls)
            if matches>=self.limit:
                return True
            self.calls.append((now,signature))
        return False
