"""Offline tests: never load real configuration or create a Lich process."""
import copy
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from daily_checkin import CheckinCoordinator, CheckinError, game_day


class FakeService:
    def __init__(self):
        self.online = []
        self.started = []
        self.closed = []

    def sessions(self):
        return copy.deepcopy(self.online)

    def start_checkin(self, character, realm, job_id, context):
        session = dict(id=job_id + ':1', pid=100 + len(self.started), character=character,
                       realm=realm, attachment='Headless', running=True)
        self.started.append((character, job_id, context))
        self.online.append(session)
        return session

    def disconnect(self, session_id, force=False):
        assert not force
        self.closed.append(session_id)
        self.online = [s for s in self.online if s['id'] != session_id]
        return {'disconnected': True}


class CheckinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(Path(self.tmp.name) / 'telemetry.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.telemetry = SimpleNamespace(db=self.db, lock=threading.RLock(), path=Path(self.tmp.name)/'telemetry.sqlite3')
        self.service = FakeService()
        self.now = 1792732800.0
        self.config = {'accounts': {'A': ['Alpha', 'Beta'], 'B': ['Gamma']},
                       'daily_checkin': {'allow_live_operations': True, 'startup_mode': 'none'}}
        self.engine = CheckinCoordinator(self.config, self.service, self.telemetry, clock=lambda: self.now)

    def tearDown(self):
        self.engine.close()
        self.db.close()
        self.tmp.cleanup()

    def pump(self, predicate, count=100):
        for _ in range(count):
            self.engine.tick()
            if predicate(): return
            time.sleep(.005)
        self.fail('Fake worker did not reach expected state')

    def capture(self, job, **overrides):
        self.pump(lambda: next(j for j in self.engine.snapshot()['run']['jobs'] if j['id']==job['id'])['session_id'] is not None)
        session = next(s for s in self.service.online if s['character'] == job['character'])
        fields = {k: {'status': 'captured', 'observed_at': self.now} for k in
                  ('character', 'stats', 'skills', 'bonuses', 'experience', 'resources', 'deeds', 'reward_info')}
        report = dict(capture_id=job['capture_id'], startup_ready=True, phase='captured', fields=fields,
                      presence_at=self.now, streak=12)
        report.update(overrides)
        payload=self.payload(job)
        payload.update(checkin=report,reporter_id='reporter',sequence=10)
        return self.engine.report(payload,session['id'])

    def payload(self,job):
        return dict(character={'name':job['character']},
                    stats={k:{'value':80,'bonus':15} for k in ('strength','constitution','dexterity','agility','discipline','aura','logic','intuition','wisdom','influence')},
                    skills={'arcane_symbols':{'ranks':20,'bonus':90}},
                    bonuses={'lumnis_stage':'expired','observed_at':self.now},
                    experience={'lifetime_exp':1000},resources={'weekly':1,'total':5,'observed_at':self.now},
                    wealth={'deeds':5,'deeds_observed_at':self.now},login_rewards={'streak':12,'observed_at':self.now},
                    metadata={'availability':{k:{'available':True,'collected_at':self.now} for k in ('character','stats','skills','bonuses','experience','resources')}})

    def test_receipt_without_actual_values_cannot_complete(self):
        self.engine.start_run();self.pump(lambda:len(self.service.started)==2)
        job=self.engine.snapshot()['run']['jobs'][0]
        self.payload=lambda job:{}
        self.capture(job)
        self.assertEqual(self.engine.snapshot()['run']['jobs'][0]['outcome'],'partial')

    def test_disabled_by_default_never_starts(self):
        self.engine.config['daily_checkin']['allow_live_operations'] = False
        with self.assertRaises(CheckinError): self.engine.start_run()
        self.engine.tick()
        self.assertEqual(self.service.started, [])

    def test_accounts_parallel_but_same_account_serial_and_capture_before_logout(self):
        self.engine.start_run()
        self.pump(lambda: len(self.service.started) == 2)
        self.assertEqual({x[0] for x in self.service.started}, {'Alpha', 'Gamma'})
        self.assertEqual(self.service.closed, [])
        jobs = self.engine.snapshot()['run']['jobs']
        alpha = next(j for j in jobs if j['character'] == 'Alpha')
        self.capture(alpha)
        self.pump(lambda: any(x[0] == 'Beta' for x in self.service.started))
        self.assertEqual(len(self.service.closed), 1)
        self.assertEqual(next(j for j in self.engine.snapshot()['run']['jobs'] if j['character']=='Alpha')['status'], 'complete')

    def test_occupied_account_deferred_other_accounts_continue(self):
        self.service.online.append(dict(id='external:1', character='Alpha', realm='prime', attachment='Attached'))
        self.engine.start_run()
        self.pump(lambda: len(self.service.started) == 1)
        self.assertEqual(self.service.started[0][0], 'Gamma')
        self.assertEqual(self.service.closed, [])
        self.assertEqual(sum(j['status']=='waiting' for j in self.engine.snapshot()['run']['jobs']), 2)

    def test_wrong_capture_and_stale_fields_do_not_finish(self):
        self.engine.start_run()
        self.pump(lambda: len(self.service.started)==2)
        alpha = self.engine.snapshot()['run']['jobs'][0]
        self.capture(alpha, capture_id='wrong')
        self.engine.tick()
        self.assertEqual(self.service.closed, [])
        self.capture(alpha, fields={'stats': {'status':'captured','observed_at':self.now-600}})
        self.engine.tick()
        self.assertNotEqual(self.engine.snapshot()['run']['jobs'][0]['status'], 'complete')

    def test_pause_prevents_more_starts_and_stop_cancels_queued(self):
        run = self.engine.start_run()
        self.engine.control(run['id'], 'pause')
        self.engine.tick()
        self.assertEqual(self.service.started, [])
        self.engine.control(run['id'], 'stop')
        self.engine.tick()
        self.assertEqual(self.engine.snapshot()['run']['status'], 'cancelled')

    def test_attachment_prevents_automatic_logout(self):
        self.engine.start_run()
        self.pump(lambda: len(self.service.started)==2)
        alpha = self.engine.snapshot()['run']['jobs'][0]
        self.service.online[0]['attachment']='Attached'
        self.capture(alpha)
        self.pump(lambda: self.engine.snapshot()['run']['jobs'][0]['status']=='attention')
        self.assertEqual(self.service.closed, [])

    def test_restart_preserves_completed_jobs_and_blocks_uncertain_sessions(self):
        self.engine.start_run()
        self.pump(lambda: len(self.service.started)==2)
        self.engine.close()
        self.engine = CheckinCoordinator(self.config, self.service, self.telemetry, clock=lambda:self.now)
        self.engine.reconcile()
        self.assertTrue(any(j['status']=='attention' for j in self.engine.snapshot()['run']['jobs']))
        self.assertEqual(self.service.closed, [])

    def test_settings_validation_and_schedule_disabled(self):
        with self.assertRaises(ValueError): self.engine.update_settings({'parallel_accounts': 0})
        with self.assertRaises(ValueError): self.engine.update_settings({'time': '25:00'})
        with self.assertRaises(ValueError): self.engine.update_settings({'enabled': 'yes'})
        self.engine.tick()
        self.assertIsNone(self.engine.snapshot()['run'])

    def test_new_run_is_idempotent_while_active(self):
        a=self.engine.start_run(); b=self.engine.start_run()
        self.assertEqual(a['id'],b['id'])

    def test_game_day_uses_eastern_not_utc(self):
        from datetime import datetime, timezone
        ts=datetime(2026,10,23,2,tzinfo=timezone.utc).timestamp()
        self.assertEqual(game_day(ts), '2026-10-22')

    def test_roster_edit_blocked_while_run_active(self):
        self.engine.assert_roster_editable()
        run=self.engine.start_run()
        with self.assertRaises(CheckinError):self.engine.assert_roster_editable()
        self.engine.control(run['id'],'stop');self.engine.tick()
        self.engine.assert_roster_editable()

    def test_queued_jobs_expire_at_day_rollover_without_launch(self):
        self.engine.start_run()
        self.now+=86400
        self.engine.tick()
        self.assertEqual(self.service.started,[])
        self.assertTrue(all(j['status']=='partial' for j in self.engine.snapshot()['run']['jobs']))

    def test_takeover_disarms_cleanup_and_returns_reporter_release(self):
        self.engine.start_run();self.pump(lambda:len(self.service.started)==2)
        self.pump(lambda:self.engine.snapshot()['run']['jobs'][0]['session_id'] is not None)
        job=self.engine.snapshot()['run']['jobs'][0]
        result=self.engine.takeover(job['id'])
        self.assertFalse(result['owned'])
        self.assertEqual(self.engine.report({},job['session_id']),{'checkin_release':job['capture_id']})
        self.engine.tick();self.assertEqual(self.service.closed,[])

    def test_successful_capture_is_durable_and_idempotent(self):
        self.engine.start_run();self.pump(lambda:len(self.service.started)==2)
        job=self.engine.snapshot()['run']['jobs'][0]
        receipt=self.capture(job)
        self.assertEqual(receipt['checkin_ack'],job['capture_id'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM checkin_captures').fetchone()[0],1)
        current=self.engine.snapshot()['run']['jobs'][0]
        self.engine.report({'checkin': {'capture_id': job['capture_id'], 'phase': 'captured'}}, current['session_id'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM checkin_captures').fetchone()[0],1)

    def test_logout_failure_keeps_account_reserved(self):
        self.engine.start_run();self.pump(lambda:len(self.service.started)==2)
        job=self.engine.snapshot()['run']['jobs'][0]
        def broken(*args,**kwargs):raise RuntimeError('fake logout failure')
        self.service.disconnect=broken
        self.capture(job)
        self.pump(lambda:self.engine.snapshot()['run']['jobs'][0]['status']=='attention')
        self.assertFalse(any(c[0]=='Beta' for c in self.service.started))

    def test_retry_after_manual_close_releases_blocked_reservation(self):
        self.engine.start_run();self.pump(lambda:len(self.service.started)==2)
        self.pump(lambda:self.engine.snapshot()['run']['jobs'][0]['session_id'] is not None)
        job=self.engine.snapshot()['run']['jobs'][0]
        self.engine.reconcile()
        self.service.online=[s for s in self.service.online if s['character']!='Alpha']
        self.assertEqual(self.engine.retry(job['id'])['status'],'queued')

    def test_scheduled_run_only_after_eastern_time_and_once_per_day(self):
        from datetime import datetime,timezone
        self.now=datetime(2026,10,23,4,10,tzinfo=timezone.utc).timestamp()
        self.engine.update_settings({'enabled':True})
        self.engine.tick();self.assertIsNone(self.engine.snapshot()['run'])
        self.now+=600;self.engine.tick()
        run=self.engine.snapshot()['run'];self.assertEqual(run['trigger'],'scheduled')
        self.engine.control(run['id'],'stop');self.pump(lambda:self.engine.snapshot()['run']['status']=='cancelled')
        self.engine.tick();self.assertEqual(len(self.engine.snapshot()['history']),1)

    def test_prior_day_reservation_can_be_resolved_after_manual_close(self):
        self.engine.start_run();self.pump(lambda:len(self.service.started)==2)
        self.engine.close()
        self.engine=CheckinCoordinator(self.config,self.service,self.telemetry,clock=lambda:self.now)
        self.engine.reconcile()
        job=self.engine.snapshot()['run']['jobs'][0]
        self.now+=86400;self.service.online=[]
        result=self.engine.retry(job['id'])
        self.assertEqual(result['status'],'partial')
        self.assertIsNone(self.db.execute('SELECT 1 FROM checkin_reservations WHERE account=?',(job['account'],)).fetchone())

    def test_unrelated_stale_observations_do_not_schedule_refresh(self):
        self.engine.update_settings({'enabled':True})
        run=self.engine.start_run(trigger='scheduled')
        with self.db:
            self.engine._save_run(dict(run,status='complete'))
            self.db.execute('INSERT INTO checkin_observations VALUES(?,?,?,?,?)',('test','removed',game_day(self.now-86400),self.now-86400,1))
        self.now+=7200;self.engine.tick()
        self.assertEqual(len(self.engine.snapshot()['history']),1)

    def test_historical_reservation_resolves_while_new_run_active(self):
        run=self.engine.start_run();self.pump(lambda:len(self.service.started)==2)
        self.engine.close()
        self.engine=CheckinCoordinator(self.config,self.service,self.telemetry,clock=lambda:self.now)
        self.engine.reconcile()
        old=self.engine.snapshot()['run']['jobs'][0]
        self.engine.control(run['id'],'stop');self.engine.tick()
        current=self.engine.start_run()
        self.service.online=[]
        self.engine.retry(old['id'])
        self.assertIsNone(self.db.execute('SELECT 1 FROM checkin_reservations WHERE account=?',(old['account'],)).fetchone())
        self.assertEqual(self.engine.snapshot()['run']['id'],current['id'])


if __name__ == '__main__': unittest.main()
