"""Validated live Lich telemetry and durable, source-labelled experience history."""
import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

DEFAULTS = dict(timezone='America/Los_Angeles', day_boundary=5, stale_seconds=20,
                expiry_seconds=300, default_client='vellum_despana', density='comfortable',
                default_view='live', update_interval=3)
REALMS = {'GS3': 'prime', 'GS4': 'prime', 'GSIV': 'prime', 'GST': 'test',
          'GSF': 'fallen', 'GSIVF': 'fallen', 'prime': 'prime', 'test': 'test', 'fallen': 'fallen'}

class TelemetryStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True,mode=0o700)
        self.path = self.directory / 'telemetry.sqlite3'
        self.lock = threading.RLock()
        self.live = {}
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        os.chmod(self.path,0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
          CREATE TABLE IF NOT EXISTS baselines (realm TEXT, character TEXT, normal INTEGER,
            asc INTEGER, received REAL, PRIMARY KEY(realm,character));
          CREATE TABLE IF NOT EXISTS samples (realm TEXT, character TEXT, date TEXT,
            received REAL, normal INTEGER, asc INTEGER, coverage TEXT);
          CREATE INDEX IF NOT EXISTS sample_identity ON samples(realm,character,date);
          CREATE INDEX IF NOT EXISTS sample_date ON samples(date);
          CREATE TABLE IF NOT EXISTS imports (realm TEXT, character TEXT, bucket TEXT,
            period TEXT, normal INTEGER, asc INTEGER, source TEXT, digest TEXT,
            PRIMARY KEY(realm,character,bucket,period));
          CREATE TABLE IF NOT EXISTS reporters (session TEXT, reporter TEXT, retired INTEGER, PRIMARY KEY(session,reporter));
          CREATE TABLE IF NOT EXISTS sequences (session TEXT, reporter TEXT, sequence INTEGER,
            PRIMARY KEY(session,reporter));
        ''')
        if 'received' not in {r[1] for r in self.db.execute('PRAGMA table_info(imports)')}:
            self.db.execute('ALTER TABLE imports ADD COLUMN received REAL NOT NULL DEFAULT 0')
        self.db.commit()

    def settings(self):
        with self.lock:
            result = dict(DEFAULTS)
            result.update({r['key']: json.loads(r['value']) for r in self.db.execute('SELECT * FROM settings')})
            return result

    def update_settings(self, data):
        if not isinstance(data, dict) or set(data) - set(DEFAULTS):
            raise ValueError('Unknown settings')
        cfg = self.settings() | data
        try:
            ZoneInfo(cfg['timezone'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('Unknown timezone') from None
        for k, low, high in [('day_boundary',0,23), ('stale_seconds',5,3600), ('expiry_seconds',30,86400), ('update_interval',1,60)]:
            if type(cfg[k]) is not int or not low <= cfg[k] <= high:
                raise ValueError(f'Invalid {k}')
        if cfg['expiry_seconds'] <= cfg['stale_seconds']:
            raise ValueError('Expiry must exceed stale interval')
        if cfg['density'] not in ('comfortable','compact') or cfg['default_view'] not in ('live','progress','characters','settings'):
            raise ValueError('Invalid display setting')
        from client_options import CLIENTS
        if not isinstance(cfg['default_client'],str) or cfg['default_client'] not in CLIENTS:
            raise ValueError('Unknown client')
        with self.lock, self.db:
            for key, value in data.items():
                self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key,json.dumps(value)))
        return self.settings()

    def _date(self, timestamp):
        cfg = self.settings()
        local = datetime.fromtimestamp(timestamp, ZoneInfo(cfg['timezone']))
        # Subtract in wall time: the boundary remains 5 AM across DST changes.
        return (local.replace(tzinfo=None) - timedelta(hours=cfg['day_boundary'])).date().isoformat()

    @staticmethod
    def _period(date, period):
        day = datetime.fromisoformat(date)
        if period in ('today','day'): return date
        if period == 'week': return day.strftime('%G-W%V')
        if period == 'month': return date[:7]
        if period == 'year': return date[:4]
        if period == 'all': return 'all'
        raise ValueError('Unknown history period')

    @staticmethod
    def _counter(exp, keys):
        for key in keys:
            value = exp.get(key)
            if type(value) in (int,float) and 0 <= value <= 10**15 and (type(value) is int or math.isfinite(value)):
                return int(value)
        return None

    def ingest(self, data, sessions):
        if not isinstance(data,dict): raise ValueError('Snapshot must be an object')
        try:
            encoded = json.dumps(data, allow_nan=False)
        except (ValueError,TypeError): raise ValueError('Invalid JSON snapshot') from None
        if len(encoded.encode()) > 256_000: raise ValueError('Snapshot too large')
        def check(value, depth=0):
            if depth > 12: raise ValueError('Snapshot too deeply nested')
            if isinstance(value,(dict,list)):
                if len(value)>512: raise ValueError('Snapshot collection too large')
                for item in (value.values() if isinstance(value,dict) else value): check(item,depth+1)
            elif isinstance(value,str) and len(value)>4096: raise ValueError('Snapshot string too long')
        check(data)
        version=data.get('version',data.get('schema_version'))
        if type(version) is not int or version != 1: raise ValueError('Unsupported telemetry version')
        ident = data.get('identity',data)
        if not isinstance(ident,dict): raise ValueError('Identity must be an object')
        char = data.get('character',ident.get('character'))
        name = char.get('name') if isinstance(char,dict) else char
        realm_raw = ident.get('realm',ident.get('game_code',data.get('game_code')))
        realm = REALMS.get(realm_raw) if isinstance(realm_raw,str) else None
        pid, reporter, sequence = ident.get('pid'), ident.get('reporter_id'), ident.get('sequence')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z\-\x27]{0,63}',name): raise ValueError('Invalid character')
        if realm is None or type(pid) is not int or pid<=0: raise ValueError('Invalid session identity')
        if not isinstance(reporter,str) or not re.fullmatch(r'[A-Za-z0-9_:\-]{1,128}',reporter): raise ValueError('Invalid reporter identity')
        if type(sequence) is not int or not 0<=sequence<=2**63-1: raise ValueError('Invalid sequence')
        session = next((s for s in sessions if s['pid']==pid and s['realm']==realm and s['character'].casefold()==name.casefold()),None)
        if session is None: raise ValueError('Reporter does not match a running Lich session')
        if ident.get('process_start') is not None and str(ident['process_start']) != str(session['id']).split(':',1)[-1]:
            raise ValueError('Process start identity does not match')
        name=session['character']
        for section in ('vitals','status','location','injuries','wounds','scars','effects','experience','resources','tracking'):
            if data.get(section) is not None and not isinstance(data[section],dict): raise ValueError(f'{section} must be an object')
        for key,value in (data.get('vitals') or {}).items():
            if value is not None and not isinstance(value,dict): raise ValueError('Vital entries must be objects')
            if isinstance(value,dict):
                for metric in ('current','max','percent'):
                    if value.get(metric) is not None and (type(value[metric]) not in (int,float) or abs(value[metric])>10**15 or (type(value[metric]) is float and not math.isfinite(value[metric]))): raise ValueError('Vital values must be numbers')
        for key,value in (data.get('effects') or {}).items():
            if not isinstance(value,list) or any(not isinstance(effect,dict) or not isinstance(effect.get('name'),str) for effect in value): raise ValueError('Effect categories require named effect objects')
            for effect in value:
                for metric in ('remaining_seconds','end_time'):
                    if effect.get(metric) is not None and (type(effect[metric]) not in (int,float) or abs(effect[metric])>10**15 or (type(effect[metric]) is float and not math.isfinite(effect[metric]))): raise ValueError('Effect times must be numbers')
        session_id = session['id']
        now, monotonic = time.time(),time.monotonic()
        with self.lock, self.db:
            old = self.db.execute('SELECT sequence FROM sequences WHERE session=? AND reporter=?',(session_id,reporter)).fetchone()
            if old and sequence<=old['sequence']: raise ValueError('Duplicate or out-of-order snapshot')
            retired_row=self.db.execute('SELECT retired FROM reporters WHERE session=? AND reporter=?',(session_id,reporter)).fetchone()
            if retired_row and retired_row['retired']: raise ValueError('Retired reporter')
            self.db.execute('UPDATE reporters SET retired=1 WHERE session=? AND reporter!=?',(session_id,reporter))
            self.db.execute('INSERT OR REPLACE INTO reporters VALUES (?,?,0)',(session_id,reporter))
            previous = self.live.get(session_id)
            if previous and previous['reporter']!=reporter and previous['reporter'] in previous['retired']:
                raise ValueError('Retired reporter')
            retired = set(previous['retired']) if previous else set()
            if previous and previous['reporter']!=reporter:
                if reporter in retired: raise ValueError('Retired reporter')
                retired.add(previous['reporter'])
            self.db.execute('INSERT OR REPLACE INTO sequences VALUES (?,?,?)',(session_id,reporter,sequence))
            exp = data.get('experience') or {}
            if not isinstance(exp,dict): raise ValueError('Experience must be an object')
            normal = self._counter(exp, ('normal_xp','lifetime_exp','experience','total_experience','experience_total'))
            asc = self._counter(exp, ('ascension_xp','ascension_exp','ascension_experience','asc_exp'))
            baseline = self.db.execute('SELECT * FROM baselines WHERE realm=? AND character=?',(realm,name)).fetchone()
            if baseline:
                gain = max(0,normal-baseline['normal']) if normal is not None and baseline['normal'] is not None else 0
                asc_gain = max(0,asc-baseline['asc']) if asc is not None and baseline['asc'] is not None else 0
                gap = now-baseline['received'] > self.settings()['stale_seconds'] or self._date(now)!=self._date(baseline['received'])
                if gain or asc_gain:
                    self.db.execute('INSERT INTO samples VALUES (?,?,?,?,?,?,?)',(realm,name,self._date(now),now,gain,asc_gain,'gap' if gap else 'observed'))
            self.db.execute('INSERT OR REPLACE INTO baselines VALUES (?,?,?,?,?)',(realm,name,normal if normal is not None else (baseline['normal'] if baseline else None),asc if asc is not None else (baseline['asc'] if baseline else None),now if normal is not None and asc is not None else (baseline['received'] if baseline else now)))
            self.live[session_id] = dict(snapshot=copy.deepcopy(data), monotonic=monotonic,received=now,reporter=reporter,retired=retired)
            active = {s['id'] for s in sessions}
            self.live = {k:v for k,v in self.live.items() if k in active and monotonic-v['monotonic']<=self.settings()['expiry_seconds']}
        return dict(accepted=True,session_id=session_id)

    def enrich(self,sessions):
        with self.lock:
            cfg, now = self.settings(),time.monotonic()
            result=[]
            today={(row['realm'],row['character'].casefold()):row for row in self.progress('today')['characters']}
            for session in sessions:
                entry=self.live.get(session['id'])
                age=now-entry['monotonic'] if entry else None
                available=entry is not None and age<=cfg['expiry_seconds']
                telemetry=dict(status=('fresh' if age<=cfg['stale_seconds'] else 'stale') if available else 'unavailable',age_seconds=round(age,1) if entry else None,snapshot=copy.deepcopy(entry['snapshot']) if available else None,received_at=datetime.fromtimestamp(entry['received'],timezone.utc).isoformat() if entry else None)
                totals=today.get((session['realm'],session['character'].casefold()),{})
                telemetry['today_xp']=totals.get('normal_xp')
                telemetry['today_ascension_xp']=totals.get('ascension_xp')
                telemetry['today_total_xp']=totals.get('total_xp')
                if telemetry['snapshot'] is not None:
                    tracking=telemetry['snapshot'].get('daily_tracking')
                    if not isinstance(tracking,dict): tracking={}
                    tracking.update(gempy_normal_xp_today=totals.get('normal_xp'),gempy_ascension_xp_today=totals.get('ascension_xp'),gempy_total_xp_today=totals.get('total_xp'))
                    telemetry['snapshot']['daily_tracking']=tracking
                result.append(dict(session,telemetry=telemetry))
            return result

    def import_saga(self,roots):
        if isinstance(roots,(str,Path)): roots=[roots]
        paths=set()
        for root in roots:
            root=Path(root)
            paths.update([root] if root.name=='exp_sagapanel_history.yaml' and root.is_file() else root.rglob('exp_sagapanel_history.yaml'))
        result=dict(files=len(paths),imported=0,skipped=0,errors=[])
        with self.lock,self.db:
            for path in sorted(paths):
                before_imported,before_skipped=result['imported'],result['skipped']
                self.db.execute('SAVEPOINT import_file')
                try:
                    if path.stat().st_size>5_000_000: raise ValueError('History file too large')
                    raw=path.read_bytes(); history=yaml.safe_load(raw)
                    if not isinstance(history,dict): raise ValueError('History must be a mapping')
                    name=path.parent.name; realm=REALMS.get(path.parent.parent.name)
                    if not realm: raise ValueError('Unrecognized game directory')
                    digest=hashlib.sha256(raw).hexdigest()
                    for bucket,period_type in [('daily','day'),('weekly','week'),('monthly','month'),('yearly','year')]:
                        values=history.get(bucket,{})
                        if not isinstance(values,dict): raise ValueError('Invalid history bucket')
                        for period,entry in values.items():
                            period=str(period)
                            pattern={'daily':r'\d{4}-\d{2}-\d{2}','weekly':r'\d{4}-W\d{2}','monthly':r'\d{4}-\d{2}','yearly':r'\d{4}'}[bucket]
                            if not re.fullmatch(pattern,period) or not isinstance(entry,dict): raise ValueError('Invalid history entry')
                            if bucket=='daily': datetime.strptime(period,'%Y-%m-%d')
                            elif bucket=='monthly': datetime.strptime(period,'%Y-%m')
                            elif bucket=='weekly':
                                y,w=period.split('-W'); datetime.fromisocalendar(int(y),int(w),1)
                            else: datetime.strptime(period,'%Y')
                            normal=self._counter(entry,('exp',)) or 0; asc=self._counter(entry,('asc',)) or 0
                            existing=self.db.execute('SELECT normal,asc FROM imports WHERE realm=? AND character=? AND bucket=? AND period=?',(realm,name,bucket,period)).fetchone()
                            if existing:
                                result['skipped']+=1; continue
                            # Imported files are cumulative snapshots, never additive imports.
                            self.db.execute('INSERT INTO imports VALUES (?,?,?,?,?,?,?,?,?)',(realm,name,bucket,period,normal,asc,str(path),digest,time.time()))
                            result['imported']+=1
                    self.db.execute('RELEASE import_file')
                except (OSError,ValueError,yaml.YAMLError) as exc:
                    self.db.execute('ROLLBACK TO import_file'); self.db.execute('RELEASE import_file')
                    result['imported'],result['skipped']=before_imported,before_skipped
                    result['errors'].append(dict(path=str(path),error=str(exc)))
        return result

    def progress(self,period='week',realm=None,character=None,start=None,end=None):
        if period=='custom':
            try:
                start_date=datetime.strptime(start,'%Y-%m-%d').date(); end_date=datetime.strptime(end,'%Y-%m-%d').date()
                if start_date>end_date or (end_date-start_date).days>3660: raise ValueError()
            except (TypeError,ValueError): raise ValueError('Custom range requires valid start/end dates, at most ten years') from None
            key=f'{start}..{end}'
        else:
            key=self._period(self._date(time.time()),period)
        def contains(date):
            return start<=date<=end if period=='custom' else (period=='all' or self._period(date,period)==key)
        with self.lock:
            # Live enrichment requests today's totals every polling cycle. Keep
            # that query bounded even after years of historical samples.
            if period == 'custom':
                first, last = start_date.isoformat(), end_date.isoformat()
                start, end = first, last
                key = f'{first}..{last}'
            elif period in ('day', 'today'):
                first = last = key
            elif period == 'week':
                year, week = key.split('-W')
                first_day = datetime.fromisocalendar(int(year), int(week), 1).date()
                first, last = first_day.isoformat(), (first_day + timedelta(days=6)).isoformat()
            elif period == 'month':
                first_day = datetime.strptime(key, '%Y-%m').date()
                next_month = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
                first, last = first_day.isoformat(), (next_month - timedelta(days=1)).isoformat()
            elif period == 'year':
                first, last = key + '-01-01', key + '-12-31'
            else:
                first = last = None
            if first is None:
                samples = list(self.db.execute('SELECT * FROM samples'))
            else:
                samples = list(self.db.execute('SELECT * FROM samples WHERE date BETWEEN ? AND ?', (first, last)))
            imports=list(self.db.execute('SELECT * FROM imports'))
            identities={(r['realm'],r['character']) for r in samples+imports}
            identities.update((r['realm'],r['character']) for r in self.db.execute('SELECT * FROM baselines'))
            characters=[]
            for r,c in sorted(identities):
                if realm and realm!=r or character and character.casefold()!=c.casefold(): continue
                relevant=[s for s in samples if s['realm']==r and s['character']==c and contains(s['date'])]
                imported=[s for s in imports if s['realm']==r and s['character']==c]
                days={}
                for s in imported:
                    if s['bucket']=='daily' and contains(s['period']):
                        days[s['period']]=dict(date=s['period'],normal_xp=s['normal'],ascension_xp=s['asc'],coverage='imported',imported_at=s['received'])
                live_days={}
                for s in relevant:
                    d=live_days.setdefault(s['date'],dict(date=s['date'],normal_xp=0,ascension_xp=0,coverage='observed'))
                    d['normal_xp']+=s['normal']; d['ascension_xp']+=s['asc']
                    if s['coverage']=='gap': d['coverage']='gap'
                # A history import may overlap live collection; use maxima rather than add.
                for date,d in live_days.items():
                    old=days.get(date)
                    if old:
                        pre=[s for s in relevant if s['date']==date and s['received']<=old['imported_at']]
                        post=[s for s in relevant if s['date']==date and s['received']>old['imported_at']]
                        d['normal_xp']=max(sum(s['normal'] for s in pre),old['normal_xp'])+sum(s['normal'] for s in post)
                        d['ascension_xp']=max(sum(s['asc'] for s in pre),old['ascension_xp'])+sum(s['asc'] for s in post)
                        if d['coverage']!='gap': d['coverage']='imported'
                    days[date]=d
                normal=sum(d['normal_xp'] for d in days.values()); asc=sum(d['ascension_xp'] for d in days.values())
                bucket={'day':'daily','today':'daily','week':'weekly','month':'monthly','year':'yearly'}.get(period)
                aggregate=[s for s in imported if s['bucket']==bucket and s['period']==key]
                if aggregate:
                    a=aggregate[0]
                    pre=[s for s in relevant if s['received']<=a['received']]
                    post=[s for s in relevant if s['received']>a['received']]
                    normal=max(normal,max(a['normal'],sum(s['normal'] for s in pre))+sum(s['normal'] for s in post))
                    asc=max(asc,max(a['asc'],sum(s['asc'] for s in pre))+sum(s['asc'] for s in post))
                if period=='all':
                    # Resolve overlap inside each calendar year, then sum disjoint years.
                    # Weekly aggregates can cross year boundaries, so they are excluded
                    # when calendar-month/year/daily evidence exists.
                    years={d[:4] for d in days} | {s['period'][:4] for s in imported if s['bucket'] in ('yearly','monthly','daily')}
                    normal=asc=0
                    if not years:
                        normal=sum(s['normal'] for s in imported if s['bucket']=='weekly')
                        asc=sum(s['asc'] for s in imported if s['bucket']=='weekly')
                    for year in years:
                        daily_normal=sum(d['normal_xp'] for date,d in days.items() if date[:4]==year)
                        daily_asc=sum(d['ascension_xp'] for date,d in days.items() if date[:4]==year)
                        monthly_normal=monthly_asc=0
                        for a in (s for s in imported if s['bucket']=='monthly' and s['period'][:4]==year):
                            month_samples=[s for s in relevant if s['date'][:7]==a['period']]
                            pre=[s for s in month_samples if s['received']<=a['received']]
                            post=[s for s in month_samples if s['received']>a['received']]
                            month_daily=[d for date,d in days.items() if date[:7]==a['period']]
                            monthly_normal+=max(sum(d['normal_xp'] for d in month_daily),max(a['normal'],sum(s['normal'] for s in pre))+sum(s['normal'] for s in post))
                            monthly_asc+=max(sum(d['ascension_xp'] for d in month_daily),max(a['asc'],sum(s['asc'] for s in pre))+sum(s['asc'] for s in post))
                        # Include daily-only months alongside imported month totals.
                        imported_months={s['period'] for s in imported if s['bucket']=='monthly' and s['period'][:4]==year}
                        monthly_normal+=sum(d['normal_xp'] for date,d in days.items() if date[:4]==year and date[:7] not in imported_months)
                        monthly_asc+=sum(d['ascension_xp'] for date,d in days.items() if date[:4]==year and date[:7] not in imported_months)
                        year_normal,year_asc=max(daily_normal,monthly_normal),max(daily_asc,monthly_asc)
                        for a in (s for s in imported if s['bucket']=='yearly' and s['period']==year):
                            year_samples=[s for s in relevant if s['date'][:4]==year]
                            pre=[s for s in year_samples if s['received']<=a['received']]
                            post=[s for s in year_samples if s['received']>a['received']]
                            year_normal=max(year_normal,max(a['normal'],sum(s['normal'] for s in pre))+sum(s['normal'] for s in post))
                            year_asc=max(year_asc,max(a['asc'],sum(s['asc'] for s in pre))+sum(s['asc'] for s in post))
                        normal+=year_normal; asc+=year_asc
                daily=[]
                for d in sorted(days.values(),key=lambda d:d['date']):
                    d.pop('imported_at',None)
                    d['total_xp']=d['normal_xp']+d['ascension_xp']; daily.append(d)
                coverage='gap' if any(d['coverage']=='gap' for d in daily) else ('imported' if aggregate or (period=='all' and imported) or any(d['coverage']=='imported' for d in daily) else 'observed')
                characters.append(dict(character=c,realm=r,normal_xp=normal,ascension_xp=asc,total_xp=normal+asc,atp_equivalent=asc/50000,coverage=coverage,daily=daily))
            totals={}
            for c in characters:
                for d in c['daily']:
                    row=totals.setdefault(d['date'],dict(date=d['date'],normal_xp=0,ascension_xp=0,total_xp=0,coverage='observed'))
                    for metric in ('normal_xp','ascension_xp','total_xp'): row[metric]+=d[metric]
                    if d['coverage']!='observed': row['coverage']=d['coverage']
            return dict(period=period,period_key=key,characters=characters,daily=sorted(totals.values(),key=lambda d:d['date']),timezone=self.settings()['timezone'],day_boundary=self.settings()['day_boundary'],start=start if period=='custom' else None,end=end if period=='custom' else None,history_note='Custom ranges include daily detail only; aggregate-only imports are unavailable.' if period=='custom' else 'Gaps are assigned to receipt day; imported periods are frozen at first import.')

    def close(self):
        with self.lock: self.db.close()

    def backup(self,destination=None):
        destination=Path(destination) if destination else self.directory / ('telemetry-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
        with self.lock, sqlite3.connect(destination) as target: self.db.backup(target)
        return str(destination)
