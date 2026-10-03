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

    def test_saga_keyless_detachable_handoff_and_windows_environment(self):
        with patch.dict(os.environ, {'SAGA_LICH_KEY': 'stale-secret', 'SAGA_AUTO_LOGIN': 'Other@GS3', 'WSLENV': 'OTHER/p:SAGA_LICH_PORT/u'}):
            env = saga_environment(8012)
        self.assertNotIn('SAGA_LICH_KEY', env)
        self.assertNotIn('SAGA_AUTO_LOGIN', env)
        self.assertEqual(env['SAGA_LICH_PORT'], '8012')
        self.assertIn('OTHER/p', env['WSLENV'])
        self.assertNotIn('SAGA_LICH_PORT/u', env['WSLENV'])

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

    def test_running_windows_saga_rejected(self):
        self.service.config['paths']['saga_bin'] = '/tmp/Saga.exe'
        with patch('gempy_service.Path.is_file', return_value=True), patch('gempy_service.subprocess.run', return_value=Mock(stdout='"Saga.exe","12"')):
            with self.assertRaisesRegex(ServiceError, 'Close Saga first'): self.service._check_client('saga')

    def test_native_existing_attachment_does_not_false_report_success(self):
        p = dict(self.p, attachment='Attached', _connections={'old'})
        child = Mock(); child.poll.return_value = 1
        rows = [dict(local=8000, state='01', inode='old')]
        with patch.object(self.service, '_multi_client', return_value=True), patch('gempy_service.Path.iterdir', return_value=[]), patch('gempy_service.subprocess.Popen', return_value=child), patch.object(self.service, '_track'), patch('gempy_service.tcp_rows', return_value=rows), patch('gempy_service.socket_inodes', return_value={'old'}):
            with self.assertRaises(ServiceError): self.service._attach_native(p, 'vellum_gui')

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
