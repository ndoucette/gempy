"""Isolated UI fixture. Serves static assets and synthetic data, never GemPy Service.

Run with Python then visit http://127.0.0.1:18767/?view=checkin . All mutations
are rejected. The page's sample preview interactions remain browser-local.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent.parent/'static'
SETTINGS=dict(timezone='America/Los_Angeles',day_boundary=5,stale_seconds=20,expiry_seconds=300,
              default_client='vellum_despana',density='comfortable',default_view='checkin',update_interval=3,
              reporter_configured=False)
ACCOUNTS={'Account A':['Renwaldo','Vlatimire'],'Account B':['Voxy','Gringott'],'Account C':['Vecto','Dartwen']}


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        path=urlsplit(self.path).path
        state=dict(allowed=False,disabled_reason='Live execution is disabled. This isolated fixture cannot connect to game sessions.',
                   settings=dict(enabled=False,time='00:15',parallel_accounts=4,freshness_hours=22),run=None,history=[],
                   now=1792778400,game_day='2026-10-23',roster=[dict(account=a,account_label=a,character=c) for a,names in ACCOUNTS.items() for c in names])
        api={'/api/auth':{'csrf':'fixture'},'/api/characters':{'accounts':ACCOUNTS},'/api/sessions':{'sessions':[]},
             '/api/settings':SETTINGS,'/api/profiles':{'profiles':[]},'/api/checkin':state}
        if path in api:
            content=json.dumps(api[path]).encode();kind='application/json'
        else:
            name='index.html' if path=='/' else path.removeprefix('/assets/')
            file=(ROOT/name).resolve()
            if not file.is_relative_to(ROOT.resolve()) or not file.is_file():self.send_error(404);return
            content=file.read_bytes();kind={'.html':'text/html','.js':'text/javascript','.css':'text/css','.webp':'image/webp'}.get(file.suffix,'application/octet-stream')
        self.send_response(200);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)

    def do_POST(self): self.send_error(409,'Read-only fixture: game operations are unavailable.')
    def do_PUT(self): self.do_POST()
    def log_message(self,*args): pass


if __name__=='__main__':
    print('Read-only UI fixture: http://127.0.0.1:18767/?view=checkin',flush=True)
    ThreadingHTTPServer(('127.0.0.1',18767),Fixture).serve_forever()
