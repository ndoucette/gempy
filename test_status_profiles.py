import sqlite3
import unittest
from character_profiles import ProfileRepository, validate_profile


class StatusProfilesTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.repo = ProfileRepository(self.db)

    def tearDown(self):
        self.db.close()

    def test_independent_observations_partial_and_old_reports(self):
        self.repo.ingest('prime', 'Hero', {
            'resources': {'weekly': 1, 'suffused': 100, 'observed_at': 1000, 'suffused_observed_at': 900},
            'wealth': {'bank_balance': 123000, 'bank_balance_observed_at': 800, 'deeds': 10, 'deeds_observed_at': 900}}, 1100)
        self.repo.ingest('prime', 'Hero', {
            'resources': {'weekly': 2, 'suffused': 100, 'observed_at': 1200, 'suffused_observed_at': 900},
            'wealth': {'bank_balance': None, 'deeds': 0, 'deeds_observed_at': 1200}}, 1300)
        row = self.repo.get('prime', 'hero')
        self.assertEqual(row['snapshot']['wealth'], {'bank_balance': 123000, 'deeds': 0})
        self.assertEqual(row['field_observed_at']['wealth'], {'bank_balance': 800, 'deeds': 1200})
        self.assertEqual(row['field_observed_at']['resources']['suffused'], 900)
        self.repo.ingest('prime', 'Hero', {'wealth': {'deeds': 99, 'deeds_observed_at': 100}}, 1400)
        self.assertEqual(self.repo.get('prime', 'hero')['snapshot']['wealth']['deeds'], 0)
        self.assertIsNone(self.repo.get('test', 'hero'))

    def test_validation(self):
        for section, field in [('wealth', 'bank_balance'), ('wealth', 'deeds'), ('wealth', 'deeds_observed_at'),
                               ('wealth', 'bank_balance_observed_at'), ('resources', 'suffused'), ('resources', 'suffused_observed_at')]:
            for value in [-1, '123', True, float('inf')]:
                with self.subTest(section=section, field=field, value=value), self.assertRaises(ValueError):
                    validate_profile({section: {field: value}})
        with self.assertRaises(ValueError):
            validate_profile({'wealth': []})
        validate_profile({'wealth': {'bank_balance': 0, 'deeds': None}})
