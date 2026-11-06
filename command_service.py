"""Durable command admission and receipts. Never replay a possible dispatch."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid

from account_guard import account_for, host_lock, reservation

TARGET_KEYS = ('session_id', 'bridge_generation', 'character', 'realm')


class CommandError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate(body):
    if not isinstance(body, dict):
        raise CommandError('Expected a command batch.')
    command = body.get('command')
    try:
        valid = (isinstance(command, str) and bool(command.strip()) and
                 len(command.encode('utf-8')) <= 1024 and
                 not any(ord(c) < 32 or 127 <= ord(c) <= 159 or c in '\u2028\u2029' for c in command))
    except UnicodeEncodeError:
        valid = False
    if not valid:
        raise CommandError('Use one line without control characters, up to 1,024 UTF-8 bytes.')
    targets = body.get('targets')
    if not isinstance(targets, list) or not 1 <= len(targets) <= 100:
        raise CommandError('Choose between 1 and 100 explicit recipients.')
    seen, normalized = set(), []
    for target in targets:
        if (not isinstance(target, dict) or set(target) != set(TARGET_KEYS) or
                any(not isinstance(target[k], str) for k in TARGET_KEYS) or
                not re.fullmatch(r'[1-9][0-9]{0,19}:[0-9]{1,20}', target['session_id']) or
                not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', target['bridge_generation']) or
                not re.fullmatch(r'[A-Za-z]{1,50}', target['character']) or
                target['realm'] not in ('prime', 'test')):
            raise CommandError('Invalid recipient identity.')
        if target['session_id'] in seen:
            raise CommandError('Duplicate recipient.')
        seen.add(target['session_id'])
        normalized.append({k: target[k] for k in TARGET_KEYS})
    request_id = body.get('request_id')
    try:
        if str(uuid.UUID(request_id)) != request_id: raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise CommandError('Invalid request ID.') from None
    normalized.sort(key=lambda t: tuple(t[k] for k in TARGET_KEYS))
    fingerprint = hashlib.sha256(json.dumps([command, normalized], ensure_ascii=True,
                                           separators=(',', ':')).encode()).hexdigest()
    return command, normalized, fingerprint


class CommandService:
    def __init__(self, service, directory, transport=None):
        self.service = service
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        if transport is None:
            from command_transport import CommandTransport
            transport = CommandTransport(service)
        self.transport = transport
        self.lock = threading.RLock()
        self.secret = secrets.token_bytes(32)
        self.closed = False
        path = self.directory / 'commands.sqlite3'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS command_batches (id TEXT PRIMARY KEY, accepted REAL, fingerprint TEXT, data TEXT)')
            self.db.execute('CREATE TABLE IF NOT EXISTS command_ids (id TEXT PRIMARY KEY, fingerprint TEXT, expires REAL)')
            for (raw,) in self.db.execute('SELECT data FROM command_batches').fetchall():
                batch = json.loads(raw)
                for target in batch['targets']:
                    if target['state'] == 'sending':
                        target.update(state='not_sent' if target['phase'] == 'queued' else 'unconfirmed',
                                      reason='Server restarted before delivery was confirmed.')
                self._save(batch)
            self._prune()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='gempy-command')

    def prepare(self, admin):
        request_id, expires = str(uuid.uuid4()), time.time() + 60
        expiry = str(expires)
        signature = hmac.new(self.secret, f'{request_id}\n{expiry}\n{admin}'.encode(), hashlib.sha256).hexdigest()
        return {'request_id': request_id, 'admission_token': expiry + '.' + signature}

    def _admission(self, body, admin):
        try:
            expiry, signature = body['admission_token'].rsplit('.', 1)
            expected = hmac.new(self.secret, f"{body['request_id']}\n{expiry}\n{admin}".encode(), hashlib.sha256).hexdigest()
            expires = float(expiry)
            if not hmac.compare_digest(signature, expected) or not time.time() < expires <= time.time()+61:
                raise ValueError()
            return expires
        except (ValueError, KeyError, TypeError, AttributeError):
            raise CommandError('Admission expired or invalid. Start a new explicit send.', 403) from None

    def targets(self):
        result = []
        for session in self.service.sessions():
            target = dict(session_id=session['id'], character=session['character'], realm=session['realm'],
                          bridge_generation=None, ready=False, reason='Control unavailable.')
            try:
                account = account_for(self.service.config, session['character'])
                target.update(self.transport.target(session))
                if reservation(self.service.state, account):
                    target.update(ready=False, reason='Check-in controlled. Take over in Daily Check-in.', checkin_controlled=True)
            except Exception:
                target.update(ready=False, reason='Control unavailable. Verify the local bridge and account mapping.')
            result.append(target)
        return result

    def submit(self, body, admin):
        command, targets, fingerprint = validate(body)
        request_id = body['request_id']
        with self.lock:
            if self.closed: raise CommandError('Command service is stopping.', 503)
            with self.db:
                self._prune()
            row = self.db.execute('SELECT fingerprint,data FROM command_batches WHERE id=?', (request_id,)).fetchone()
            if row:
                if row[0] != fingerprint: raise CommandError('Request ID already used with different input.', 409)
                return self._public(json.loads(row[1]))
            tombstone = self.db.execute('SELECT fingerprint FROM command_ids WHERE id=?', (request_id,)).fetchone()
            if tombstone:
                if tombstone[0] != fingerprint: raise CommandError('Request ID already used with different input.', 409)
                raise CommandError('This accepted receipt has expired; it cannot be submitted again.', 410)
            expires = self._admission(body, admin)
            accepted = time.time()
            batch = dict(request_id=request_id, command=command, accepted_at=accepted, targets=[
                dict(t, state='sending', reason='', phase='queued', delivery_id=f'{request_id}:{index}')
                for index, t in enumerate(targets)])
            with self.db:
                self.db.execute('INSERT INTO command_ids VALUES(?,?,?)', (request_id, fingerprint, expires))
                self.db.execute('INSERT INTO command_batches VALUES(?,?,?,?)',
                                (request_id, accepted, fingerprint, json.dumps(batch)))
                self._prune()
            # The acceptance record is durable before any worker can contact Lich.
            for index in range(len(targets)):
                self.executor.submit(self._deliver, request_id, index)
            return self._public(batch)

    def _save(self, batch):
        self.db.execute('UPDATE command_batches SET data=? WHERE id=?', (json.dumps(batch), batch['request_id']))

    def _load(self, request_id):
        row = self.db.execute('SELECT data FROM command_batches WHERE id=?', (request_id,)).fetchone()
        if not row: raise CommandError('Command receipt not found.', 404)
        return json.loads(row[0])

    @staticmethod
    def _public(batch):
        return {**batch, 'targets': [{k:v for k,v in target.items() if k not in ('phase','delivery_id')}
                                     for target in batch['targets']]}

    def _update(self, request_id, index, **values):
        with self.lock, self.db:
            try: batch = self._load(request_id)
            except CommandError: return False
            batch['targets'][index].update(values)
            self._save(batch)
        return True

    @contextmanager
    def _account_lock(self, account, deadline):
        while time.time() < deadline:
            manager = host_lock(self.service.state, 'account:' + account, blocking=False)
            try:
                manager.__enter__()
                break
            except BlockingIOError:
                time.sleep(.02)
        else:
            raise CommandError('Expired while waiting for the account.')
        try: yield
        finally: manager.__exit__(None, None, None)

    def _deliver(self, request_id, index):
        contact = False
        session_lock = None
        acquired = False
        try:
            with self.lock:
                batch = self._load(request_id)
            target = batch['targets'][index]
            deadline = batch['accepted_at'] + 5
            account = account_for(self.service.config, target['character'])
            # Account-before-session matches account backend launch, which can take a session lock.
            with self._account_lock(account, deadline):
                session_lock = self.service._lock(target['session_id'])
                acquired = session_lock.acquire(timeout=max(0, deadline-time.time()))
                if not acquired or time.time() >= deadline:
                    raise CommandError('Expired before dispatch.')
                session = next((s for s in self.service.sessions() if s['id'] == target['session_id']), None)
                if not session or session['character'] != target['character'] or session['realm'] != target['realm']:
                    raise CommandError('Session identity changed.')
                if reservation(self.service.state, account):
                    raise CommandError('Check-in controlled. Take over in Daily Check-in.')
                fresh = self.transport.target(session)
                if not fresh.get('ready') or any(fresh.get(k) != target[k] for k in TARGET_KEYS):
                    raise CommandError('Control unavailable or connection generation changed.')
                if time.time() >= deadline:
                    raise CommandError('Expired before dispatch.')
                if not self._update(request_id, index, phase='contact'): return
                contact = True
                reply = self.transport.exchange(target, dict(action='dispatch', request_id=target['delivery_id'],
                                                            command=batch['command'], deadline=deadline))
                state = reply.get('state')
                if state not in ('sent', 'not_sent'): state = 'unconfirmed'
                # Reasons are controlled by this service, never arbitrary command-bearing runtime errors.
                reason = '' if state == 'sent' else ('Bridge rejected before dispatch.' if state == 'not_sent' else 'Delivery not confirmed. Inspect the client before resending.')
                self._update(request_id, index, state=state, reason=reason, phase='terminal')
        except Exception as error:
            ambiguous = contact and getattr(error, 'may_have_sent', True)
            reason = 'Delivery not confirmed. Inspect the client before resending.' if ambiguous else (
                str(error) if isinstance(error, CommandError) else 'Control unavailable before dispatch.')
            self._update(request_id, index, state='unconfirmed' if ambiguous else 'not_sent', reason=reason,
                         phase='contact' if ambiguous else 'terminal')
        finally:
            if acquired: session_lock.release()

    def _reconcile(self, batch):
        for index, target in enumerate(batch['targets']):
            if target['state'] != 'unconfirmed': continue
            try:
                reply = self.transport.exchange(target, dict(action='receipt', request_id=target['delivery_id']))
                if reply.get('state') == 'sent':
                    self._update(batch['request_id'], index, state='sent', reason='', phase='terminal')
                elif reply.get('state') == 'not_sent' and reply.get('reason') not in ('unknown_request', 'request_conflict'):
                    # Only a cached pre-admission rejection is conclusive.
                    if reply.get('reason') in ('expired', 'not_ready', 'busy', 'checkin_controlled'):
                        self._update(batch['request_id'], index, state='not_sent', reason='Bridge rejected before dispatch.', phase='terminal')
            except Exception:
                pass

    def get(self, request_id):
        with self.lock, self.db:
            self._prune()
            batch = self._load(request_id)
        self._reconcile(batch)
        with self.lock:
            return self._public(self._load(request_id))

    def recent(self, limit=20):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise CommandError('History limit must be between 1 and 1,000.')
        with self.lock, self.db:
            self._prune()
            return [self._public(json.loads(row[0])) for row in self.db.execute(
                'SELECT data FROM command_batches ORDER BY accepted DESC,rowid DESC LIMIT ?', (limit,))]

    def _prune(self):
        self.db.execute('DELETE FROM command_batches WHERE accepted<? OR id NOT IN (SELECT id FROM command_batches ORDER BY accepted DESC,rowid DESC LIMIT 1000)', (time.time()-7*86400,))
        self.db.execute('DELETE FROM command_ids WHERE expires<=?', (time.time(),))

    def close(self):
        with self.lock:
            if self.closed: return
            self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            self.db.close()
