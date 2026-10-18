import tempfile
import unittest

from telemetry import TelemetryStore
import test_dashboard_api


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TelemetryStore(self.tmp.name)
        self.sessions = [dict(id='12:100', pid=12, realm='prime', character='Example')]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def snapshot(self, sequence=1):
        return dict(schema_version=1, pid=12, realm='prime', reporter_id='r1', sequence=sequence,
                    character=dict(name='Example', level=100, profession='Wizard'),
                    stats=dict(strength=dict(value=80, bonus=15, base_value=75, base_bonus=12)),
                    skills=dict(arcane_symbols=dict(ranks=202, bonus=302),
                                wizard=dict(ranks=100, bonus=None, category='spell_research')),
                    resources=dict(type='essence', weekly=32450, total=118750, observed_at=1000),
                    bonuses=dict(lumnis_stage=3, lumnis_points_remaining=4500,
                                 lumnis_donations=0, observed_at=1000, donations_observed_at=999))

    def profile(self, realm='prime', character='example'):
        return self.store.profile(realm, character)

    def test_persists_exact_balances_across_restart_and_expiry(self):
        self.store.ingest(self.snapshot(), self.sessions)
        self.store.live.clear()
        self.store.close()
        self.store = TelemetryStore(self.tmp.name)
        result = self.profile()
        self.assertEqual(result['character'], 'Example')
        self.assertEqual(result['snapshot']['resources']['weekly'], 32450)
        self.assertEqual(result['snapshot']['resources']['total'], 118750)
        self.assertEqual(result['snapshot']['skills']['wizard']['ranks'], 100)
        self.assertEqual(result['observed_at']['resources'], 1000)
        self.assertIsNone(self.profile('test'))

    def test_partial_reports_keep_valid_fields_and_original_observation_time(self):
        self.store.ingest(self.snapshot(), self.sessions)
        incoming = self.snapshot(2)
        incoming.update(stats=None, skills=None, bonuses={'lumnis_stage': 'expired', 'observed_at': 1100},
                        resources={'type': None, 'weekly': None, 'total': 0, 'observed_at': 1100})
        self.store.ingest(incoming, self.sessions)
        result = self.profile()
        self.assertEqual(result['snapshot']['resources']['weekly'], 32450)
        self.assertEqual(result['snapshot']['resources']['total'], 0)
        self.assertEqual(result['field_observed_at']['resources']['weekly'], 1000)
        self.assertEqual(result['field_observed_at']['resources']['total'], 1100)
        self.assertEqual(result['snapshot']['bonuses']['lumnis_donations'], 0)
        self.assertIsNone(result['snapshot']['bonuses'].get('lumnis_points_remaining'))
        self.assertEqual(result['snapshot']['stats']['strength']['value'], 80)

    def test_older_section_cannot_replace_newer_values(self):
        data = self.snapshot()
        self.store.ingest(data, self.sessions)
        old = self.snapshot(2)
        old['resources'].update(weekly=1, total=2, observed_at=900)
        self.store.ingest(old, self.sessions)
        self.assertEqual(self.profile()['snapshot']['resources']['weekly'], 32450)

    def test_complete_skill_refresh_removes_untrained_skills(self):
        self.store.ingest(self.snapshot(), self.sessions)
        data = self.snapshot(2)
        data['skills'] = {'arcane_symbols': {'ranks': 1, 'bonus': 5}}
        self.store.ingest(data, self.sessions)
        self.assertNotIn('wizard', self.profile()['snapshot']['skills'])
        data['sequence'] = 3
        data['skills'] = {}
        self.store.ingest(data, self.sessions)
        self.assertEqual(self.profile()['snapshot']['skills'], {})

    def test_nullable_donation_timestamp_uses_section_observation(self):
        data = self.snapshot()
        data['bonuses']['donations_observed_at'] = None
        self.store.ingest(data, self.sessions)
        self.assertEqual(self.profile()['field_observed_at']['bonuses']['lumnis_donations'], 1000)

    def test_tutelage_observations_are_independent_of_lumnis(self):
        data=self.snapshot()
        data['bonuses'].update(fashlonae_state='active',fashlonae_observed_at=1000,
                              fashlonae_days_remaining=121,fashlonae_days_observed_at=900)
        self.store.ingest(data,self.sessions)
        newer=self.snapshot(2)
        newer['bonuses'].update(observed_at=1200,fashlonae_state='eligible',fashlonae_observed_at=950)
        self.store.ingest(newer,self.sessions)
        result=self.profile()
        self.assertEqual(result['snapshot']['bonuses']['fashlonae_state'],'active')
        self.assertEqual(result['field_observed_at']['bonuses']['fashlonae_days_remaining'],900)
        newer['sequence']=3
        newer['bonuses'].update(fashlonae_state='unavailable',fashlonae_observed_at=1300)
        self.store.ingest(newer,self.sessions)
        self.assertEqual(self.profile()['snapshot']['bonuses']['fashlonae_days_remaining'],0)
        newer['sequence']=4
        newer['bonuses'].update(fashlonae_state='active',fashlonae_observed_at=1400)
        self.store.ingest(newer,self.sessions)
        self.assertNotIn('fashlonae_days_remaining',self.profile()['snapshot']['bonuses'])

    def test_tutelage_fields_reject_invalid_values(self):
        for fields in [dict(fashlonae_state='made up'),dict(fashlonae_days_remaining=-1),
                       dict(fashlonae_observed_at='now')]:
            data=self.snapshot();data['bonuses'].update(fields)
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                self.store.ingest(data,self.sessions)

    def test_tutelage_weekly_exhaustion_preserves_benefit_duration(self):
        data=self.snapshot()
        data['bonuses'].update(fashlonae_state='expended',fashlonae_days_remaining=121,
                              fashlonae_observed_at=1100,fashlonae_days_observed_at=1000)
        self.store.ingest(data,self.sessions)
        data['sequence']=2;data['bonuses'].update(lumnis_stage='ready',observed_at=1200)
        self.store.ingest(data,self.sessions)
        self.store.close();self.store=TelemetryStore(self.tmp.name)
        result=self.profile()['snapshot']['bonuses']
        self.assertEqual(result['fashlonae_state'],'expended')
        self.assertEqual(result['fashlonae_days_remaining'],121)

    def test_rejects_invalid_sections_without_accepting_sequence(self):
        for fields in [dict(stats=[]), dict(skills={'arcane_symbols': {'ranks': -1}}),
                       dict(stats={'strength': {'value': '80'}}),
                       dict(resources={'weekly': True}), dict(bonuses={'lumnis_donations': -1}),
                       dict(metadata={'availability': []})]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.store.ingest(self.snapshot() | fields, self.sessions)
        self.store.ingest(self.snapshot(), self.sessions)

    def test_old_reporter_remains_compatible_and_realms_stay_separate(self):
        legacy = self.snapshot()
        legacy.pop('stats'); legacy.pop('skills')
        self.store.ingest(legacy, self.sessions)
        other = self.snapshot()
        other.update(pid=13, realm='test', reporter_id='r2')
        other['resources']['total'] = 50
        self.store.ingest(other, [dict(id='13:100', pid=13, realm='test', character='Example')])
        self.assertEqual(self.profile('test')['snapshot']['resources']['total'], 50)
        self.assertEqual(self.profile()['snapshot']['resources']['total'], 118750)


class ProfileApiTests(unittest.TestCase):
    setUp = test_dashboard_api.DashboardApiTests.setUp
    tearDown = test_dashboard_api.DashboardApiTests.tearDown
    token = test_dashboard_api.DashboardApiTests.token
    snapshot = test_dashboard_api.DashboardApiTests.snapshot

    def test_profiles_include_unreported_roster_and_offline_data(self):
        headers = {'Authorization': 'Bearer ' + self.token()}
        payload = self.snapshot() | dict(resources={'type': 'essence', 'weekly': 32450, 'total': 118750})
        self.client.post('/api/telemetry/update', headers=headers, json=payload)
        profiles = self.client.get('/api/profiles?realm=prime').json()['profiles']
        self.assertEqual(profiles[0]['snapshot']['resources']['total'], 118750)
        self.assertEqual(profiles[0]['account'], 'Main')
        self.client.app.state.telemetry.live.clear()
        result = self.client.get('/api/profiles/prime/hero')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['snapshot']['resources']['weekly'], 32450)
        empty = self.client.get('/api/profiles/test/Hero').json()
        self.assertEqual(empty['snapshot'], {})
        self.assertIsNone(empty['updated_at'])
        self.assertEqual(self.client.get('/api/profiles/bad/Hero').status_code, 400)
        self.assertEqual(self.client.get('/api/profiles/prime/Unknown').status_code, 404)
        self.client.post('/api/logout', headers=self.headers)
        self.assertEqual(self.client.get('/api/profiles').status_code, 401)
        self.assertEqual(self.client.get('/api/profiles/prime/Hero').status_code, 401)
