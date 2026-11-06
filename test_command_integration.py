"""Python admission to the real Ruby bridge over a temporary Unix socket.

The Ruby process has a deliberately fake game adapter: no Lich process or game
connection is started. Native adapter coverage lives in test_command_bridge.rb.
"""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
import unittest

from command_service import CommandService
from test_command_service import Sessions

RUBY = r'''
load ARGV.fetch(0)
class FakeGame
  def initialize(path); @path=path; @mutex=Mutex.new; end
  def snapshot; {key: [1],character: 'Hero',realm: 'prime',ready: true}; end
  def dispatch(command)
    @mutex.synchronize do
      return unless yield
      File.open(File.join(@path,'received'),'a') { |f| f.puts(JSON.generate(command)) }
      sleep 0.01 while command == 'block' && !File.exist?(File.join(@path,'release'))
    end
  end
end
bridge=GempyControl::Bridge.new(runtime: FakeGame.new(ARGV.fetch(1)))
server=GempyControl::Server.new(directory: File.join(ARGV.fetch(1),'control'),bridge: bridge).start
puts JSON.generate(bridge.record); STDOUT.flush
trap('TERM') { exit }
begin
  loop { sleep 0.05; server.refresh }
ensure
  server.stop
end
'''

@unittest.skipUnless(shutil.which('ruby'),'Ruby is required for local bridge integration')
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='gempy-command-test-');root=Path(self.tmp.name)
        self.child=subprocess.Popen(['ruby','-e',RUBY,str(Path('scripts/gempy_control.lic').resolve()),str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if not select.select([self.child.stdout],[],[],5)[0]: self.fail('fake bridge failed to start')
        self.record=json.loads(self.child.stdout.readline())
        self.service=Sessions(root);self.service.rows=[dict(id=self.record['session_id'],pid=self.child.pid,character='Hero',realm='prime')]
        self.commands=CommandService(self.service,root)
    def tearDown(self):
        (Path(self.tmp.name)/'release').touch()
        self.commands.close();self.child.terminate();self.child.communicate(timeout=5);self.tmp.cleanup()
    def send(self,command):
        targets=self.commands.targets();self.assertTrue(targets[0]['ready'])
        target={k:targets[0][k] for k in ('session_id','bridge_generation','character','realm')}
        body=dict(self.commands.prepare('admin'),command=command,targets=[target])
        self.commands.submit(body,'admin');return body
    def receipt(self,body,state,seconds=7):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            result=self.commands.get(body['request_id'])
            if result['targets'][0]['state']==state:return result
            time.sleep(.02)
        self.fail(f'Expected {state}: {result}')
    def test_literal_delivery_and_duplicate_through_real_private_socket(self):
        body=self.send('  ;pause all;look  ');self.receipt(body,'sent')
        self.commands.submit(body,'admin')
        self.assertEqual([json.loads(s) for s in (Path(self.tmp.name)/'received').read_text().splitlines()],['  ;pause all;look  '])
        self.assertEqual((Path(self.tmp.name)/'control'/f'{self.child.pid}.json').stat().st_mode & 0o777,0o600)
    def test_blocked_admitted_dispatch_is_queryable_then_resolves_without_replay(self):
        body=self.send('block');self.receipt(body,'unconfirmed')
        self.assertEqual((Path(self.tmp.name)/'received').read_text().splitlines(),['"block"'])
        (Path(self.tmp.name)/'release').touch();self.receipt(body,'sent')
        self.assertEqual((Path(self.tmp.name)/'received').read_text().splitlines(),['"block"'])

if __name__=='__main__':unittest.main()
