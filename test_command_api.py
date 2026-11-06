import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from web_app import create_app, save_password
from test_command_service import Sessions, Bridge


class CommandApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();save_password('test password long',self.tmp.name)
        self.service=Sessions(self.tmp.name)
        self.app=create_app(self.service.config,self.service,self.tmp.name)
        self.client=TestClient(self.app)
        self.headers={'x-csrf-token':self.client.post('/api/login',json={'password':'test password long'}).json()['csrf']}
    def tearDown(self):
        if hasattr(self.app.state,'commands'): self.app.state.commands.close()
        self.app.state.telemetry.close()
        self.tmp.cleanup()
    def test_command_endpoints_require_auth_and_mutation_csrf_origin(self):
        self.assertEqual(self.client.get('/api/command-targets').status_code,200)
        self.assertEqual(self.client.post('/api/command-batches/prepare').status_code,403)
        self.assertEqual(self.client.post('/api/command-batches/prepare',headers={**self.headers,'origin':'http://evil.test'}).status_code,403)
        self.client.post('/api/logout',headers=self.headers)
        for path in ['/api/command-targets','/api/command-batches','/api/command-batches/missing','/api/control/script']:
            self.assertEqual(self.client.get(path).status_code,401)
    def test_prepare_accept_lookup_and_history(self):
        self.app.state.commands.transport=Bridge()
        prepared=self.client.post('/api/command-batches/prepare',headers=self.headers).json()
        targets=self.client.get('/api/command-targets').json()['targets']
        body=dict(prepared,command=';pause all',targets=[{k:t[k] for k in ('session_id','bridge_generation','character','realm')} for t in targets])
        response=self.client.post('/api/command-batches',json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        request_id=response.json()['request_id']
        for _ in range(100):
            receipt=self.client.get('/api/command-batches/'+request_id).json()
            if all(t['state']=='sent' for t in receipt['targets']):break
            time.sleep(.01)
        self.assertEqual([t['state'] for t in receipt['targets']],['sent','sent'])
        self.assertEqual(self.client.get('/api/command-batches?limit=20').json()['batches'][0]['request_id'],request_id)
        self.assertEqual(self.client.post('/api/command-batches',json=body,headers=self.headers).status_code,200)
        body['command']='look'
        self.assertEqual(self.client.post('/api/command-batches',json=body,headers=self.headers).status_code,409)
    def test_browser_assets_are_served(self):
        for asset in ('commands.js','commands.css'):
            response=self.client.get('/assets/'+asset)
            self.assertEqual(response.status_code,200,response.text)

    def test_bounded_request_and_bad_inputs(self):
        self.assertEqual(self.client.post('/api/command-batches',content=b'x'*65537,headers=self.headers).status_code,413)
        self.assertEqual(self.client.post('/api/command-batches',json=[],headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/api/command-batches?limit=1001').status_code,400)
        self.assertEqual(self.client.get('/api/command-batches/missing').status_code,404)

if __name__=='__main__':unittest.main()
