"""Terminal integration preserves the selected frontend using shared sessions."""
import unittest
from unittest.mock import Mock, patch
import launcher


class TerminalServiceTests(unittest.TestCase):
    def test_launch_uses_shared_backend_and_terminal_frontend(self):
        service = Mock()
        service.ensure_backend.return_value = {'port': 8123}
        with patch.object(launcher, 'TERMINAL_SERVICE', service), patch.object(launcher, 'connect_to_lich', return_value=True) as connect:
            self.assertTrue(launcher.launch_gemstone('Example', 'test'))
            service.ensure_backend.assert_called_once_with('Example', 'test')
            connect.assert_called_once_with('Example', 8123, 'test')

    def test_status_uses_shared_discovery_with_realm_isolation(self):
        service = Mock()
        service.sessions.return_value = [{'character':'Example','realm':'prime','port':8123}]
        columns = [{'items':['Example']}]
        with patch.object(launcher, 'TERMINAL_SERVICE', service):
            self.assertTrue(launcher.get_character_statuses(columns, 'prime')['Example'].online)
            self.assertFalse(launcher.get_character_statuses(columns, 'test')['Example'].online)
