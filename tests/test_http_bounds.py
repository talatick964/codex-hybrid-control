import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import urllib.request
import pytest
from hybrid_http import read_limited


def test_slow_body_cannot_extend_download_forever():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200);self.end_headers()
            try:
                for _ in range(100):self.wfile.write(b'x');self.wfile.flush();time.sleep(.03)
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        started=time.monotonic()
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}',timeout=2) as response:
            with pytest.raises((TimeoutError,OSError)):read_limited(response,started+.3,1000)
        assert time.monotonic()-started<1.2
    finally:server.shutdown();server.server_close()


def test_oversized_response_is_rejected_before_parse():
    class Response:
        def read1(self,size):return b'x'*size
    with pytest.raises(ValueError,match='размер'):read_limited(Response(),time.monotonic()+1,10)
