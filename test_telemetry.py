import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from telemetry import TelemetryStore

class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=TelemetryStore(self.tmp.name)
        self.sessions=[dict(id='12:100',pid=12,realm='prime',character='Example')]
    def tearDown(self):
        self.store.db.close(); self.tmp.cleanup()
    def snapshot(self,seq=1,normal=100,asc=0,reporter='run1'):
        return dict(version=1,pid=12,realm='prime',reporter_id=reporter,sequence=seq,character=dict(name='Example'),experience=dict(normal_xp=normal,ascension_xp=asc))
    def test_matching_rejects_other_realm_and_pid(self):
        for change in [dict(realm='test'),dict(pid=13)]:
            with self.assertRaises(ValueError): self.store.ingest(self.snapshot()|change,self.sessions)
        self.store.ingest(self.snapshot(),self.sessions)
        self.assertEqual('fresh',self.store.enrich(self.sessions)[0]['telemetry']['status'])
        self.assertEqual('unavailable',self.store.enrich([self.sessions[0]|dict(id='12:101')])[0]['telemetry']['status'])
    def test_duplicates_restart_and_reporter_retirement(self):
        self.store.ingest(self.snapshot(),self.sessions)
        with self.assertRaises(ValueError): self.store.ingest(self.snapshot(),self.sessions)
        self.store.ingest(self.snapshot(2,150,reporter='run2'),self.sessions)
        with self.assertRaises(ValueError): self.store.ingest(self.snapshot(3,1000),self.sessions)
        self.assertEqual(50,self.store.progress()['characters'][0]['normal_xp'])
        self.store.db.close(); self.store=TelemetryStore(self.tmp.name)
        self.store.ingest(self.snapshot(3,175,reporter='run2'),self.sessions)
        self.assertEqual(75,self.store.progress()['characters'][0]['normal_xp'])
    def test_counter_reset_does_not_invent_gain(self):
        self.store.ingest(self.snapshot(normal=1000),self.sessions)
        self.store.ingest(self.snapshot(2,10),self.sessions)
        self.store.ingest(self.snapshot(3,30),self.sessions)
        self.assertEqual(20,self.store.progress()['characters'][0]['normal_xp'])
    def test_stale_and_expiry_use_monotonic(self):
        with patch('telemetry.time.monotonic',return_value=100): self.store.ingest(self.snapshot(),self.sessions)
        with patch('telemetry.time.monotonic',return_value=121): self.assertEqual('stale',self.store.enrich(self.sessions)[0]['telemetry']['status'])
        with patch('telemetry.time.monotonic',return_value=401): self.assertIsNone(self.store.enrich(self.sessions)[0]['telemetry']['snapshot'])
    def test_import_repeat_and_overlapping_buckets(self):
        date=self.store._date(__import__('time').time()); week=self.store._period(date,'week')
        path=Path(self.tmp.name)/'GSIV'/'Example'/'exp_sagapanel_history.yaml'; path.parent.mkdir(parents=True)
        path.write_text(f'daily:\n  "{date}": {{exp: 100, asc: 50000}}\nweekly:\n  "{week}": {{exp: 120, asc: 50000}}\n')
        self.assertEqual(2,self.store.import_saga([Path(self.tmp.name)])['imported'])
        self.assertEqual(0,self.store.import_saga([Path(self.tmp.name)])['imported'])
        self.store.ingest(self.snapshot(),self.sessions); self.store.ingest(self.snapshot(2,150),self.sessions)
        row=self.store.progress()['characters'][0]
        self.assertEqual(170,row['normal_xp']); self.assertEqual(1,row['atp_equivalent'])
        self.assertEqual(150,row['daily'][0]['normal_xp'])
        self.store.import_saga([Path(self.tmp.name)])
        self.assertEqual(170,self.store.progress()['characters'][0]['normal_xp'])
    def test_custom_range_and_nullable_sections(self):
        self.store.ingest(self.snapshot()|dict(vitals=None,experience=None),self.sessions)
        date=self.store._date(__import__('time').time())
        result=self.store.progress('custom',start=date,end=date)
        self.assertEqual(f'{date}..{date}',result['period_key'])
        with self.assertRaises(ValueError): self.store.progress('custom',start='2026-02-30',end=date)
        with self.assertRaises(ValueError): self.store.ingest(self.snapshot(2)|dict(effects={'spells':{}}),self.sessions)

    def test_dst_wall_clock_boundary(self):
        from datetime import datetime,timezone
        # 5 AM is noon UTC before fall-back and 1 PM UTC after it.
        for stamp,expected in [('2026-10-31T11:59:00+00:00','2026-10-30'),('2026-10-31T12:01:00+00:00','2026-10-31'),('2026-11-01T12:59:00+00:00','2026-10-31'),('2026-11-01T13:01:00+00:00','2026-11-01'),('2026-03-08T11:59:00+00:00','2026-03-07'),('2026-03-08T12:01:00+00:00','2026-03-08')]:
            self.assertEqual(expected,self.store._date(datetime.fromisoformat(stamp).timestamp()))

    def test_all_sums_disjoint_years_and_daily_only_new_months(self):
        with self.store.db:
            self.store.db.execute('INSERT INTO imports VALUES (?,?,?,?,?,?,?,?,?)',('prime','Example','yearly','2025',1000,0,'fixture','digest',1))
            self.store.db.execute('INSERT INTO imports VALUES (?,?,?,?,?,?,?,?,?)',('prime','Example','monthly','2026-01',50,0,'fixture','digest',1))
            self.store.db.execute('INSERT INTO samples VALUES (?,?,?,?,?,?,?)',('prime','Example','2026-02-01',2,20,0,'observed'))
        row=self.store.progress('all')['characters'][0]
        self.assertEqual(1070,row['normal_xp']); self.assertEqual('imported',row['coverage'])
        self.assertEqual(20,self.store.progress('custom',start='2026-02-01',end='2026-02-01')['characters'][0]['normal_xp'])

    def test_malformed_json_shapes_and_settings_raise_value_error(self):
        for data in [dict(default_client=[]),dict(timezone=[]),dict(timezone='../bad'),[],None]:
            with self.assertRaises(ValueError): self.store.update_settings(data)
        for fields in [dict(identity=[]),dict(realm=[]),dict(vitals={'health':{'current':10**400}}),dict(effects={'spells':[{'name':'Test','end_time':10**400}]})]:
            with self.assertRaises(ValueError): self.store.ingest(self.snapshot()|fields,self.sessions)

    def test_boundary_iso_week_and_backup(self):
        from datetime import datetime,timezone
        before=datetime(2026,10,3,11,59,tzinfo=timezone.utc).timestamp()
        after=datetime(2026,10,3,12,1,tzinfo=timezone.utc).timestamp()
        self.assertEqual('2026-10-02',self.store._date(before)); self.assertEqual('2026-10-03',self.store._date(after))
        self.assertEqual('2026-W01',self.store._period('2025-12-31','week'))
        self.assertTrue(Path(self.store.backup()).exists())
    def test_settings_and_payload_validation(self):
        with self.assertRaises(ValueError): self.store.update_settings(dict(timezone='Nonsense/Zone'))
        with self.assertRaises(ValueError): self.store.ingest(self.snapshot()|dict(vitals={'large':'a'*5000}),self.sessions)
        with self.assertRaises(ValueError): self.store.ingest(self.snapshot()|dict(sequence=-1),self.sessions)
        self.assertEqual('compact',self.store.update_settings(dict(density='compact'))['density'])

if __name__=='__main__': unittest.main()
