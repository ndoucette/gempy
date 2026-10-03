import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch, Mock

from gempy_service import Service, ServiceError, process_info, owns_listener, start_backend


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Service({'accounts': {'Account': ['Example']},
                                'paths': {'lich_bin': '/tmp/lich.rbw', 'vellum_bin': '/tmp/vellum-fe'},
                                'web': {}}, directory=self.temp.name)
        self.p = dict(id='12:100', pid=12, start=100, character='Example', realm='prime',
                      port=8000, attachment='Headless', running=True, args=[])

    def test_prime_launch_explicitly_selects_gemstone(self):
        child = Mock(pid=12)
        child.poll.return_value = None
        with patch.object(self.service, '_discover', side_effect=[[], [self.p]]), patch('gempy_service.start_backend', return_value=child) as start, patch('gempy_service.owns_listener', return_value=True), patch.object(self.service, '_track'):
            self.service.ensure_backend('Example', 'prime')
        self.assertEqual(start.call_args.args[3], ['--gemstone'])

    def test_prime_discovery_accepts_explicit_and_legacy_game_flags(self):
        for flags in ([], ['--gemstone']):
            process = {'pid': 12, 'start': 100, 'args': ['ruby', '/tmp/lich.rbw', '--login', 'Example', '--detachable-client=8000', *flags]}
            with patch('gempy_service.Path.iterdir', return_value=iter([Path('/proc/12')])), patch('gempy_service.process_info', return_value=process):
                self.assertEqual(self.service._process_sessions()[0]['realm'], 'prime')

    def test_active_api_prime_runtime_codes_remain_attachable(self):
        for code in ('GS3', 'GS4', 'GSIV'):
            with patch.object(self.service, '_process_sessions', return_value=[dict(self.p)]), patch.object(self.service, '_api_records', return_value={12: {'game_code': code}}), patch('gempy_service.tcp_rows', return_value=[]), patch('gempy_service.socket_inodes', return_value=set()), patch('gempy_service.owns_listener', return_value=True):
                self.assertEqual(self.service._validated(self.p['id'])['realm'], 'prime')

    def test_private_state(self):
        self.assertEqual(os.stat(self.service.state).st_mode & 0o777, 0o700)

    def test_current_process_identity(self):
        p = process_info(os.getpid())
        self.assertEqual(p['pid'], os.getpid())
        self.assertGreater(p['start'], 0)
        self.assertGreater(p['epoch_start'], 1000000000)

    def test_listener_ownership_passive(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); sock.listen()
            with patch('gempy_service.socket.create_connection', side_effect=AssertionError('probe')):
                self.assertTrue(owns_listener(os.getpid(), sock.getsockname()[1]))

    def test_pid_reuse_rejected(self):
        with patch.object(self.service, '_discover', return_value=[dict(self.p, id='12:101')]):
            with self.assertRaises(ServiceError): self.service._validated('12:100')

    def test_listener_owner_rejected(self):
        with patch.object(self.service, '_discover', return_value=[self.p]), patch('gempy_service.owns_listener', return_value=False):
            with self.assertRaises(ServiceError): self.service.disconnect(self.p['id'], force=True)

    def test_unknown_realm_rejected(self):
        with patch.object(self.service, '_discover', return_value=[dict(self.p, realm='unknown')]):
            with self.assertRaises(ServiceError): self.service._validated(self.p['id'])

    def test_prime_test_isolation(self):
        prime = self.p
        test = dict(self.p, realm='test', id='13:101', pid=13, port=8001)
        with patch.object(self.service, '_discover', return_value=[prime, test]):
            self.assertEqual(self.service.ensure_backend('Example', 'prime')['id'], prime['id'])
            self.assertEqual(self.service.ensure_backend('Example', 'test')['id'], test['id'])

    def test_unconfigured_launch_rejected(self):
        with self.assertRaises(ServiceError): self.service.launch('Other', 'prime')

    def test_port_conflict_and_reservation(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); sock.listen()
            port = sock.getsockname()[1]
            first = self.service._allocate(port)
            second = self.service._allocate(port)
            self.assertNotEqual(first, port)
            self.assertNotEqual(first, second)

    def test_backend_active_api_registration(self):
        with patch('gempy_service.subprocess.Popen') as popen:
            start_backend('/tmp/lich.rbw', 'Example', 8001, ['--gemstone', '--test'], '/private/state')
        command = popen.call_args.args[0]
        self.assertIn('--active-session-dir=/private/state', command)
        self.assertIn('--test', command)

    def test_external_frontend_orderly_exit_rejected(self):
        p = dict(self.p, attachment='Attached')
        with patch.object(self.service, '_validated', return_value=p), patch.object(self.service, '_client_for', return_value=None), patch('gempy_service.socket.create_connection') as connect:
            with self.assertRaises(ServiceError): self.service.disconnect(p['id'])
            connect.assert_not_called()

    def test_existing_client_pairing_fragment_no_secret_logs(self):
        entry = {'port': 19000}
        p = dict(self.p, attachment='Attached')
        with patch.object(self.service, '_validated', return_value=p), patch.object(self.service, '_client_for', return_value=entry), patch.object(self.service, '_token', return_value='secret'):
            result = self.service.attach(p['id'])
        self.assertEqual(result['pairing_path'], '/despana#token=secret')
        self.assertNotIn('args', result)

    def test_managed_orderly_exit_without_new_listener_socket(self):
        entry = {'port': 19000}
        p = dict(self.p, attachment='Attached')
        with patch.object(self.service, '_validated', return_value=p), patch.object(self.service, '_client_for', return_value=entry), patch.object(self.service, '_websocket') as ws, patch('gempy_service.process_info', return_value=None), patch.object(self.service, '_stop_frontend') as stop, patch('gempy_service.socket.create_connection') as connect:
            self.assertTrue(self.service.disconnect(p['id'])['disconnected'])
            ws.assert_called_once_with(entry, {'t': 'cmd', 'd': {'text': 'exit'}})
            connect.assert_not_called()
            stop.assert_called_once()

    def test_connected_false_is_not_logged_out(self):
        p = dict(self.p)
        with patch.object(self.service, '_process_sessions', return_value=[p]), patch.object(self.service, '_api_records', return_value={12: {'connected': False, 'session_name': 'Example', 'game_code': 'GS3'}}), patch('gempy_service.tcp_rows', return_value=[]), patch('gempy_service.socket_inodes', return_value=set()), patch('gempy_service.owns_listener', return_value=True):
            sessions = self.service.sessions()
        self.assertEqual(sessions[0]['attachment'], 'Headless')
        self.assertTrue(sessions[0]['running'])

    def test_unknown_attachment_without_proc_visibility(self):
        with patch.object(self.service, '_process_sessions', return_value=[dict(self.p)]), patch.object(self.service, '_api_records', return_value={}), patch('gempy_service.tcp_rows', return_value=None):
            self.assertEqual(self.service.sessions()[0]['attachment'], 'Unknown')

    def test_external_frontend_not_removed(self):
        with patch('gempy_service.process_info', return_value={'start': 100, 'args': ['vellum-fe', '--frontend', 'gui']}), patch('gempy_service.os.pidfd_open') as kill:
            self.service._stop_frontend({'pid': 12, '_start': 100})
            kill.assert_not_called()

    def test_force_uses_pidfd_after_revalidation(self):
        with patch.object(self.service, '_validated', return_value=self.p) as validated, patch.object(self.service, '_client_for', return_value=None), patch('gempy_service.os.pidfd_open', return_value=77), patch('gempy_service.signal.pidfd_send_signal') as kill, patch('gempy_service.os.close'), patch('gempy_service.process_info', return_value=None):
            self.service.disconnect(self.p['id'], force=True)
            self.assertEqual(validated.call_count, 2)
            self.assertEqual(kill.call_args.args[0], 77)

    def test_launch_child_startup_failure(self):
        child = Mock(pid=12); child.poll.return_value = 1
        with patch.object(self.service, '_discover', return_value=[]), patch('gempy_service.start_backend', return_value=child):
            with self.assertRaises(ServiceError): self.service.ensure_backend('Example', 'prime')
        self.assertEqual(self.service.reserved, set())

    def test_authenticated_active_session_api(self):
        self.service.active_dir.joinpath('lich-active-sessions.json').write_text(json.dumps({'port': 12345, 'auth_token': 'private-secret'}))
        sock = Mock()
        sock.recv.return_value = (json.dumps({'ok': True, 'payload': {'sessions': [{'pid': 12, 'connected': False}]}}) + '\n').encode()
        context = Mock()
        context.__enter__ = Mock(return_value=sock)
        context.__exit__ = Mock(return_value=False)
        with patch('gempy_service.socket.create_connection', return_value=context):
            records = self.service._api_records([])
        self.assertIn(12, records)
        sent = json.loads(sock.sendall.call_args.args[0])
        self.assertEqual(sent['auth'], 'private-secret')
        self.assertEqual(sent['command'], 'snapshot')

    def test_rbw_process_discovery_and_realm_flags(self):
        process = {'pid': 12, 'start': 100, 'args': ['ruby', '/tmp/lich.rbw', '--login', 'Example', '--detachable-client=8001', '--gemstone', '--test']}
        with patch('gempy_service.Path.iterdir', return_value=iter([Path('/proc/12')])), patch('gempy_service.process_info', return_value=process):
            found = self.service._process_sessions()
        self.assertEqual(found[0]['realm'], 'test')
        self.assertEqual(found[0]['port'], 8001)

    def test_concurrent_launch_reuses_backend(self):
        import concurrent.futures
        process = dict(self.p)
        live = []
        child = Mock(pid=12)
        child.poll.return_value = None
        def start(*args):
            live.append(process)
            return child
        with patch.object(self.service, '_discover', side_effect=lambda: list(live)), patch('gempy_service.start_backend', side_effect=start) as backend, patch('gempy_service.owns_listener', return_value=True), patch.object(self.service, '_track'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _: self.service.ensure_backend('Example', 'prime'), range(2)))
        self.assertEqual(backend.call_count, 1)
        self.assertEqual(outcomes[0]['id'], outcomes[1]['id'])

    def test_restart_rediscovers_existing_backend(self):
        restarted = Service(self.service.config, directory=self.temp.name)
        with patch.object(restarted, '_discover', return_value=[self.p]), patch('gempy_service.start_backend') as backend:
            self.assertEqual(restarted.ensure_backend('Example', 'prime')['id'], self.p['id'])
            backend.assert_not_called()

    def test_reconnect_existing_unattached_client(self):
        entry = {'port': 19000}
        attached = dict(self.p, attachment='Attached')
        with patch.object(self.service, '_validated', side_effect=[self.p, self.p, attached]), patch.object(self.service, '_client_for', return_value=entry), patch.object(self.service, '_token', return_value='secret'), patch.object(self.service, '_websocket') as ws:
            self.service.attach(self.p['id'])
        self.assertEqual(ws.call_args.args[1]['t'], 'connect')

    def test_force_refuses_pid_changed_after_pidfd_open(self):
        with patch.object(self.service, '_validated', side_effect=[self.p, ServiceError('changed')]), patch.object(self.service, '_client_for', return_value=None), patch('gempy_service.os.pidfd_open', return_value=77), patch('gempy_service.signal.pidfd_send_signal') as kill, patch('gempy_service.os.close'):
            with self.assertRaises(ServiceError): self.service.disconnect(self.p['id'], force=True)
            kill.assert_not_called()

    def test_loopback_listener_owned_by_another_process_rejected(self):
        rows = [dict(local=8000, state='0A', inode='own', address='00000000'),
                dict(local=8000, state='0A', inode='foreign', address='0100007F')]
        with patch('gempy_service.socket_inodes', return_value={'own'}):
            self.assertFalse(owns_listener(12, 8000, rows))

    def test_lan_listener_does_not_authorize_loopback_exit(self):
        rows = [dict(local=8000, state='0A', inode='own', address='0101A8C0')]
        with patch('gempy_service.socket_inodes', return_value={'own'}):
            self.assertFalse(owns_listener(12, 8000, rows))

    def test_vellum_remote_same_port_not_selected(self):
        rows = [dict(local=50000, remote=8000, state='01', inode='client', address='0100007F', remote_address='0101A8C0')]
        entry = {'pid': 13, 'port': 18000}
        with patch.object(self.service, '_vellum_entries', return_value=iter([entry])), patch('gempy_service.tcp_rows', return_value=rows), patch('gempy_service.socket_inodes', return_value={'client'}):
            self.assertIsNone(self.service._client_for(dict(self.p, attachment='Attached')))

    def test_vellum_connection_requires_backend_reverse_tuple(self):
        rows = [dict(local=50000, remote=8000, state='01', inode='client', address='0100007F', remote_address='0100007F'),
                dict(local=8000, remote=50001, state='01', inode='backend', address='0100007F', remote_address='0100007F')]
        entry = {'pid': 13, 'port': 18000}
        with patch.object(self.service, '_vellum_entries', side_effect=lambda: iter([entry])), patch('gempy_service.tcp_rows', return_value=rows), patch('gempy_service.socket_inodes', side_effect=lambda pid: {'client'} if pid == 13 else {'backend'}):
            self.assertIsNone(self.service._client_for(dict(self.p, attachment='Attached')))
            rows[1]['remote'] = 50000
            self.assertEqual(self.service._client_for(dict(self.p, attachment='Attached')), entry)

    def test_supported_foreign_frontend_orderly_direct_exit(self):
        p = dict(self.p, attachment='Attached')
        sock = Mock()
        context = Mock()
        context.__enter__ = Mock(return_value=sock)
        context.__exit__ = Mock(return_value=False)
        with patch.object(self.service, '_validated', return_value=p), patch.object(self.service, '_client_for', return_value=None), patch.object(self.service, '_multi_client', return_value=True), patch('gempy_service.socket.create_connection', return_value=context) as connect, patch('gempy_service.process_info', return_value=None):
            self.assertTrue(self.service.disconnect(p['id'])['disconnected'])
        sock.sendall.assert_called_once_with(b'exit\n')
        connect.assert_called_once_with(('127.0.0.1', 8000), timeout=3)


if __name__ == '__main__': unittest.main()
