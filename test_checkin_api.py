"""In-process HTTP tests using temporary DBs and fake sessions only."""
import tempfile
import unittest
from fastapi.testclient import TestClient
from web_app import create_app, save_password
from test_daily_checkin import FakeService


class CheckinApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        save_password('a long test password',self.tmp.name)
        self.service=FakeService()
        self.app=create_app({'accounts':{'A':['Alpha']}},self.service,self.tmp.name)
        self.client=TestClient(self.app)

    def tearDown(self):
        self.app.state.checkin.close()
        self.app.state.telemetry.close()
        self.tmp.cleanup()

    def login(self):
        result=self.client.post('/api/login',json={'password':'a long test password'})
        return {'x-csrf-token':result.json()['csrf']}

    def test_auth_csrf_and_disabled_backend(self):
        self.assertEqual(self.client.get('/api/checkin').status_code,401)
        headers=self.login()
        self.assertEqual(self.client.post('/api/checkin/runs',json={}).status_code,403)
        state=self.client.get('/api/checkin').json()
        self.assertFalse(state['allowed'])
        self.assertIsNone(state['run'])
        self.assertEqual(self.client.post('/api/checkin/runs',json={},headers=headers).status_code,409)
        self.assertEqual(self.service.started,[])

    def test_settings_and_assets(self):
        headers=self.login()
        self.assertEqual(self.client.put('/api/checkin/settings',json={'parallel_accounts':3},headers=headers).json()['parallel_accounts'],3)
        self.assertEqual(self.client.put('/api/checkin/settings',json={'enabled':True},headers=headers).status_code,409)
        for asset in ('checkin.js','checkin.css'):
            self.assertEqual(self.client.get('/assets/'+asset).status_code,200)


if __name__=='__main__': unittest.main()
