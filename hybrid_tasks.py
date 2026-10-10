"""Deliver background results through the Tk event loop, never from a worker."""
import queue
import threading


def dispatch(window,work,done,failed):
    results=queue.Queue()
    def run():
        try:results.put((True,work()))
        except Exception as error:results.put((False,str(error)))
    def poll():
        if not window.winfo_exists():return
        try:success,result=results.get_nowait()
        except queue.Empty:
            window.after(80,poll);return
        (done if success else failed)(result)
    threading.Thread(target=run,daemon=True).start()
    window.after(80,poll)
