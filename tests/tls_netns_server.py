"""HTTPS fake Open-Meteo server for the path-MTU test; runs inside a network
namespace (started with `ip netns exec`). Args: bind_ip port cert key"""
import ssl
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_server import FakeServer  # noqa: E402

ip, port, cert, key = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
fs = FakeServer()
fs.httpd.server_close()
fs.httpd = ThreadingHTTPServer((ip, port), fs.httpd.RequestHandlerClass)
fs.httpd.daemon_threads = True
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(cert, key)
fs.httpd.socket = ctx.wrap_socket(fs.httpd.socket, server_side=True)
print("serving", flush=True)
fs.httpd.serve_forever()
