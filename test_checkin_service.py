import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from gempy_service import Service, ServiceError


class CheckinServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        # Avoid any constructor discovery; every process operation is stubbed.
        self.service=object.__new__(Service)
        self.service.config={'accounts':{'A':['Alpha','Beta'],'B':['Gamma']}}
        self.service.state=Path(self.tmp.name)
        self.service.guard=threading.RLock(); self.service.locks={}

    def tearDown(self): self.tmp.cleanup()

    def test_busy_account_never_spawns(self):
        with patch.object(self.service,'_discover',return_value=[dict(character='Alpha',realm='prime',id='1:2')]), patch.object(self.service,'_ensure_backend') as spawn:
            with self.assertRaises(ServiceError): self.service.ensure_backend('Beta','prime')
            spawn.assert_not_called()

    def test_manual_launch_cannot_bypass_reserved_account(self):
        db=sqlite3.connect(self.service.state/'telemetry.sqlite3')
        db.execute('CREATE TABLE checkin_reservations(account TEXT PRIMARY KEY,job_id TEXT)')
        db.execute('INSERT INTO checkin_reservations VALUES(?,?)',('a','job'))
        db.commit();db.close()
        with patch.object(self.service,'_discover',return_value=[]),patch.object(self.service,'_ensure_backend') as spawn:
            with self.assertRaises(ServiceError): self.service.ensure_backend('Beta','prime')
            spawn.assert_not_called()

    def test_live_disabled_at_adapter_too(self):
        with patch.object(self.service,'ensure_backend') as spawn:
            with self.assertRaises(ServiceError):self.service.start_checkin('Alpha','prime','job',{})
            spawn.assert_not_called()

    def test_attach_requires_explicit_takeover_of_reserved_session(self):
        session=dict(character='Alpha',realm='prime',id='1:2')
        with patch.object(self.service,'_check_client'),patch.object(self.service,'_validated',return_value=session),patch('account_guard.reservation',return_value='job'):
            with self.assertRaisesRegex(ServiceError,'take over'):
                self.service.attach('1:2','connection')

    def test_same_session_reused_for_normal_launch(self):
        session=dict(character='Alpha',realm='prime',id='1:2')
        with patch.object(self.service,'_discover',return_value=[session]),patch.object(self.service,'_ensure_backend') as spawn:
            self.assertEqual(self.service.ensure_backend('Alpha','prime'),session)
            spawn.assert_not_called()

    def test_checkin_refuses_reuse_and_attachment_cleanup(self):
        self.service.config['daily_checkin']={'allow_live_operations':True}
        session=dict(character='Alpha',realm='prime',id='1:2',attachment='Attached')
        with patch.object(self.service,'_discover',return_value=[session]):
            with self.assertRaises(ServiceError):self.service.start_checkin('Alpha','prime','job',{})
        with patch.object(self.service,'_validated',return_value=session),patch.object(self.service,'disconnect') as close:
            with self.assertRaises(ServiceError):self.service.disconnect_checkin('1:2')
            close.assert_not_called()

    def test_cleanup_never_falls_through_to_attached_client_exit(self):
        session=dict(character='Alpha',realm='prime',id='1:2',attachment='Headless')
        with patch.object(self.service,'_validated',side_effect=[session,dict(session,attachment='Attached')]),patch.object(self.service,'_client_for',return_value={'id':'client'}),patch.object(self.service,'_websocket') as send:
            with self.assertRaises(ServiceError):self.service.disconnect_checkin('1:2')
            send.assert_not_called()


if __name__=='__main__':unittest.main()
