from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from web_app import create_app, save_password


class Sessions:
    def sessions(self):
        return [dict(id='42:100', pid=42, character='Hero', realm='prime',
                     running=True, attachment='Headless')]


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        save_password('long test password', self.root)
        self.config = {'paths': {'lich_bin': str(self.root / 'lich.rbw')},
                       'accounts': {'Main': ['Hero']}}
        self.path = self.root / 'config.yaml'
        self.path.write_text('paths:\n  lich_bin: example\n# Preserve me\naccounts:\n  Main: [Hero]\n')
        self.client = TestClient(create_app(self.config, Sessions(), self.root, config_path=self.path))
        self.headers = {'x-csrf-token': self.client.post('/api/login', json={
            'password': 'long test password'}).json()['csrf']}

    def tearDown(self):
        self.client.app.state.telemetry.db.close()
        self.tmp.cleanup()

    def token(self):
        return self.client.post('/api/telemetry/token', headers=self.headers).json()['token']

    def snapshot(self, sequence=1, xp=100):
        return dict(schema_version=1, pid=42, realm='GSIV', reporter_id='instance', sequence=sequence,
                    character={'name': 'Hero'}, experience={'lifetime_exp': xp, 'ascension_exp': 0})

    def test_reporter_auth_identity_and_rotation(self):
        payload = self.snapshot()
        self.assertEqual(self.client.post('/api/telemetry/update', json=payload).status_code, 401)
        self.assertEqual(self.client.post('/api/telemetry/token').status_code, 403)
        token = self.token()
        headers = {'Authorization': 'Bearer ' + token}
        self.assertNotIn(token, (self.root / 'reporter-token.sha256').read_text())
        self.assertEqual(self.client.post('/api/telemetry/update', headers=headers, json=payload).status_code, 200)
        session = self.client.get('/api/sessions').json()['sessions'][0]
        self.assertEqual(session['telemetry']['status'], 'fresh')
        self.assertEqual(self.client.post('/api/telemetry/update', headers=headers, json=payload).status_code, 400)
        other = dict(self.snapshot(2), realm='GST')
        self.assertEqual(self.client.post('/api/telemetry/update', headers=headers, json=other).status_code, 400)
        self.token()
        self.assertEqual(self.client.post('/api/telemetry/update', headers=headers, json=self.snapshot(2)).status_code, 401)

    def test_payload_limits_and_progress_auth(self):
        headers = {'Authorization': 'Bearer ' + self.token()}
        self.assertEqual(self.client.post('/api/telemetry/update', headers=headers, content='x' * 262145).status_code, 413)
        self.assertEqual(self.client.post('/api/telemetry/update', headers=headers, content='not json').status_code, 400)
        for fields in ({'identity': []}, {'realm': []}, {'sequence': 2**80}):
            self.assertEqual(self.client.post('/api/telemetry/update', headers=headers,
                                             json=self.snapshot() | fields).status_code, 400)
        self.assertEqual(self.client.post('/api/telemetry/update', headers=headers,
                                         content='[' * 1200 + '0' + ']' * 1200).status_code, 400)
        self.client.post('/api/telemetry/update', headers=headers, json=self.snapshot())
        self.client.post('/api/telemetry/update', headers=headers, json=self.snapshot(2, 130))
        result = self.client.get('/api/progress?period=day').json()
        self.assertEqual(result['characters'][0]['normal_xp'], 30)
        self.assertEqual(self.client.get('/api/progress?period=custom&start=2026-10-01&end=2026-10-03').status_code, 200)
        self.assertEqual(self.client.get('/api/progress?period=custom&start=bad&end=2026-10-03').status_code, 400)
        self.client.post('/api/logout', headers=self.headers)
        for path in ('/api/settings', '/api/progress', '/api/history/backup', '/api/reporter/script'):
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_settings_import_backup_and_roster_edit(self):
        self.assertEqual(self.client.post('/api/settings', json={'timezone': 'UTC'}).status_code, 403)
        self.assertEqual(self.client.post('/api/settings', headers=self.headers,
                                         json={'timezone': 'invalid timezone'}).status_code, 400)
        self.assertEqual(self.client.post('/api/settings', headers=self.headers,
                                         json={'timezone': 'UTC'}).status_code, 200)
        self.assertEqual(self.client.get('/api/settings').json()['timezone'], 'UTC')
        history = self.root / 'data/GSIV/Hero/exp_sagapanel_history.yaml'
        history.parent.mkdir(parents=True)
        history.write_text('daily:\n  "2026-09-21": {exp: 100, asc: 50}\n')
        self.assertEqual(self.client.post('/api/history/import', headers=self.headers).status_code, 200)
        backup = self.client.get('/api/history/backup')
        self.assertEqual(backup.status_code, 200)
        self.assertTrue(backup.content.startswith(b'SQLite format 3'))
        result = self.client.patch('/api/characters', headers=self.headers,
                                   json={'character': 'Hero', 'new_character': 'Newhero', 'account': 'Other'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['accounts'], {'Other': ['Newhero']})
        result = self.client.patch('/api/accounts', headers=self.headers,
                                   json={'account': 'Other', 'new_account': 'Renamed'})
        self.assertEqual(result.json()['accounts'], {'Renamed': ['Newhero']})
        self.assertIn('# Preserve me', self.path.read_text())


if __name__ == '__main__':
    unittest.main()
