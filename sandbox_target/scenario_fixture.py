"""Small HTTP target for testing scenario transport and binding behavior."""
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit


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


class WorkflowTarget(Target):
    attempts = 0
    polls = 0

    def do_POST(self):
        if self.path == '/token':
            body = parse_qs(self.rfile.read(int(self.headers.get('Content-Length', 0))).decode())
            valid = body == {'grant_type': ['client_credentials'], 'client_id': ['user'], 'client_secret': ['test-only']}
            self.reply(200 if valid else 401, {'access_token': 'fixture-oauth-token'})
        elif self.path == '/upload':
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            accepted = 'multipart/form-data; boundary=' in self.headers.get('Content-Type', '') and b'filename="sample.txt"' in body and b'hello upload' in body
            self.reply(200 if accepted else 422, {'uploaded': accepted})
        else:
            super().do_POST()

    def do_GET(self):
        if self.path == '/protected':
            self.reply(200 if self.headers.get('Authorization') == 'Bearer fixture-oauth-token' else 401, {'accepted': True})
        elif self.path.startswith('/filter?'):
            valid = parse_qs(urlsplit(self.path).query) == {'tag': ['one', 'two'], 'filter[state]': ['open']}
            self.reply(200 if valid else 422, {'accepted': valid})
        elif self.path == '/basic':
            expected = 'Basic ' + base64.b64encode(b'user:test-only').decode()
            self.reply(200 if self.headers.get('Authorization') == expected else 401, {'enabled': True})
        elif self.path == '/ready':
            type(self).polls += 1
            self.reply(200, {'ready': type(self).polls >= 2})
        elif self.path == '/temporary':
            type(self).attempts += 1
            self.reply(503 if type(self).attempts == 1 else 200, {'ok': True})
        else:
            super().do_GET()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    ThreadingHTTPServer(('127.0.0.1', args.port), WorkflowTarget).serve_forever()
