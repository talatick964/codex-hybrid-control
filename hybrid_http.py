"""Hard response-body deadline and size bound for small HTTP downloads."""
import time


def read_limited(response,deadline,limit):
    if not hasattr(response,'read1'):
        result=response.read(limit+1)
        if len(result)>limit:raise ValueError('Ответ сервера превышает допустимый размер')
        if time.monotonic()>deadline:raise TimeoutError('Сервер не завершил ответ вовремя')
        return result
    blocks=[];size=0
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Сервер не завершил ответ вовремя')
        try:response.fp.raw._sock.settimeout(remaining)
        except AttributeError:pass
        block=response.read1(min(65536,limit-size+1))
        if not block:return b''.join(blocks)
        size+=len(block)
        if size>limit:raise ValueError('Ответ сервера превышает допустимый размер')
        blocks.append(block)
