import os
import tempfile
import unittest
from unittest.mock import patch, Mock
from pathlib import Path
from client_options import connection_details, saga_environment, terminal_command, vellum_command
from gempy_service import Service, ServiceError


class ClientTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.service = Service({'paths': {'vellum_bin': '/tmp/vellum-fe', 'saga_bin': '/tmp/saga'}, 'accounts': {'A': ['Hero']}}, temp.name)
        self.p = dict(id='12:100', pid=12, start=100, port=8000, character='Hero', realm='test', attachment='Headless', args=[])

    def test_saga_opens_login_window_without_inherited_launch_target(self):
        with patch.dict(os.environ, {'SAGA_LICH_KEY': 'stale-secret', 'SAGA_LICH_MODE': '1',
                                    'SAGA_LICH_HOST': '127.0.0.1', 'SAGA_LICH_PORT': '8000',
                                    'SAGA_AUTO_LOGIN': 'Other@GS3', 'SAGA_VERSES': '1',
                                    'SAGA_VERSES_READY': '/tmp/stale-ready',
                                    'WSLENV': 'OTHER/p:SAGA_LICH_PORT/u:SAGA_AUTO_LOGIN/u'}):
            env = saga_environment()
        self.assertNotIn('SAGA_LICH_KEY', env)
        self.assertNotIn('SAGA_LICH_PORT', env)
        self.assertNotIn('SAGA_LICH_HOST', env)
        self.assertEqual(env['SAGA_LICH_MODE'], '0')
        self.assertEqual(env['SAGA_AUTO_LOGIN'], '')
        self.assertEqual(env['SAGA_VERSES'], '0')
        self.assertEqual(env['SAGA_VERSES_READY'], '')
        self.assertIn('OTHER/p', env['WSLENV'])
        self.assertNotIn('SAGA_LICH_PORT/u', env['WSLENV'])
        self.assertIn('SAGA_AUTO_LOGIN', env['WSLENV'].split(':'))

    def test_invalid_choice_does_not_start_backend(self):
        with patch.object(self.service, 'ensure_backend') as backend:
            with self.assertRaises(ServiceError): self.service.launch('Hero', 'prime', 'bogus')
        backend.assert_not_called()

    def test_mobile_layout_reuses_existing_engine(self):
        with patch.object(self.service, '_validated', return_value=dict(self.p, attachment='Attached')), patch.object(self.service, '_client_for', return_value={'port': 18000}), patch.object(self.service, '_token', return_value='secret'), patch('gempy_service.subprocess.Popen') as start:
            result = self.service.attach(self.p['id'], 'vellum_web')
        self.assertEqual(result['pairing_path'], '/play#token=secret')
        start.assert_not_called()

    def test_connection_details_do_not_attach(self):
        with patch.object(self.service, '_validated', return_value=self.p), patch('gempy_service.subprocess.Popen') as start, patch('gempy_service.socket.create_connection') as connect:
            result = self.service.attach(self.p['id'], 'connection')
        self.assertEqual(result['connection']['port'], 8000)
        start.assert_not_called(); connect.assert_not_called()

    def test_saga_missing_rejected_before_game_login(self):
        with patch('client_options.Path.is_file', return_value=False), patch.object(self.service, 'ensure_backend') as backend:
            with self.assertRaises(ServiceError): self.service.launch('Hero', 'prime', 'saga')
        backend.assert_not_called()

    def test_multiple_saga_windows_return_their_own_attach_details(self):
        self.service.config['accounts']['B'] = ['Other']
        for binary in ('/tmp/Saga.exe', '/tmp/saga'):
            with self.subTest(binary=binary):
                self.service.config['paths']['saga_bin'] = binary
                sessions = [self.p, dict(self.p, id='13:101', pid=13, character='Other', realm='prime', port=8001)]
                child = Mock(); child.poll.return_value = 0  # Saga's forwarding process may exit normally.
                with patch('gempy_service.Path.is_file', return_value=True), \
                     patch('gempy_service.subprocess.run', return_value=Mock(stdout='"Saga.exe","12"')), \
                     patch('gempy_service.Path.iterdir', return_value=[Path('/proc/12')]), \
                     patch('gempy_service.process_info', return_value={'args': [binary]}), \
                     patch.object(self.service, '_validated', side_effect=sessions), \
                     patch.object(self.service, '_track'), \
                     patch('gempy_service.tcp_rows', return_value=[]), \
                     patch('gempy_service.socket_inodes', return_value=set()), \
                     patch('gempy_service.subprocess.Popen', return_value=child) as start:
                    results = [self.service.attach(p['id'], 'saga') for p in sessions]
                self.assertEqual(start.call_count, 2)
                for call in start.call_args_list:
                    self.assertEqual(call.kwargs['env']['SAGA_LICH_MODE'], '0')
                for result, character, realm, port in zip(results, ('Hero', 'Other'), ('test', 'prime'), (8000, 8001)):
                    self.assertTrue(result['attachment_pending'])
                    details = result['connection']
                    self.assertEqual(details['client'], 'saga')
                    self.assertEqual(details['character'], character)
                    self.assertEqual(details['realm'], realm)
                    self.assertEqual(details['host'], '127.0.0.1')
                    self.assertEqual(details['port'], port)
                    self.assertNotIn('connected', result['message'].lower())

    def test_native_existing_attachment_does_not_false_report_success(self):
        p = dict(self.p, attachment='Attached', _connections={'old'})
        child = Mock(); child.poll.return_value = 1
        rows = [dict(local=8000, state='01', inode='old')]
        with patch.object(self.service, '_multi_client', return_value=True), patch('gempy_service.Path.iterdir', return_value=[]), patch('gempy_service.subprocess.Popen', return_value=child), patch.object(self.service, '_track'), patch('gempy_service.tcp_rows', return_value=rows), patch('gempy_service.socket_inodes', return_value={'old'}):
            with self.assertRaises(ServiceError): self.service._attach_native(p, 'vellum_gui')

    def test_saga_startup_failure_is_not_reported_as_pending_attachment(self):
        child = Mock(); child.poll.return_value = 1
        with patch('gempy_service.subprocess.Popen', return_value=child), patch.object(self.service, '_track'):
            with self.assertRaisesRegex(ServiceError, 'exited during startup'):
                self.service._attach_native(self.p, 'saga')

    def test_saga_keeps_legacy_lich_single_attachment_guard(self):
        with patch.object(self.service, '_multi_client', return_value=False), patch('gempy_service.subprocess.Popen') as start:
            with self.assertRaisesRegex(ServiceError, 'Lich version accepts one client'):
                self.service._attach_native(dict(self.p, attachment='Attached'), 'saga')
        start.assert_not_called()

    def test_native_new_socket_confirms_attachment(self):
        p = dict(self.p, _connections=set())
        rows = [dict(local=8000, state='01', inode='new')]
        with patch('gempy_service.Path.iterdir', return_value=[]), patch('gempy_service.subprocess.Popen') as start, patch.object(self.service, '_track'), patch('gempy_service.tcp_rows', return_value=rows), patch('gempy_service.socket_inodes', return_value={'new'}):
            result = self.service._attach_native(p, 'vellum_gui')
        self.assertIn('connected', result['message'])
        self.assertIn('--frontend', start.call_args.args[0])
        self.assertIn('gui', start.call_args.args[0])

    def test_no_display_rejected_before_backend(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(self.service, 'ensure_backend') as backend:
            with self.assertRaises(ServiceError): self.service.launch('Hero', 'prime', 'vellum_gui')
        backend.assert_not_called()

    def test_terminal_argv_preserves_spaces(self):
        command = vellum_command('/path with spaces/vellum-fe', 'Hero', 'test', 8012, 'tui')
        self.assertEqual(terminal_command({'clients': {'terminal_command': ['xterm', '-e']}}, command)[2], '/path with spaces/vellum-fe')
        with self.assertRaises(ValueError): terminal_command({'clients': {'terminal_command': 'xterm -e'}}, command)
