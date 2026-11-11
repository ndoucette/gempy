"""Browser frontend lifetime tests; never connect to a real game session."""
import tempfile
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from gempy_service import Service, ServiceError, tcp_rows


class FrontendCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Service({'accounts': {'A': ['Hero']}}, self.temp.name)
        self.entry = {'pid': 13, '_start': 100, 'port': 18080}
        self.process = {'pid': 13, 'start': 100, 'args': [
            '/tmp/vellum-fe', '--frontend', 'headless', '--profile',
            'gempy-Hero-prime', '--host', '127.0.0.1', '--port', '8000']}
        self.rows = [dict(local=18080, remote=0, state='0A', inode='listen',
                          address='00000000', remote_address='00000000')]
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(self.service, '_vellum_entries',
                                             side_effect=lambda: iter([self.entry])))
        self.stack.enter_context(patch('gempy_service.process_info',
                                      side_effect=lambda pid: self.process))
        self.stack.enter_context(patch('gempy_service.tcp_rows', side_effect=lambda **kwargs: self.rows))
        self.inodes = self.stack.enter_context(patch('gempy_service.socket_inodes',
            return_value={'listen', 'browser', 'browser2', 'backend'}))
        self.clock = self.stack.enter_context(patch('gempy_service.time.monotonic', return_value=0))
        self.stack.enter_context(patch('gempy_service.os.pidfd_open', return_value=77, create=True))
        self.signal = self.stack.enter_context(patch('gempy_service.signal.pidfd_send_signal', create=True))
        self.stack.enter_context(patch('gempy_service.os.close'))

    def sweep(self, now):
        self.clock.return_value = now
        self.service.cleanup_frontends()

    def browser(self, inode='browser', state='01'):
        return dict(local=18080, remote=50000, state=state, inode=inode,
                    address='0100007F', remote_address='0100007F')

    def test_last_browser_close_stops_only_frontend_after_grace(self):
        # The outgoing Lich connection must not keep a browserless engine alive.
        self.rows.append(dict(local=50001, remote=8000, state='01', inode='backend',
                              address='0100007F', remote_address='0100007F'))
        self.sweep(0)
        self.sweep(59)
        self.signal.assert_not_called()
        self.sweep(61)
        self.signal.assert_called_once()
        self.assertEqual(self.signal.call_args.args[0], 77)

    def test_another_tab_keeps_engine_alive(self):
        self.rows.extend([self.browser(), self.browser('browser2')])
        self.sweep(0)
        self.rows.pop()
        self.sweep(100)
        self.signal.assert_not_called()

    def test_browser_reconnect_restarts_grace(self):
        self.sweep(0)
        self.rows.append(self.browser())
        self.sweep(59)
        self.rows.pop()
        self.sweep(61)
        self.sweep(100)
        self.signal.assert_not_called()
        self.sweep(122)
        self.signal.assert_called_once()

    def test_closed_browser_socket_does_not_keep_engine_alive(self):
        self.rows.append(self.browser(state='08'))  # CLOSE_WAIT, not a live browser
        self.sweep(0)
        self.sweep(61)
        self.signal.assert_called_once()

    def test_unknown_socket_state_restarts_grace(self):
        self.sweep(0)
        self.inodes.return_value = None
        self.sweep(59)
        self.inodes.return_value = {'listen'}
        self.sweep(61)
        self.signal.assert_not_called()
        self.sweep(122)
        self.signal.assert_called_once()

    def test_unreadable_tcp_tables_never_authorize_cleanup(self):
        self.sweep(0)
        self.rows = None
        self.sweep(100)
        self.signal.assert_not_called()

    def test_external_or_gui_frontend_never_stopped(self):
        for args in (['vellum-fe', '--frontend', 'gui', '--profile', 'gempy-Hero-prime'],
                     ['vellum-fe', '--frontend', 'headless', '--profile', 'personal']):
            self.process['args'] = args
            self.sweep(0)
            self.sweep(100)
        self.signal.assert_not_called()

    def test_process_identity_change_never_stopped(self):
        self.sweep(0)
        self.process['start'] = 101
        self.sweep(100)
        self.signal.assert_not_called()

    def test_new_attach_gets_full_browser_open_grace(self):
        p = dict(id='12:100', pid=12, start=100, character='Hero', realm='prime',
                 port=8000, attachment='Attached', args=[])
        self.sweep(0)
        self.clock.return_value = 59
        with patch.object(self.service, '_validated', return_value=p), \
             patch.object(self.service, '_client_for', return_value=self.entry), \
             patch.object(self.service, '_token', return_value='secret'):
            self.service.attach(p['id'])
        self.sweep(61)
        self.signal.assert_not_called()
        self.sweep(120)
        self.signal.assert_called_once()

    def test_startup_failure_reaps_new_frontend(self):
        p = dict(id='12:100', pid=12, start=100, character='Hero', realm='prime',
                 port=8000, attachment='Headless', args=[])
        child = Mock(pid=13)
        child.poll.return_value = None
        with patch.object(self.service, '_validated', return_value=p), \
             patch.object(self.service, '_client_for', return_value=None), \
             patch.object(self.service, '_allocate', return_value=18080), \
             patch.object(self.service, '_track'), \
             patch('gempy_service.subprocess.Popen', return_value=child), \
             patch.object(self.service, '_websocket', side_effect=ServiceError('pairing failed')):
            with self.assertRaises(ServiceError):
                self.service.attach(p['id'])
        child.terminate.assert_called_once()
        child.wait.assert_called_once()

    def test_reuses_disconnected_engine_without_registry_launch_metadata(self):
        # Gempy uses --profile, so Vellum's registry has launch=null.
        self.entry['_args'] = self.process['args']
        p = dict(pid=12, port=8000, character='Hero', realm='prime', attachment='Headless')
        self.assertEqual(self.service._client_for(p), self.entry)

    def test_reused_engine_reconnects_even_if_another_client_is_attached(self):
        self.entry['_args'] = self.process['args']
        p = dict(id='12:100', pid=12, start=100, character='Hero', realm='prime',
                 port=8000, attachment='Attached', args=[])
        self.assertEqual(self.service._client_for(p), self.entry)
        def connect(entry, message):
            self.rows.extend([
                dict(local=50001, remote=8000, state='01', inode='client',
                     address='0100007F', remote_address='0100007F'),
                dict(local=8000, remote=50001, state='01', inode='server',
                     address='0100007F', remote_address='0100007F')])
        self.inodes.side_effect = lambda pid: {'listen', 'client'} if pid == 13 else {'server'}
        with patch.object(self.service, '_validated', return_value=p), \
             patch.object(self.service, '_multi_client', return_value=True), \
             patch.object(self.service, '_token', return_value='secret'), \
             patch.object(self.service, '_websocket', side_effect=connect) as send, \
             patch('gempy_service.subprocess.Popen') as spawn:
            result = self.service.attach(p['id'])
        self.assertEqual(result['web_port'], 18080)
        send.assert_called_once()
        spawn.assert_not_called()

    def test_never_reuses_engine_connected_to_another_backend(self):
        self.entry['_args'] = self.process['args']
        self.rows.append(dict(local=50001, remote=8001, state='01', inode='backend',
                              address='0100007F', remote_address='0100007F'))
        p = dict(pid=12, port=8000, character='Hero', realm='prime', attachment='Headless')
        self.assertIsNone(self.service._client_for(p))

    def test_reconnect_during_final_idle_check_cancels_cleanup(self):
        self.sweep(0)
        with patch('gempy_service.tcp_rows', side_effect=[self.rows, self.rows + [self.browser()]]):
            self.sweep(61)
        self.signal.assert_not_called()

    def test_partial_tcp_visibility_cannot_authorize_cleanup(self):
        with patch('gempy_service.Path.read_text', side_effect=['header\n', PermissionError()]):
            self.assertIsNone(tcp_rows(require_complete=True))

    def test_pid_reuse_after_opening_handle_never_signaled(self):
        with patch('gempy_service.process_info', side_effect=[
                self.process, dict(self.process, start=101)]):
            self.service._stop_frontend(self.entry)
        self.signal.assert_not_called()

    def test_other_service_attach_resets_shared_grace(self):
        self.sweep(0)
        other = Service(self.service.config, self.temp.name)
        p = dict(id='12:100', pid=12, start=100, character='Hero', realm='prime',
                 port=8000, attachment='Attached', args=[])
        self.clock.return_value = 59
        with patch.object(other, '_validated', return_value=p), \
             patch.object(other, '_client_for', return_value=self.entry), \
             patch.object(other, '_token', return_value='secret'):
            other.attach(p['id'])
        self.sweep(61)
        self.signal.assert_not_called()
        self.sweep(120)
        self.signal.assert_called_once()

    def test_reuse_does_not_displace_legacy_lich_frontend(self):
        self.entry['_args'] = self.process['args']
        p = dict(id='12:100', pid=12, start=100, character='Hero', realm='prime',
                 port=8000, attachment='Attached', args=[])
        with patch.object(self.service, '_validated', return_value=p), \
             patch.object(self.service, '_multi_client', return_value=False), \
             patch.object(self.service, '_websocket') as send, \
             patch.object(self.service, '_token', return_value='secret'), \
             patch('gempy_service.time.monotonic', side_effect=range(100)):
            with self.assertRaises(ServiceError):
                self.service.attach(p['id'])
        send.assert_not_called()

    def test_cleanup_worker_scans_once_started_and_stops_cleanly(self):
        scanned = threading.Event()
        sweep = self.service.cleanup_frontends
        def scan():
            sweep()
            scanned.set()
        self.addCleanup(self.service.stop_frontend_cleanup)
        with patch.object(self.service, 'cleanup_frontends', side_effect=scan):
            self.service.start_frontend_cleanup()
            worker = self.service._frontend_cleanup_thread
            self.service.start_frontend_cleanup()
            self.assertIs(self.service._frontend_cleanup_thread, worker)
            self.assertTrue(scanned.wait(7), 'cleanup worker never scanned')
            self.service.stop_frontend_cleanup()
            self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
