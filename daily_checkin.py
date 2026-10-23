"""Durable daily check-ins. Importing/constructing this module never starts a game.

Live operations require an explicit server-side opt-in. Workers only launch or
close sessions; the coordinator advances from committed reporter receipts.
"""
import json
import math
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class CheckinError(ValueError):
    pass


def game_day(timestamp):
    return datetime.fromtimestamp(timestamp, ZoneInfo('America/New_York')).date().isoformat()


DEFAULTS = dict(enabled=False, time='00:15', parallel_accounts=4, freshness_hours=22)
TERMINAL = {'complete', 'partial', 'failed', 'attention', 'cancelled'}
ACTIVE = {'logging_in', 'startup', 'capturing', 'persisting', 'logging_out'}
REQUIRED = ('character', 'stats', 'skills', 'bonuses', 'experience', 'resources', 'deeds', 'reward_info')


def captured_value(data, key, job, now):
    """A receipt flag alone cannot certify a missing or stale parsed value."""
    def number(value):
        return type(value) in (int,float) and math.isfinite(value) and value>=0
    def fresh(value):
        return type(value) in (int,float) and job['requested_at']<=value<=now+5
    section={'deeds':'wealth','bank':'wealth','reward_info':'login_rewards'}.get(key,key)
    values=data.get(section)
    if not isinstance(values,dict): return False
    if key in ('deeds','bank'):
        field='deeds' if key=='deeds' else 'bank_balance'
        return number(values.get(field)) and fresh(values.get(field+'_observed_at'))
    if key=='reward_info':
        return type(values.get('streak')) is int and 1<=values['streak']<=30 and fresh(values.get('observed_at'))
    availability=(data.get('metadata') or {}).get('availability',{}).get(section,{})
    if availability.get('available') is not True or not fresh(availability.get('collected_at')): return False
    if key=='character': return str(values.get('name','')).casefold()==job['character'].casefold()
    if key=='stats':
        names=('strength','constitution','dexterity','agility','discipline','aura','logic','intuition','wisdom','influence')
        return all(isinstance(values.get(k),dict) and number(values[k].get('value')) and type(values[k].get('bonus')) in (int,float) for k in names)
    if key=='skills': return all(isinstance(v,dict) and number(v.get('ranks')) for v in values.values())
    if key=='bonuses': return values.get('lumnis_stage') in (2,3,4,5,'ready','expired','unavailable') and fresh(values.get('observed_at'))
    if key=='resources': return number(values.get('weekly')) and number(values.get('total')) and fresh(values.get('observed_at'))
    if key=='experience': return number(values.get('lifetime_exp'))
    return False


class CheckinCoordinator:
    def __init__(self, config, service, telemetry, clock=time.time):
        self.config, self.service, self.telemetry, self.clock = config, service, telemetry, clock
        self.db, self.lock = telemetry.db, telemetry.lock
        self.futures = {}
        self.executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix='gempy-checkin')
        self.halt = threading.Event()
        self.thread = None
        self.leader = None
        self.scheduler_error = None
        with self.lock, self.db:
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS checkin_settings (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS checkin_runs (id TEXT PRIMARY KEY, started REAL, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS checkin_jobs (id TEXT PRIMARY KEY, run_id TEXT, data TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS checkin_job_run ON checkin_jobs(run_id);
              CREATE TABLE IF NOT EXISTS checkin_reservations (account TEXT PRIMARY KEY, job_id TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS checkin_events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT,
                job_id TEXT, at REAL, phase TEXT, message TEXT);
              CREATE TABLE IF NOT EXISTS checkin_observations (realm TEXT, character TEXT, day TEXT,
                captured REAL, streak INTEGER, PRIMARY KEY(realm,character));
              CREATE TABLE IF NOT EXISTS checkin_captures (capture_id TEXT PRIMARY KEY, job_id TEXT,
                session_id TEXT, received REAL, data TEXT NOT NULL);
            ''')

    @property
    def allowed(self):
        return self.config.get('daily_checkin', {}).get('allow_live_operations') is True

    def settings(self):
        row = self.db.execute('SELECT data FROM checkin_settings WHERE id=1').fetchone()
        return DEFAULTS | (json.loads(row[0]) if row else {})

    def update_settings(self, data):
        with self.lock, self.db:
            if not isinstance(data, dict) or set(data) - set(DEFAULTS):
                raise ValueError('Unknown check-in settings.')
            cfg = self.settings() | data
            if type(cfg['enabled']) is not bool:
                raise ValueError('Enabled must be true or false.')
            if cfg['enabled'] and not self.allowed:
                raise CheckinError('Live check-ins are disabled on this server. Complete the pilot before enabling scheduling.')
            for key, low, high in [('parallel_accounts', 1, 16), ('freshness_hours', 1, 23)]:
                if type(cfg[key]) is not int or not low <= cfg[key] <= high:
                    raise ValueError(f'{key} must be between {low} and {high}.')
            try:
                parsed = datetime.strptime(cfg['time'], '%H:%M')
                if parsed.strftime('%H:%M') != cfg['time']: raise ValueError()
            except (ValueError, TypeError):
                raise ValueError('Schedule time must be HH:MM in Eastern time.') from None
            self.db.execute('INSERT OR REPLACE INTO checkin_settings VALUES(1,?)', (json.dumps(cfg),))
            return cfg

    def roster(self):
        aliases = self.config.get('daily_checkin', {}).get('account_ids', {})
        seen = set()
        rows = []
        for label, names in self.config.get('accounts', {}).items():
            account = str(aliases.get(label, label)).casefold()
            for name in names:
                if not isinstance(name, str) or name.casefold() in seen:
                    raise CheckinError('Every character must occur once in the configured roster.')
                seen.add(name.casefold())
                rows.append(dict(account=account, account_label=label, character=name))
        return rows

    def _runs(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM checkin_runs ORDER BY started DESC, rowid DESC LIMIT 30')]

    def assert_roster_editable(self):
        """Caller holds the telemetry lock through the subsequent roster edit."""
        with self.lock:
            if any(r['status'] in ('running','paused','stopping') for r in self._runs()) or self.db.execute('SELECT 1 FROM checkin_reservations LIMIT 1').fetchone():
                raise CheckinError('Finish the check-in run and resolve reserved sessions before editing the roster.')

    def _jobs(self, run_id):
        return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM checkin_jobs WHERE run_id=? ORDER BY rowid', (run_id,))]

    def _save_run(self, run):
        self.db.execute('INSERT OR REPLACE INTO checkin_runs VALUES(?,?,?)', (run['id'], run['started_at'], json.dumps(run)))

    def _save_job(self, job, **values):
        old = job.get('status')
        job.update(values, updated_at=self.clock())
        self.db.execute('INSERT INTO checkin_jobs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        (job['id'], job['run_id'], json.dumps(job)))
        if old != job['status'] or 'message' in values:
            self.db.execute('INSERT INTO checkin_events(run_id,job_id,at,phase,message) VALUES(?,?,?,?,?)',
                            (job['run_id'], job['id'], self.clock(), job['status'], job.get('message', '')))

    def snapshot(self, run_id=None):
        with self.lock:
            runs = self._runs()
            run = next((r for r in runs if r['id'] == run_id), None) if run_id else (runs[0] if runs else None)
            if run_id and run is None:
                row = self.db.execute('SELECT data FROM checkin_runs WHERE id=?', (run_id,)).fetchone()
                run = json.loads(row[0]) if row else None
                if run is None: raise CheckinError('Unknown run.')
            if run:
                run = dict(run, jobs=self._jobs(run['id']))
            return dict(allowed=self.allowed, settings=self.settings(), run=run, history=runs,
                        roster=self.roster(), now=self.clock(), game_day=game_day(self.clock()),
                        scheduler_error=self.scheduler_error,
                        disabled_reason=None if self.allowed else 'Live execution is disabled. Preview the page safely; enable only after a supervised pilot.')

    def start_run(self, mode='due', trigger='manual'):
        if not self.allowed:
            raise CheckinError('Live execution is disabled on this server.')
        if mode not in ('due', 'refresh_all'):
            raise ValueError('Unknown run mode.')
        with self.lock, self.db:
            existing = next((r for r in self._runs() if r['status'] in ('running', 'paused', 'stopping')), None)
            if existing: return existing
            now = self.clock()
            run = dict(id=secrets.token_hex(12), started_at=now, finished_at=None, game_day=game_day(now),
                       status='running', mode=mode, trigger=trigger)
            realm = self.config.get('daily_checkin', {}).get('realm', 'prime')
            if realm not in ('prime', 'test'): raise CheckinError('Unsupported check-in realm.')
            if self.config.get('daily_checkin', {}).get('startup_mode','ack') not in ('ack','none'):
                raise CheckinError('Startup mode must be ack or none.')
            roster = self.roster()
            self._save_run(run)
            for identity in roster:
                observation = self.db.execute('SELECT * FROM checkin_observations WHERE realm=? AND character=?',
                                               (realm, identity['character'].casefold())).fetchone()
                satisfied = mode == 'due' and observation and observation['day'] == run['game_day'] and now-observation['captured'] < self.settings()['freshness_hours']*3600
                job = dict(**identity, id=secrets.token_hex(12), run_id=run['id'], realm=realm,
                           status='complete' if satisfied else 'queued', attempt=0, session_id=None, owned=False,
                           capture_id=None, requested_at=None, deadline=None, next_attempt=now, fields={},
                           credit='observed' if satisfied else 'unknown', cleanup='not_needed',
                           captured_at=observation['captured'] if satisfied else None,
                           streak=observation['streak'] if satisfied else None,
                           message='Already checked in; required data is fresh.' if satisfied else 'Waiting to start.')
                self._save_job(job)
            return run

    def control(self, run_id, action):
        with self.lock, self.db:
            run = self.snapshot(run_id)['run']; run.pop('jobs')
            if action not in ('pause', 'resume', 'stop'): raise ValueError('Unknown action.')
            if run['status'] not in ('running','paused','stopping'): return run
            if action=='resume' and run['status']=='stopping': raise CheckinError('A stopped run cannot resume.')
            run['status'] = {'pause':'paused','resume':'running','stop':'stopping'}[action]
            self._save_run(run)
            return run

    def retry(self, job_id):
        if not self.allowed: raise CheckinError('Live execution is disabled on this server.')
        with self.lock, self.db:
            row = self.db.execute('SELECT data FROM checkin_jobs WHERE id=?', (job_id,)).fetchone()
            if not row: raise CheckinError('Unknown job.')
            job=json.loads(row[0])
            if job['status'] not in ('partial','failed','attention','cancelled'): return job
            previous_day=self.snapshot(job['run_id'])['run']['game_day'] != game_day(self.clock())
            if job['owned'] and job['cleanup'] != 'closed':
                members={r['character'].casefold() for r in self.roster() if r['account']==job['account']}
                known={r['character'].casefold() for r in self.roster()}
                if any(s.get('character','').casefold() in members or s.get('character','').casefold() not in known for s in self.service.sessions()):
                    raise CheckinError('Inspect the remaining session before retrying. It must be closed manually.')
                job.update(owned=False,cleanup='closed')
            if previous_day:
                self._release(job)
                self._save_job(job,status='partial',message='Prior-day reservation cleared. Start a new run for the current game day.')
                return job
            active = next((r for r in self._runs() if r['status'] in ('running','paused','stopping')),None)
            if active and active['id']!=job['run_id']:
                self._release(job)
                self._save_job(job,status='partial',message='Historical reservation resolved. The current run owns further check-ins.')
                return job
            run=self.snapshot(job['run_id'])['run'];run.pop('jobs')
            run.update(status='running',finished_at=None)
            self._save_run(run)
            self._release(job)
            self._save_job(job,status='queued',attempt=0,next_attempt=self.clock(),session_id=None,owned=False,
                           capture_id=None,fields={},message='Queued for retry.')
            return job

    def takeover(self, job_id):
        with self.lock,self.db:
            row=self.db.execute('SELECT data FROM checkin_jobs WHERE id=?',(job_id,)).fetchone()
            if not row: raise CheckinError('Unknown job.')
            job=json.loads(row[0])
            if job['status'] not in ('startup','capturing','persisting','attention') or not job['session_id']:
                raise CheckinError('Takeover is not available while login or logout is in progress.')
            self._save_job(job,status='attention',owned=False,cleanup='user_owned',message='Session kept for manual play. Automatic logout disabled.')
            self._release(job)
            return job

    def events(self, run_id, after=0):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM checkin_events WHERE run_id=? AND id>? ORDER BY id LIMIT 200', (run_id, after))]

    def report(self, data, session_id):
        """Called only AFTER authenticated telemetry ingest has committed."""
        with self.lock, self.db:
            jobs=[json.loads(r[0]) for r in self.db.execute('SELECT data FROM checkin_jobs')]
            released=next((j for j in jobs if j['session_id']==session_id and j['cleanup']=='user_owned'),None)
            if released: return {'checkin_release':released['capture_id']}
            job=next((j for j in jobs if j['session_id']==session_id and j['status'] in ('startup','capturing')),None)
            if not job: return {}
            incoming=data.get('checkin')
            request=dict(capture_id=job['capture_id'], requested_at=job['requested_at'],
                         startup_mode=self.config.get('daily_checkin',{}).get('startup_mode','ack'))
            if not isinstance(incoming,dict) or incoming.get('capture_id')!=job['capture_id']:
                return {'checkin_request':request}
            if incoming.get('startup_ready') is not True:
                return {'checkin_request':request}
            if job['status']=='startup':
                self._save_job(job,status='capturing',deadline=self.clock()+180,message='Startup ready; capturing required observations.')
            if incoming.get('phase')!='captured': return {'checkin_request':request}
            fields=incoming.get('fields')
            if not isinstance(fields,dict) or len(fields)>32: return {'checkin_request':request}
            clean={}
            for key in REQUIRED+('bank',):
                value=fields.get(key,{})
                if not isinstance(value,dict): continue
                state=value.get('status')
                observed=value.get('observed_at')
                if state not in ('captured','unavailable','timeout','not_applicable'): continue
                if type(observed) not in (int,float) or not job['requested_at']<=observed<=self.clock()+5:
                    state='unavailable';observed=None
                # Only profession resources can be explicitly inapplicable.
                if state=='not_applicable' and key!='resources': state='unavailable'
                if state=='captured' and not captured_value(data,key,job,self.clock()): state='unavailable'
                clean[key]={'status':state,'observed_at':observed}
            present=incoming.get('presence_at')
            credit=type(present) in (int,float) and job['requested_at']<=present<=self.clock()+5 and clean.get('character',{}).get('status')=='captured'
            complete=credit and all(clean.get(k,{}).get('status') in ('captured','not_applicable') for k in REQUIRED)
            same_day=credit and game_day(present)==self.snapshot(job['run_id'])['run']['game_day']
            streak=incoming.get('streak')
            if type(streak) is not int or not 1<=streak<=30: streak=None
            self._save_job(job, status='persisting',fields=clean,credit='presence_observed' if credit else 'unknown',
                           credit_day=game_day(present) if credit else None,streak=streak,captured_at=self.clock() if complete else None,
                           outcome='complete' if complete and same_day else 'partial',receipt_sequence=data.get('sequence'),
                           message='Capture saved after the requested game day ended.' if complete and not same_day else 'Capture saved.' if complete else 'Capture saved with missing required fields.')
            self.db.execute('INSERT OR REPLACE INTO checkin_captures VALUES(?,?,?,?,?)',
                            (job['capture_id'],job['id'],session_id,self.clock(),json.dumps(data)))
            if complete:
                self.db.execute('INSERT OR REPLACE INTO checkin_observations VALUES(?,?,?,?,?)',
                                (job['realm'],job['character'].casefold(),game_day(present),self.clock(),streak))
            return {'checkin_ack':job['capture_id']}

    def _release(self, job):
        self.db.execute('DELETE FROM checkin_reservations WHERE account=? AND job_id=?',(job['account'],job['id']))

    def _schedule(self):
        cfg=self.settings()
        if not cfg['enabled']: return
        runs=self._runs()
        if any(r['status'] in ('running','paused','stopping') for r in runs): return
        local=datetime.fromtimestamp(self.clock(),ZoneInfo('America/New_York'))
        today=local.date().isoformat()
        if local.strftime('%H:%M')<cfg['time']: return
        scheduled=next((r for r in runs if r['game_day']==today and r['trigger']=='scheduled'),None)
        if not scheduled:
            self.start_run(trigger='scheduled');return
        # Catch up successful captures approaching the freshness limit, without
        # repeatedly replaying failures or user-stopped runs throughout the day.
        if scheduled['status']=='cancelled': return
        # One catch-up window per day. A failed/stopped catch-up is not silently
        # retried hourly; the next daily run or explicit retry owns that decision.
        if any(r['game_day']==today and r['trigger']=='freshness' for r in runs): return
        realm=self.config.get('daily_checkin',{}).get('realm','prime')
        names={r['character'].casefold() for r in self.roster()}
        observations=[r for r in self.db.execute('SELECT character,captured FROM checkin_observations WHERE realm=? AND day=?',(realm,today)) if r['character'] in names]
        if observations and min(r['captured'] for r in observations)<=self.clock()-cfg['freshness_hours']*3600 and self.clock()-runs[0]['started_at']>=3600:
            self.start_run(trigger='freshness')

    def tick(self):
        if not self.allowed or self.halt.is_set(): return
        with self.lock, self.db:
            self._schedule()
            run=next((r for r in self._runs() if r['status'] in ('running','paused','stopping')),None)
            if not run: return
            sessions=self.service.sessions()
            roster=self.roster()
            membership={r['character'].casefold():r['account'] for r in roster}
            unknown=any(s.get('character','').casefold() not in membership for s in sessions)
            jobs=self._jobs(run['id'])
            for job in jobs:
                pending=self.futures.get(job['id'])
                if pending and pending.done():
                    del self.futures[job['id']]
                    try:
                        value=pending.result()
                        if job['status']=='logging_in':
                            self._save_job(job,session_id=value['id'],owned=True,status='startup',cleanup='pending',
                                           requested_at=int(self.clock()),deadline=self.clock()+180,message='Waiting for login scripts and reporter.')
                        else:
                            # A successful adapter result must explicitly confirm closure.
                            if value.get('disconnected') is not True: raise RuntimeError('Closure not confirmed')
                            self._release(job)
                            self._save_job(job,status=job.get('outcome','partial'),cleanup='closed',message='Session closed.')
                    except Exception:
                        # A failed launch can leave a child behind. Never guess ownership.
                        self._save_job(job,status='attention',cleanup='unknown',owned=True,
                                       message='Session operation failed. Inspect this account before retrying.')
                if job['id'] in self.futures: continue
                if run['status']=='stopping' and job['status'] in ('queued','waiting','retry_wait'):
                    self._save_job(job,status='cancelled',message='Cancelled before login.');continue
                if run['game_day']!=game_day(self.clock()) and job['status'] in ('queued','waiting','retry_wait'):
                    self._save_job(job,status='partial',message='Game day ended before this character could start.');continue
                if job['status'] in ('startup','capturing'):
                    if self.clock()>=job['deadline'] or run['status']=='stopping':
                        self._save_job(job,status='persisting',outcome='cancelled' if run['status']=='stopping' else 'partial',
                                       message='Capture stopped.' if run['status']=='stopping' else 'Startup or capture timed out.')
                if job['status']=='persisting':
                    current=next((s for s in sessions if s['id']==job['session_id']),None)
                    if not current:
                        self._release(job)
                        self._save_job(job,status=job.get('outcome','partial'),cleanup='closed',message='Session is no longer running.')
                    elif not job['owned'] or current.get('attachment')!='Headless':
                        self._save_job(job,status='attention',message='A client attached or ownership changed. Automatic logout suspended.')
                    else:
                        self._save_job(job,status='logging_out',message='Capture saved; logging out.')
                        self.futures[job['id']]=self.executor.submit(self._disconnect,job['session_id'])
            # Launch only after persisting each reservation and intent. One slot
            # per distinct account, also shared with manual launch entry points.
            active_count=sum(j['status'] in ACTIVE for j in jobs)
            if run['status']=='running':
                for job in jobs:
                    if job['status'] not in ('queued','waiting','retry_wait') or self.clock()<job['next_attempt']: continue
                    occupied=next((s for s in sessions if membership.get(s.get('character','').casefold())==job['account']),None)
                    reserved=self.db.execute('SELECT job_id FROM checkin_reservations WHERE account=?',(job['account'],)).fetchone()
                    if unknown or occupied or reserved:
                        reason='Unmapped session is running.' if unknown else (f"Waiting: {occupied['character']} is online." if occupied else 'Account reserved by another check-in.')
                        if job['status']!='waiting' or job['message']!=reason:
                            self._save_job(job,status='waiting',message=reason)
                        continue
                    if active_count>=self.settings()['parallel_accounts']: break
                    self.db.execute('INSERT INTO checkin_reservations VALUES(?,?)',(job['account'],job['id']))
                    capture_id=secrets.token_hex(24)
                    self._save_job(job,status='logging_in',attempt=job['attempt']+1,capture_id=capture_id,
                                   message='Starting a headless Lich session.')
                    self.db.commit()  # Reservation must be visible to the launch adapter.
                    context={'capture_id':capture_id,'startup_mode':self.config.get('daily_checkin',{}).get('startup_mode','ack')}
                    self.futures[job['id']]=self.executor.submit(self.service.start_checkin,job['character'],job['realm'],job['id'],context)
                    active_count+=1
            jobs=self._jobs(run['id'])
            if all(j['status'] in TERMINAL for j in jobs):
                status='cancelled' if run['status']=='stopping' else ('complete' if all(j['status']=='complete' for j in jobs) else 'attention')
                run.update(status=status,finished_at=self.clock());self._save_run(run)

    def _disconnect(self, session_id):
        current=next((s for s in self.service.sessions() if s['id']==session_id),None)
        if not current: return {'disconnected':True}
        if current.get('attachment')!='Headless': raise CheckinError('Session has a client; cleanup suspended.')
        # Production adapter rechecks attachment while holding its session lock.
        if hasattr(self.service,'disconnect_checkin'):
            return self.service.disconnect_checkin(session_id)
        return self.service.disconnect(session_id)

    def reconcile(self):
        with self.lock,self.db:
            for row in self.db.execute('SELECT data FROM checkin_jobs').fetchall():
                job=json.loads(row[0])
                if job['status'] in ACTIVE:
                    self._save_job(job,status='attention',owned=True,cleanup='unknown',message='Service restarted during this attempt. Inspect the session before retrying.')

    def start(self):
        if not self.allowed or self.thread: return
        from account_guard import host_lock
        self.leader=host_lock(self.telemetry.path.parent,'checkin-coordinator',blocking=False)
        try: self.leader.__enter__()
        except (OSError, CheckinError):
            self.leader=None;self.scheduler_error='Another coordinator is active.';return
        self.reconcile()
        def loop():
            while not self.halt.is_set():
                try:
                    self.tick();self.scheduler_error=None
                except Exception:
                    self.scheduler_error='Check-in coordinator could not advance. Review configuration and session state.'
                self.halt.wait(1)
        self.thread=threading.Thread(target=loop,name='gempy-checkin',daemon=True);self.thread.start()

    def close(self):
        self.halt.set()
        if self.thread: self.thread.join(timeout=3)
        self.executor.shutdown(wait=True,cancel_futures=True)
        if self.leader: self.leader.__exit__(None,None,None);self.leader=None
