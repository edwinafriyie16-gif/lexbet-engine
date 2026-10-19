#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(ROOT), **kwargs)
    def do_GET(self):
        if self.path == '/': self.path = '/site/index.html'
        elif self.path in ['/styles.css', '/app.js', '/manus-routes.json']:
            self.path = '/site' + self.path
        super().do_GET()
    def do_POST(self):
        if self.path == '/api/chat':
            from api.chat import handler
            class Request:
                method='POST'
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            result=handler(Request())
            self.send_response(result['statusCode'])
            for key,value in result.get('headers',{}).items(): self.send_header(key,value)
            body=result['body'].encode(); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        else: self.send_error(404)

if __name__ == '__main__':
    port=int(sys.argv[1]) if len(sys.argv)>1 else 3000
    print(f'Lexbet desk running at http://localhost:{port}/site/')
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
