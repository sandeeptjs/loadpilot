"""Small HTTP target for testing scenario transport and binding behavior."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.parse import parse_qs


class Target(BaseHTTPRequestHandler):
    calls: ClassVar[list] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode()
        kind = self.headers.get('Content-Type', '')
        body = parse_qs(raw) if kind == 'application/x-www-form-urlencoded' else raw if kind == 'text/plain' else json.loads(raw or '{}')
        self.calls.append(self.path)
        if self.path == '/form' and body == {'name': ['Ada Lovelace']} or self.path == '/text' and body == 'hello':
            self.reply(200, {'accepted': True})
        elif self.path == '/sessions':
            self.reply(200, {'token': 'fixture-session'})
        elif self.path == '/tickets' and self.headers.get('Authorization') == 'Bearer fixture-session' and body == {'owner': {'name': 'Ada'}}:
            self.reply(201, {'ticket': {'id': 42}})
        elif self.path == '/graphql' and body.get('query') == 'query { health }':
            self.reply(200, {'data': {'health': 'ok'}})
        else:
            self.reply(422, {'error': 'invalid input'})

    def do_GET(self):
        self.calls.append(self.path)
        if self.path == '/tickets/42':
            self.reply(200, {'status': 'open'})
        elif self.path == '/search?q=books':
            self.reply(200, {'results': ['book']})
        else:
            self.reply(404, {})

    def reply(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    ThreadingHTTPServer(('127.0.0.1', args.port), Target).serve_forever()
