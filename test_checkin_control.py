"""Local Ruby control protocol integration; no Lich/game processes or accounts."""
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from gempy_service import Service, ServiceError, process_info


class ControlProtocolTests(unittest.TestCase):
    def test_real_socket_identity_ack_and_process_closure(self):
        with tempfile.TemporaryDirectory() as temp:
            service = Service({'accounts': {'A': ['Alpha']}}, directory=temp)
            capture = 'c' * 48
            path = service._checkin_socket(capture)
            context = json.dumps(dict(capture_id=capture, control_socket=str(path)))
            # Stub only the Lich interfaces; use the real preload/socket/adapter.
            source = '''
require ARGV[0]
module Lich
  module InternalAPI
    module ActiveSessions
      module Lifecycle; end
    end
  end
  module Common
    module ShutdownCoordinator; end
    module OrderlyShutdown
      def self.request_user_exit(**args)
        Thread.main.raise(SystemExit.new(0))
      end
    end
  end
end
$_DETACHABLE_CLIENT_REGISTRY_ = Object.new
def detachable_clients_snapshot; []; end
GempyCheckinOwnership.install(JSON.parse(ARGV[1]))
sleep 30
'''
            child = subprocess.Popen(['ruby', '-e', source, str(Path('scripts/gempy_checkin_ownership.rb').resolve()), context], stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not path.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                p = process_info(child.pid)
                self.assertIsNotNone(p)
                p.update(id=f"{p['pid']}:{p['start']}", attachment='Headless')
                with patch.object(service, '_validated', return_value=p):
                    status = service._checkin_control(p, capture, 'status')
                    self.assertEqual(status['state'], 'owned')
                    with self.assertRaises(ServiceError):
                        service._checkin_control(dict(p, start=p['start']+1), capture, 'logout')
                    self.assertIsNone(child.poll(), 'Wrong process identity must never exit')
                    result = service.disconnect_checkin(p['id'], capture)
                    self.assertTrue(result['disconnected'])
                self.assertEqual(child.wait(timeout=5), 0)
                self.assertNotIn(b'terminated with exception', child.stderr.read())
            finally:
                if child.poll() is None: child.terminate()
                child.wait(timeout=5)
                child.stderr.close()
