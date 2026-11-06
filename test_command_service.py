import copy
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from command_service import CommandService, CommandError


class Sessions:
    def __init__(self, directory):
        self.state = Path(directory)
        self.config = {'accounts': {'a': ['Hero'], 'b': ['Mage']}}
        self.rows = [dict(id='11:22', pid=11, character='Hero', realm='prime'),
                     dict(id='33:44', pid=33, character='Mage', realm='test')]
        self.locks = {}
    def sessions(self): return copy.deepcopy(self.rows)
    def _lock(self, key): return self.locks.setdefault(key, threading.RLock())


class Bridge:
    def __init__(self):
        self.calls = []
        self.generation = 'generation-1'
        self.results = {}
        self.receipts = {}
    def target(self, session):
        return dict(session_id=session['id'], bridge_generation=self.generation,
                    character=session['character'], realm=session['realm'], ready=True, reason='')
    def exchange(self, target, request):
        self.calls.append((copy.deepcopy(target), copy.deepcopy(request)))
        if request['action'] == 'receipt':
            return self.receipts.get(request['request_id'], {'state': 'unconfirmed', 'reason': 'Receipt unavailable.'})
        result = self.results.get(target['character'], {'state': 'sent', 'reason': ''})
        if isinstance(result, Exception): raise result
        return result


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = Sessions(self.tmp.name)
        self.bridge = Bridge()
        self.commands = CommandService(self.service, self.tmp.name, transport=self.bridge)
    def tearDown(self):
        self.commands.close()
        self.tmp.cleanup()
    def body(self, command=';pause all', targets=None):
        prepared = self.commands.prepare('administrator-session')
        return dict(prepared, command=command, targets=targets or [
            {k:v for k,v in t.items() if k in ('session_id','bridge_generation','character','realm')}
            for t in self.commands.targets()])
    def submit(self, body): return self.commands.submit(body, 'administrator-session')
    def settled(self, request_id):
        for _ in range(100):
            result = self.commands.get(request_id)
            if all(t['state'] != 'sending' for t in result['targets']): return result
            time.sleep(.01)
        self.fail('workers did not settle')

    def test_literal_command_and_independent_mixed_results(self):
        self.bridge.results['Mage'] = {'state':'not_sent', 'reason':'Connection changed.'}
        body = self.body('  ;pause  all;look  ')
        self.submit(body)
        result = self.settled(body['request_id'])
        self.assertEqual(result['command'], '  ;pause  all;look  ')
        self.assertEqual([t['state'] for t in result['targets']], ['sent','not_sent'])
        self.assertEqual([r['command'] for _,r in self.bridge.calls], [body['command']]*2)
        self.assertTrue(all(r['deadline']==result['accepted_at']+5 for _,r in self.bridge.calls))
        self.assertNotIn('admission_token', json.dumps(result))

    def test_validation_rejects_whole_batch_before_dispatch(self):
        invalid = ['', '   ', 'look\n', 'look\r', '\x00look', 'look\t', '\x7f', '\x85', 'é'*513]
        for command in invalid:
            with self.assertRaises(CommandError): self.submit(self.body(command))
        body = self.body(); body['targets'].append(body['targets'][0])
        with self.assertRaises(CommandError): self.submit(body)
        body = self.body(); body['targets'][1]['realm'] = 'bogus'
        with self.assertRaises(CommandError): self.submit(body)
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.commands.recent(), [])

    def test_duplicate_returns_original_without_replay_and_conflict(self):
        body=self.body(); first=self.submit(body); self.settled(first['request_id'])
        self.submit(body)
        self.assertEqual(len(self.bridge.calls),2)
        body['command']='look'
        with self.assertRaises(CommandError) as raised: self.submit(body)
        self.assertEqual(raised.exception.status,409)

    def test_token_binds_admin_expiry_and_server_epoch(self):
        body=self.body()
        with self.assertRaises(CommandError): self.commands.submit(body, 'different-session')
        with patch('command_service.time.time', return_value=time.time()+61):
            with self.assertRaises(CommandError): self.submit(body)
        self.commands.close(); self.commands=CommandService(self.service,self.tmp.name,transport=self.bridge)
        with self.assertRaises(CommandError): self.submit(body)
        self.assertEqual(self.bridge.calls,[])

    def test_generation_change_and_checkin_ownership_are_not_sent(self):
        body=self.body(); self.bridge.generation='replacement'
        self.submit(body)
        self.assertEqual({t['state'] for t in self.settled(body['request_id'])['targets']},{'not_sent'})
        self.assertEqual(self.bridge.calls,[])
        db=sqlite3.connect(Path(self.tmp.name)/'telemetry.sqlite3')
        db.execute('CREATE TABLE checkin_reservations(account TEXT PRIMARY KEY, job_id TEXT)')
        db.execute("INSERT INTO checkin_reservations VALUES('a','job')");db.commit();db.close()
        self.assertFalse(self.commands.targets()[0]['ready'])
        body=self.body(); self.submit(body)
        result=self.settled(body['request_id'])
        self.assertEqual(result['targets'][0]['state'],'not_sent')
        self.assertEqual(result['targets'][1]['state'],'sent')

    def test_lost_ack_is_never_replayed_but_receipt_can_resolve(self):
        self.bridge.results['Hero']=TimeoutError()
        body=self.body(); self.submit(body); result=self.settled(body['request_id'])
        self.assertEqual(result['targets'][0]['state'],'unconfirmed')
        dispatches=[r for _,r in self.bridge.calls if r['action']=='dispatch']
        self.bridge.receipts[dispatches[0]['request_id']]={'state':'sent','reason':''}
        result=self.commands.get(body['request_id'])
        self.assertEqual(result['targets'][0]['state'],'sent')
        self.assertEqual(len([r for _,r in self.bridge.calls if r['action']=='dispatch']),2)

    def test_expired_queued_work_does_not_contact_bridge(self):
        body=self.body(); lock=self.service._lock('11:22'); lock.acquire()
        try:
            self.submit(body)
            with patch('command_service.time.time',return_value=time.time()+10):
                lock.release()
                result=self.settled(body['request_id'])
            self.assertEqual(result['targets'][0]['state'],'not_sent')
            self.assertFalse(any(t['character']=='Hero' and r['action']=='dispatch' for t,r in self.bridge.calls))
        finally:
            if getattr(lock,'_is_owned')(): lock.release()

    def test_journal_private_and_restart_recovers_without_dispatch(self):
        body=self.body(); self.submit(body); self.settled(body['request_id']); self.commands.close()
        path=Path(self.tmp.name)/'commands.sqlite3'
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        db=sqlite3.connect(path)
        data=json.loads(db.execute('SELECT data FROM command_batches').fetchone()[0])
        data['targets'][0].update(state='sending',phase='queued')
        data['targets'][1].update(state='sending',phase='contact')
        db.execute('UPDATE command_batches SET data=?',(json.dumps(data),));db.commit();db.close()
        self.bridge.calls.clear()
        self.commands=CommandService(self.service,self.tmp.name,transport=self.bridge)
        result=self.commands.get(body['request_id'])
        self.assertEqual([t['state'] for t in result['targets']],['not_sent','unconfirmed'])
        self.assertFalse(any(r['action']=='dispatch' for _,r in self.bridge.calls))

    def test_more_than_100_targets_is_rejected_without_a_partial_send(self):
        body=self.body()
        body['targets']=[dict(body['targets'][0],session_id=f'{i+1}:100') for i in range(101)]
        with self.assertRaises(CommandError): self.submit(body)
        self.assertEqual(self.commands.recent(),[])
        self.assertEqual(self.bridge.calls,[])

    def test_parallel_dispatch_has_four_workers(self):
        names=['Alpha','Beta','Gamma','Delta','Epsilon','Zeta','Eta','Theta']
        self.service.config={'accounts':{name:[name] for name in names}}
        self.service.rows=[dict(id=f'{i+1}:100',pid=i+1,character=name,realm='prime') for i,name in enumerate(names)]
        gate=threading.Event();entered=threading.Event();guard=threading.Lock();inflight=0;peak=0
        original=self.bridge.exchange
        def exchange(target,request):
            nonlocal inflight,peak
            with guard:
                inflight+=1;peak=max(peak,inflight)
                if inflight==4:entered.set()
            gate.wait(2)
            try:return original(target,request)
            finally:
                with guard:inflight-=1
        self.bridge.exchange=exchange
        body=self.body();self.submit(body)
        try:self.assertTrue(entered.wait(1))
        finally:gate.set()
        self.assertEqual({t['state'] for t in self.settled(body['request_id'])['targets']},{'sent'})
        self.assertEqual(peak,4)

    def test_history_count_retains_newest_1000_and_keeps_unexpired_tombstones(self):
        now=time.time()
        with self.commands.lock,self.commands.db:
            for index in range(1001):
                batch=dict(request_id=str(index),accepted_at=now,command='look',targets=[])
                self.commands.db.execute('INSERT INTO command_batches VALUES(?,?,?,?)',(str(index),now,'fingerprint',json.dumps(batch)))
                self.commands.db.execute('INSERT INTO command_ids VALUES(?,?,?)',(str(index),'fingerprint',now+60))
        recent=self.commands.recent(1000)
        self.assertEqual(len(recent),1000)
        self.assertEqual(recent[0]['request_id'],'1000')
        self.assertEqual(recent[-1]['request_id'],'1')
        with self.assertRaises(CommandError):self.commands.get('0')
        with self.commands.lock:
            self.assertIsNotNone(self.commands.db.execute("SELECT id FROM command_ids WHERE id='0'").fetchone())

    def test_expired_history_is_not_readable_by_id_or_list(self):
        body=self.body();self.submit(body);self.settled(body['request_id'])
        with patch('command_service.time.time', return_value=time.time()+7*86400+1):
            with self.assertRaises(CommandError) as raised: self.commands.get(body['request_id'])
            self.assertEqual(raised.exception.status,404)
            self.assertEqual(self.commands.recent(),[])
            with self.assertRaises(CommandError):self.submit(body)
        self.assertEqual(len([r for _,r in self.bridge.calls if r['action']=='dispatch']),2)

    def test_pruned_id_cannot_be_readmitted_with_valid_token(self):
        body=self.body();self.submit(body);self.settled(body['request_id'])
        with self.commands.lock, self.commands.db:
            self.commands.db.execute('DELETE FROM command_batches')
        with self.assertRaises(CommandError) as raised: self.submit(body)
        self.assertEqual(raised.exception.status,410)
        self.assertEqual(len([r for _,r in self.bridge.calls if r['action']=='dispatch']),2)

if __name__=='__main__': unittest.main()
