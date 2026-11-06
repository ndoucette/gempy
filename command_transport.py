"""Private, same-user Linux transport. A failed send is never retried."""
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import sys

from gempy_service import process_info

IDENTITY = ('session_id', 'bridge_generation', 'character', 'realm', 'pid', 'process_start', 'protocol')


class TransportError(RuntimeError):
    def __init__(self, may_have_sent=False):
        super().__init__('Local control bridge unavailable.')
        self.may_have_sent = may_have_sent


class CommandTransport:
    def __init__(self, service):
        self.service = service
        config = getattr(service, 'config', {})
        state = getattr(service, 'state', Path.home()/'.local/state/gempy')
        self.directory = Path(config.get('command_control', {}).get('directory') or
                              os.environ.get('GEMPY_CONTROL_DIR') or Path(state)/'control').expanduser()

    @staticmethod
    def _private(path, kind):
        info = path.lstat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or not kind(info.st_mode):
            raise TransportError()
        return info

    def _record(self, target):
        if not sys.platform.startswith('linux') or not hasattr(socket, 'SO_PEERCRED'):
            raise TransportError()
        self._private(self.directory, stat.S_ISDIR)
        match = re.fullmatch(r'([1-9][0-9]{0,19}):([0-9]{1,20})', target['session_id'])
        if not match: raise TransportError()
        pid, start = map(int, match.groups())
        process = process_info(pid)
        if not process or process['start'] != start: raise TransportError()
        path = self.directory/f'{pid}.json'
        self._private(path, stat.S_ISREG)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
                raise TransportError()
            raw = stream.read(8193)
        if len(raw) > 8192: raise TransportError()
        record = json.loads(raw)
        if (record.get('pid'), record.get('process_start'), record.get('protocol')) != (pid, start, 1):
            raise TransportError()
        for key in ('session_id', 'character', 'realm'):
            if record.get(key) != target.get(key): raise TransportError()
        generation = record.get('bridge_generation')
        if not isinstance(generation, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', generation):
            raise TransportError()
        if target.get('bridge_generation') is not None and target['bridge_generation'] != generation:
            raise TransportError()
        if not {'dispatch', 'receipt'} <= set(record.get('features', [])): raise TransportError()
        filename = f'{pid}-{generation}.sock'
        if record.get('socket') != filename: raise TransportError()
        self._private(self.directory/filename, stat.S_ISSOCK)
        return record

    def exchange(self, target, request):
        contacted = False
        try:
            record = self._record(target)
            identity = {key: record[key] for key in IDENTITY}
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5.5 if request.get('action') == 'dispatch' else .3)
                client.connect(str(self.directory/record['socket']))
                pid, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
                if pid != record['pid'] or uid != os.getuid(): raise TransportError()
                current = process_info(pid)
                if not current or current['start'] != record['process_start']: raise TransportError()
                contacted = request.get('action') == 'dispatch'
                client.sendall((json.dumps(dict(request, **identity))+'\n').encode())
                raw = bytearray()
                while b'\n' not in raw and len(raw) <= 16384:
                    chunk = client.recv(4096)
                    if not chunk: break
                    raw.extend(chunk)
                if len(raw) > 16384 or not raw.endswith(b'\n'): raise TransportError(contacted)
                response = json.loads(raw)
                if not isinstance(response, dict) or any(response.get(k) != v for k,v in identity.items()):
                    raise TransportError(contacted)
                return response
        except Exception as error:
            raise TransportError(contacted or getattr(error, 'may_have_sent', False)) from None

    def target(self, session):
        target = dict(session_id=session['id'], character=session['character'], realm=session['realm'],
                      bridge_generation=None, ready=False, reason='Control unavailable. Install or start the local bridge.')
        try:
            record = self._record(target)
            target['bridge_generation'] = record['bridge_generation']
            reply = self.exchange(target, {'action': 'ping'})
            target.update(ready=reply.get('ready') is True,
                          reason='' if reply.get('ready') is True else 'Control unavailable. Runtime or game connection is not ready.')
        except Exception:
            pass
        return target
