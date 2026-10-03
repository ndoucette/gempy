import tempfile
import unittest
from unittest.mock import patch, Mock
import launcher as l

class LauncherTests(unittest.TestCase):
    def setUp(self):
        l.FRONTEND='vellum_despana'
        l.VELLUM_BIN='/home/nick/gs4/vellum-fe'
        l.init_realms({})
    def test_prime_login_flags(self):
        self.assertEqual(l.REALM_FLAGS[l.PRIME], ['--gemstone'])

    @patch.object(l,'allocate_web_port',return_value=9456)
    def test_command(self,allocate):
        self.assertEqual(l.vellum_command('Dartwen',8012,l.TEST), [l.VELLUM_BIN,'--launch-profile','gempy-Dartwen-test','--port','8012','--host','127.0.0.1','--web-port','9456','--web-bind','0.0.0.0'])
    @patch.object(l.subprocess,'check_output',return_value='ruby lich --login Tumerok --detachable-client=8000 --without-frontend')
    def test_detached_clients_are_included(self,ps):
        self.assertEqual(l.get_existing_clients(),[8000])
        ps.assert_called_once_with(['ps','ax'],universal_newlines=True)
    def test_realms(self):
        lines='ruby lich --login Dartwen --detachable-client=8000 --without-frontend\nruby lich --login Dartwen --detachable-client=8001 --without-frontend --gemstone --test'
        self.assertEqual(l.lookup_char_port('Dartwen',lines,l.PRIME),8000)
        self.assertEqual(l.lookup_char_port('Dartwen',lines,l.TEST),8001)
        self.assertEqual(l.lookup_char_port('Dart',lines),0)
    @patch.object(l,'connect_to_lich',return_value=True)
    @patch.object(l,'start_lich_backend')
    @patch.object(l,'get_process_list',return_value='ruby lich --login Dartwen --detachable-client=8010 --without-frontend')
    def test_existing_attach(self,ps,start,connect):
        self.assertTrue(l.launch_gemstone('Dartwen'))
        start.assert_not_called()
        connect.assert_called_once_with('Dartwen',8010,l.PRIME)
    @patch.object(l,'wait_for_port_listen',return_value=True)
    @patch.object(l,'start_lich_backend',return_value=Mock())
    @patch.object(l,'get_existing_clients',return_value=[8000,8001])
    @patch.object(l,'get_process_list',return_value='')
    @patch.object(l,'connect_to_lich',return_value=True)
    @patch.object(l.time,'sleep')
    def test_new_realm_port(self,sleep,connect,ps,clients,start,wait):
        l.launch_gemstone('Dartwen',l.TEST)
        start.assert_called_once_with('Dartwen',8002,l.TEST)
        wait.assert_called_once_with(8002,process=start.return_value)
        connect.assert_called_once_with('Dartwen',8002,l.TEST)
    @patch.object(l.subprocess,'Popen',side_effect=OSError('private output'))
    def test_start_failure(self,popen):
        with self.assertLogs(l.logger,level='ERROR') as logs:
            self.assertFalse(l.connect_to_lich('Dartwen',8000))
        self.assertNotIn('private output',' '.join(logs.output))
    @patch.object(l,'allocate_web_port',return_value=9456)
    @patch.object(l.time,'sleep')
    @patch.object(l.threading,'Thread')
    @patch.object(l.subprocess,'Popen')
    def test_nonzero_exit(self,popen,thread,sleep,allocate):
        popen.return_value.poll.return_value=2
        self.assertFalse(l.connect_to_lich('Dartwen',8000))
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
    def test_legacy_config(self):
        with tempfile.NamedTemporaryFile() as binary:
            l.init_paths({'paths':{'lich_bin':binary.name,'profanity_bin':binary.name}})
            self.assertEqual(l.FRONTEND,'profanity')
    @patch.object(l.subprocess,'run')
    def test_profanity_connect(self,run):
        l.FRONTEND='profanity'; l.PROFANITY_BIN='/tmp/profanity.rb'; l.PROFANITY_TEMPLATE=''
        l.connect_to_lich('Dartwen',8000)
        run.assert_called_once_with(['ruby','/tmp/profanity.rb','--port=8000','--char=Dartwen'],check=True)

if __name__=='__main__': unittest.main()
