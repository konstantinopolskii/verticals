"""HTTP fault fixture for native_smoke --partial. UI assets come from the isolated app."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import urlopen
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        with urlopen('http://127.0.0.1:8388'+self.path) as r:
            data=r.read(); mime=r.headers['Content-Type']
        self.send_response(200); self.send_header('Content-Type',mime); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length','0')))
        data=json.dumps({'goal':sys.argv[1],'error':'Агент недоступен.'}).encode()
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(data)
HTTPServer(('127.0.0.1',8387),Handler).serve_forever()
