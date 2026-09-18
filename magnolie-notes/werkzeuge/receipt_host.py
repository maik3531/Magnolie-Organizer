#!/usr/bin/env python3
"""Owned loopback adapter around the CURRENT Linux handler and persistent stores."""
import base64
import json
import os
from pathlib import Path
import socket
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

root = Path(sys.argv[1]).resolve()
assert str(root).startswith('/tmp/opencode/') and root.is_dir()
source = Path(sys.argv[2]).resolve()
module = types.ModuleType('receipt_fixture_organizer')
module.__file__ = str(source)
sys.modules[module.__name__] = module
exec(compile(source.read_bytes(), str(source), 'exec'), module.__dict__)
initial = json.loads(sys.stdin.readline())
state_path, inbox_path, post_path = (str(root / name) for name in ('state.json', 'inbox.json', 'outbox.json'))
state = module.baum_lesen(state_path)
peer = next((p for p in state['partner'] if p['kennung'] == initial['id']), None)
if peer is None:
    peer = dict(kennung=initial['id'], name='Owned Android', oeffentlich=initial['public'], bestaetigt=True,
                protokoll='baum-1', adresse='127.0.0.1', port=initial['port'])
    state['partner'].append(peer)
assert peer['oeffentlich'] == initial['public']
peer.update(adresse='127.0.0.1', port=initial['port'])
state['an'] = True
lock = threading.RLock()
mode = 'normal'
requests = 0

def save(value):
    return module.baum_schreiben(value, state_path)

handler = module.BaumDienst(lambda: state, save,
    lambda partner, content: module.baum_eingang_ablegen(partner, content, inbox_path), sperre=lock)

class Http(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_): pass
    def do_POST(self):
        global requests
        self.connection.settimeout(5)
        size = int(self.headers.get('Content-Length', '-1'))
        assert 0 < size <= 2 * 1024 * 1024
        envelope = json.loads(self.rfile.read(size))
        with lock:
            requests += 1
            status, receipt = handler.behandeln(self.path, envelope, '127.0.0.1')
            if status == 200:
                if mode == 'unsigned': receipt = {}
                elif mode == 'wrong-mac': receipt = dict(receipt, mac=base64.b64encode(bytes(32)).decode())
                elif mode == 'wrong-binding':
                    key = module._sitzungsschluessel(state['geheim'], peer['oeffentlich'], state['kennung'], peer['kennung'])
                    receipt = module.baum_receipt(key, peer['kennung'], 'other', envelope)
                elif mode == 'lost':
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
        body = json.dumps(receipt, separators=(',', ':')).encode()
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)

server = ThreadingHTTPServer(('127.0.0.1', 0), Http)
server.daemon_threads = True
state['port'] = server.server_port
save(state)
threading.Thread(target=server.serve_forever, daemon=True).start()

def output(value): print('RECEIPT_HOST ' + json.dumps(value, separators=(',', ':')), flush=True)
def stats():
    return dict(inbox=len(module.baum_eingang_lesen(inbox_path)), outbox=module.baum_post_lesen(post_path), requests=requests)

output(dict(id=state['kennung'], public=state['oeffentlich'], port=server.server_port))
try:
    for line in sys.stdin:
        command = json.loads(line)
        with lock:
            op = command['op']
            if op == 'quit': break
            if op == 'mode': mode = command['value']
            elif op == 'send':
                post = module.baum_post_lesen(post_path)
                module.baum_einreihen(post, peer['kennung'], 'stand', command['body'])
                assert module.baum_post_schreiben(post, post_path)
                module.baum_post_wartung(state, post_path, hoechstens=10, zustand_sichern=save)
            elif op == 'vector':
                output(module.baum_receipt(bytes.fromhex(command['key']), 'alpha', 'beta', command['envelope']))
                continue
            output(stats())
finally:
    server.shutdown()
    server.server_close()
