import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from command_transport import CommandTransport, TransportError
from gempy_service import process_info


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/'control';self.root.mkdir(mode=0o700)
        self.pid=os.getpid();self.start=process_info(self.pid)['start']
        self.record=dict(pid=self.pid,process_start=self.start,session_id=f'{self.pid}:{self.start}',
                         character='Hero',realm='prime',bridge_generation='generation-1',protocol=1,
                         features=['dispatch','receipt'],socket=f'{self.pid}-generation-1.sock')
        self.path=self.root/f'{self.pid}.json';self.path.write_text(json.dumps(self.record));self.path.chmod(0o600)
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.bind(str(self.root/self.record['socket']))
        (self.root/self.record['socket']).chmod(0o600);self.sock.listen()
        self.service=type('Service',(),dict(state=Path(self.tmp.name),config={}))()
        self.transport=CommandTransport(self.service)
        self.session=dict(id=self.record['session_id'],pid=self.pid,character='Hero',realm='prime')
        self.target={k:self.record[k] for k in ('session_id','bridge_generation','character','realm')}
    def tearDown(self): self.sock.close();self.tmp.cleanup()
    def serve(self, mutate=None):
        def run():
            client,_=self.sock.accept()
            with client:
                request=json.loads(client.makefile('rb').readline())
                reply=dict(self.record,ready=True,state='sent',reason='')
                if mutate: mutate(reply)
                client.sendall((json.dumps(reply)+'\n').encode())
        thread=threading.Thread(target=run,daemon=True);thread.start();return thread
    def test_private_identity_bound_round_trip(self):
        thread=self.serve();target=self.transport.target(self.session);thread.join(1)
        self.assertTrue(target['ready']);self.assertEqual(target['bridge_generation'],'generation-1')
        thread=self.serve();reply=self.transport.exchange(self.target,dict(action='dispatch',request_id='test',command='look',deadline=1));thread.join(1)
        self.assertEqual(reply['state'],'sent')
    def test_unsafe_discovery_is_unavailable_without_contact(self):
        self.path.chmod(0o644)
        self.assertFalse(self.transport.target(self.session)['ready'])
        self.path.chmod(0o600);self.path.unlink();self.path.symlink_to('/etc/passwd')
        self.assertFalse(self.transport.target(self.session)['ready'])
    def test_generation_and_process_start_changes_fail_before_contact(self):
        for field,value in [('bridge_generation','old'),('session_id',f'{self.pid}:1')]:
            with self.assertRaises(TransportError) as raised:
                self.transport.exchange(dict(self.target,**{field:value}),dict(action='dispatch'))
            self.assertFalse(raised.exception.may_have_sent)
    def test_wrong_reply_identity_is_ambiguous_after_dispatch(self):
        thread=self.serve(lambda reply: reply.update(bridge_generation='replacement'))
        with self.assertRaises(TransportError) as raised:
            self.transport.exchange(self.target,dict(action='dispatch'))
        thread.join(1);self.assertTrue(raised.exception.may_have_sent)
    def test_socket_path_cannot_escape_control_directory(self):
        self.record['socket']='../foreign.sock';self.path.write_text(json.dumps(self.record))
        self.assertFalse(self.transport.target(self.session)['ready'])
    def test_directory_must_be_private(self):
        self.root.chmod(0o755)
        self.assertFalse(self.transport.target(self.session)['ready'])

if __name__=='__main__':unittest.main()
