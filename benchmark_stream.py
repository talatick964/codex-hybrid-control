"""Offline stream-parser benchmark; no network or credentials."""
import json
import random
import time
from hybrid_api_guard import read_stream


class Stream:
    def __init__(self, data):self.data=data;self.offset=0
    def read1(self, size):
        block=self.data[self.offset:self.offset+size];self.offset+=len(block);return block


def main():
    random_source=random.Random(1)
    words=[''.join(random_source.choices('abcdefghijklmnopqrstuvwxyz',k=12)) for _ in range(10000)]
    data=b''.join(('data: '+json.dumps({'type':'response.output_text.delta','delta':word+' '})+'\n\n').encode() for word in words)
    data+=b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n'
    start=time.perf_counter();read_stream(Stream(data),time.monotonic()+60)
    print(json.dumps({'events':len(words),'bytes':len(data),'elapsed_seconds':round(time.perf_counter()-start,4)}))


if __name__=='__main__':main()
