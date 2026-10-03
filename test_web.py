import tempfile
import time
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import yaml
from unittest.mock import patch
from web_app import create_app, save_password


class FakeService:
    def sessions(self):
        return [{'id': '1:100', 'character': 'Hero', 'realm': 'test', 'running': True, 'attachment': 'Headless'}]

    def launch(self, character, realm):
        return self.attach('1:100')

    def attach(self, session_id):
        return {'web_port': 9000, 'pairing_path': '/?pair=secret', 'session_id': session_id}

    def disconnect(self, session_id, force=False):
        return {'disconnected': True}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        save_password('test password long', self.tmp.name)
        self.config_path = Path(self.tmp.name) / 'config.yaml'
        self.config_path.write_text('# Keep this comment\npaths:\n  lich_bin: /example/lich.rbw\naccounts:\n  account:\n    - Hero\n# Keep realm settings\ndefault_realm: test\n')
        self.config = {'accounts': {'account': ['Hero']}}
        self.app = create_app(self.config, FakeService(), self.tmp.name, config_path=self.config_path)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def login(self):
        response = self.client.post('/api/login', json={'password': 'test password long'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('SameSite=strict', response.headers['set-cookie'])
        return {'x-csrf-token': response.json()['csrf']}

    def test_auth_csrf_logout(self):
        self.assertEqual(self.client.get('/api/sessions').status_code, 401)
        headers = self.login()
        self.assertEqual(self.client.get('/api/characters').json()['accounts'], {'account': ['Hero']})
        self.assertEqual(self.client.post('/api/launch', json={'character': 'Hero', 'realm': 'test'}).status_code, 403)
        bad = {**headers, 'origin': 'http://evil.example'}
        self.assertEqual(self.client.post('/api/logout', headers=bad).status_code, 403)
        self.assertEqual(self.client.post('/api/logout', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/auth').status_code, 401)

    def test_attach_pairing_url_and_secrets(self):
        headers = self.login()
        response = self.client.post('/api/sessions/1:100/attach', headers=headers)
        for _ in range(100):
            value = self.client.get('/api/operations/' + response.json()['operation_id']).json()
            if value['status'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(value['result'], {'client_url': 'http://testserver:9000/?pair=secret'})
        listing = self.client.get('/api/sessions').text
        self.assertNotIn('secret', listing)
        self.assertNotIn('salt', self.client.get('/api/characters').text)
        self.client.post('/api/logout', headers=headers)
        self.assertEqual(self.client.get('/api/operations/' + response.json()['operation_id']).status_code, 401)

    def test_selected_client_forwarded_for_launch_and_attach(self):
        headers = self.login()
        service = FakeService()
        # create_app closes over the supplied instance, so provide a fresh app.
        client = TestClient(create_app(self.config, service, self.tmp.name))
        headers = {'x-csrf-token': client.post('/api/login', json={'password': 'test password long'}).json()['csrf']}
        for path, body, method, expected in (
            ('/api/launch', {'character': 'Hero', 'realm': 'test', 'client': 'saga'}, 'launch', ('Hero', 'test', 'saga')),
            ('/api/sessions/1:100/attach', {'client': 'connection'}, 'attach', ('1:100', 'connection')),
        ):
            with patch.object(service, method, return_value={'message': 'Client connected.'}) as call:
                response = client.post(path, json=body, headers=headers)
                self.assertEqual(response.status_code, 200)
                for _ in range(100):
                    value = client.get('/api/operations/' + response.json()['operation_id']).json()
                    if value['status'] != 'running': break
                    time.sleep(.01)
                self.assertEqual(value['status'], 'done')
                call.assert_called_once_with(*expected)

    def test_invalid_client_rejected_before_submission(self):
        headers = self.login()
        for client in ('shell', ['saga'], None):
            self.assertEqual(self.client.post('/api/launch', headers=headers, json={'character': 'Hero', 'realm': 'test', 'client': client}).status_code, 400)
            self.assertEqual(self.client.post('/api/sessions/1:100/attach', headers=headers, json={'client': client}).status_code, 400)

    def test_lan_tailscale_and_ipv6_client_hosts(self):
        for hostname in ('192.168.1.20', 'host.tailnet.ts.net', '[fd7a:115c:a1e0::1]'):
            client = TestClient(self.app, base_url='http://' + hostname + ':8080')
            csrf = client.post('/api/login', json={'password': 'test password long'}).json()['csrf']
            op = client.post('/api/sessions/1:100/attach', headers={'x-csrf-token': csrf}).json()['operation_id']
            for _ in range(100):
                value = client.get('/api/operations/' + op).json()
                if value['status'] != 'running':
                    break
                time.sleep(.01)
            self.assertEqual(value['result']['client_url'], 'http://' + hostname + ':9000/?pair=secret')

    def test_throttle_and_bad_inputs(self):
        self.assertEqual(self.client.post('/api/login', json=[]).status_code, 400)
        for _ in range(4):
            self.assertEqual(self.client.post('/api/login', json={'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'password': 'wrong'}).status_code, 429)

    def test_expiry_and_restart(self):
        app = create_app({}, FakeService(), self.tmp.name, session_seconds=0)
        client = TestClient(app)
        client.post('/api/login', json={'password': 'test password long'})
        self.assertEqual(client.get('/api/auth').status_code, 401)
        self.login()
        restarted = TestClient(create_app({}, FakeService(), self.tmp.name))
        restarted.cookies.update(self.client.cookies)
        self.assertEqual(restarted.get('/api/auth').status_code, 401)

    def test_private_hash_and_invalid_launch(self):
        self.assertEqual(Path(self.tmp.name, 'auth.json').stat().st_mode & 0o777, 0o600)
        self.assertNotIn('test password long', Path(self.tmp.name, 'auth.json').read_text())
        headers = self.login()
        self.assertEqual(self.client.post('/api/launch', headers=headers, json={'character': 'Hero', 'realm': 'bad'}).status_code, 400)
        self.assertEqual(self.client.post('/api/launch', headers=headers, json=[]).status_code, 400)

    def test_add_character_persists_and_can_launch(self):
        headers = self.login()
        response = self.client.post('/api/characters', headers=headers, json={'character': ' Newhero ', 'account': 'ACCOUNT'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['accounts'], {'account': ['Hero', 'Newhero']})
        self.assertEqual(self.config['accounts'], response.json()['accounts'])
        saved = yaml.safe_load(self.config_path.read_text())
        self.assertEqual(saved['accounts'], response.json()['accounts'])
        self.assertEqual(saved['paths']['lich_bin'], '/example/lich.rbw')
        self.assertEqual(saved['default_realm'], 'test')
        self.assertIn('# Keep this comment', self.config_path.read_text())
        self.assertIn('# Keep realm settings', self.config_path.read_text())
        self.assertEqual(self.client.post('/api/launch', headers=headers, json={'character': 'Newhero', 'realm': 'prime'}).status_code, 200)
        restarted = TestClient(create_app(saved, FakeService(), self.tmp.name, config_path=self.config_path))
        restarted.post('/api/login', json={'password': 'test password long'})
        self.assertEqual(restarted.get('/api/characters').json()['accounts'], saved['accounts'])

    def test_add_character_validation_and_auth(self):
        payload = {'character': 'Newhero', 'account': 'new account'}
        self.assertEqual(self.client.post('/api/characters', json=payload).status_code, 401)
        headers = self.login()
        self.assertEqual(self.client.post('/api/characters', json=payload).status_code, 403)
        for body in ([], {'character': '--login', 'account': 'a'}, {'character': 'Hero', 'account': ''}, {'character': ['Hero'], 'account': 'a'}):
            self.assertEqual(self.client.post('/api/characters', headers=headers, json=body).status_code, 400)
        self.assertEqual(self.client.post('/api/characters', headers=headers, json={'character': 'hero', 'account': 'other'}).status_code, 409)
        self.assertEqual(self.client.post('/api/characters', headers=headers, json=payload).status_code, 200)
        self.assertEqual(self.client.get('/api/characters').json()['accounts']['new account'], ['Newhero'])

    def test_failed_save_does_not_update_roster(self):
        headers = self.login()
        self.config_path.write_text('accounts: invalid\n')
        response = self.client.post('/api/characters', headers=headers, json={'character': 'Newhero', 'account': 'a'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.client.get('/api/characters').json()['accounts'], {'account': ['Hero']})


if __name__ == '__main__':
    unittest.main()
