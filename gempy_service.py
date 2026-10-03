"""Linux session lifecycle shared by terminal and web launchers.

Discovery never connects to a detachable listener. Credentials stay here.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
from urllib.parse import quote
from client_options import CLIENTS, connection_details, saga_binary, saga_environment, terminal_command, vellum_command


DEFAULT_REALM_FLAGS = {'prime': ['--gemstone'], 'test': ['--gemstone', '--test']}


class ServiceError(RuntimeError):
    pass


def process_info(pid):
    try:
        root = Path('/proc') / str(pid)
        if root.stat().st_uid != os.getuid():
            return None
        stat = (root / 'stat').read_text().rsplit(')', 1)[1].split()
        if stat[0] == 'Z':
            return None
        args = (root / 'cmdline').read_bytes().decode(errors='replace').rstrip('\0').split('\0')
        return {'pid': int(pid), 'start': int(stat[19]), 'args': args, 'epoch_start': int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime '))) + int(stat[19]) // os.sysconf('SC_CLK_TCK')}
    except (OSError, ValueError, IndexError):
        return None


def tcp_rows():
    rows = []
    readable = False
    for path in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            lines = Path(path).read_text().splitlines()[1:]
            readable = True
            for line in lines:
                fields = line.split()
                rows.append({'local': int(fields[1].split(':')[1], 16),
                             'remote': int(fields[2].split(':')[1], 16),
                             'state': fields[3], 'inode': fields[9], 'address': fields[1].split(':')[0],
                             'remote_address': fields[2].split(':')[0]})
        except (OSError, ValueError, IndexError):
            pass
    return rows if readable else None


def socket_inodes(pid):
    try:
        files = list((Path('/proc') / str(pid) / 'fd').iterdir())
    except OSError:
        return None
    result = set()
    for fd in files:
        try:
            link = os.readlink(fd)
            if link.startswith('socket:['):
                result.add(link[8:-1])
        except OSError:
            continue
    return result


def owns_listener(pid, port, rows=None):
    rows = tcp_rows() if rows is None else rows
    inodes = socket_inodes(pid)
    return rows is not None and inodes is not None and any(
        r['local'] == port and r['state'] == '0A' and r['inode'] in inodes
        and r['address'] in ('0100007F', '00000000') for r in rows) and not any(
        r['local'] == port and r['state'] == '0A' and r['address'] == '0100007F'
        and r['inode'] not in inodes for r in rows)


def start_backend(lich_bin, character, port, realm_flags=(), active_session_dir=None):
    cmd = ['ruby', os.path.abspath(lich_bin), '--login', character,
           f'--detachable-client={port}', '--without-frontend', *realm_flags]
    if active_session_dir:
        cmd.append(f'--active-session-dir={active_session_dir}')
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


class Service:
    def __init__(self, config, directory=None):
        self.config = config
        self.lich = str(Path(config.get('paths', {}).get('lich_bin', '')).expanduser().absolute())
        self.vellum = str(Path(config.get('paths', {}).get('vellum_bin', '')).expanduser().absolute())
        self.state = Path(directory or
                          os.environ.get('GEMPY_STATE_DIR') or
                          Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'gempy').expanduser()
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.state, 0o700)
        self.active_dir = self.state / 'active-sessions'
        self.active_dir.mkdir(mode=0o700, exist_ok=True)
        self.guard = threading.RLock()
        self.locks = {}
        self.reserved = set()
        self._children = []

    def _track(self, child):
        with self.guard:
            self._children.append(child)
        def reap():
            child.wait()
            with self.guard:
                if child in self._children:
                    self._children.remove(child)
        threading.Thread(target=reap, daemon=True).start()

    def _multi_client(self, p):
        for arg in p['args']:
            if Path(arg).name.lower().startswith('lich') and arg.endswith(('.rb', '.rbw')):
                try:
                    lich_path = Path(arg)
                    if not lich_path.is_absolute():
                        lich_path = Path(os.readlink(f"/proc/{p['pid']}/cwd")) / lich_path
                    text = (lich_path.resolve().parent / 'lib/main/main.rb').read_text()
                    return 'Thread.new(client)' in text and 'detachable_client_register(client)' in text
                except OSError:
                    pass
        return False

    def _lock(self, key):
        with self.guard:
            return self.locks.setdefault(key, threading.RLock())

    def _process_sessions(self):
        result = []
        for root in Path('/proc').iterdir():
            if not root.name.isdigit():
                continue
            p = process_info(root.name)
            if not p:
                continue
            args = p['args']
            if not any(Path(a).name.lower().startswith('lich') and a.endswith(('.rb', '.rbw')) for a in args):
                continue
            char, port = 'Unknown', 0
            for i, arg in enumerate(args):
                if arg == '--login' and i + 1 < len(args):
                    char = args[i + 1]
                elif arg.startswith('--detachable-client='):
                    try:
                        port = int(arg.split('=', 1)[1])
                    except ValueError:
                        pass
            realm = 'test' if '--test' in args else 'prime'
            if any(a in args for a in ('--dragonrealms', '--platinum', '--shattered', '--fallen')):
                realm = 'unknown'
            configured = self.config.get('realms', {})
            flags_by_realm = {realm: list(flags) for realm, flags in DEFAULT_REALM_FLAGS.items()}
            flags_by_realm.update({r: f.split() if isinstance(f, str) else list(f or []) for r, f in configured.items() if r in flags_by_realm})
            if realm != 'unknown':
                matches = []
                # The game-family flag is required for new logins, but old
                # Prime processes may have launched without it. Realm selection
                # depends on the remaining flags (not the common --gemstone).
                flags_by_realm = {r: [f for f in flags if f not in ('--gemstone', '--gs')]
                                  for r, flags in flags_by_realm.items()}
                for candidate, flags in flags_by_realm.items():
                    other = {f for r, values in flags_by_realm.items() if r != candidate for f in values}
                    if all(f in args for f in flags) and not any(f in args for f in other if f not in flags):
                        matches.append(candidate)
                realm = matches[0] if len(matches) == 1 else 'unknown'
            p.update(character=char, realm=realm, port=port)
            result.append(p)
        return result

    def _api_records(self, processes):
        dirs = {self.active_dir, Path('/tmp'), Path(self.lich).parent / 'temp'}
        for p in processes:
            for arg in p['args']:
                if arg.startswith('--active-session-dir='):
                    dirs.add(Path(arg.split('=', 1)[1]))
        result = {}
        for directory in dirs:
            try:
                discovery_path = directory / 'lich-active-sessions.json'
                if discovery_path.stat().st_uid != os.getuid():
                    continue
                discovery = json.loads(discovery_path.read_text())
                with socket.create_connection(('127.0.0.1', int(discovery['port'])), timeout=0.4) as sock:
                    sock.sendall((json.dumps({'command': 'snapshot', 'auth': discovery['auth_token'], 'payload': {}}) + '\n').encode())
                    response = b''
                    while b'\n' not in response and len(response) < 1024 * 1024:
                        chunk = sock.recv(8192)
                        if not chunk:
                            break
                        response += chunk
                data = json.loads(response)
                if data.get('ok'):
                    result.update({int(s['pid']): s for s in data['payload']['sessions']})
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return result

    def _discover(self):
        processes = self._process_sessions()
        records = self._api_records(processes)
        rows = tcp_rows()
        for p in processes:
            api = records.get(p['pid'], {})
            if api.get('session_name'):
                p['character'] = api['session_name']
            code = api.get('game_code')
            if code:
                p['realm'] = {'GS3': 'prime', 'GS4': 'prime', 'GSIV': 'prime', 'GST': 'test'}.get(str(code).upper(), 'unknown')
            if api.get('listener_port'):
                p['port'] = int(api['listener_port'])
            inodes = socket_inodes(p['pid'])
            known = rows is not None and inodes is not None and owns_listener(p['pid'], p['port'], rows)
            attached = known and any(r['local'] == p['port'] and r['state'] == '01' and r['inode'] in inodes for r in rows)
            p['attachment'] = 'Attached' if attached else ('Headless' if known else 'Unknown')
            p['id'] = f"{p['pid']}:{p['start']}"
            p['running'] = True
        return processes

    def sessions(self):
        return [{k: p[k] for k in ('id', 'pid', 'character', 'realm', 'port', 'attachment', 'running')}
                for p in self._discover()]

    def _validated(self, session_id):
        p = next((p for p in self._discover() if p['id'] == session_id), None)
        if not p:
            raise ServiceError('Session ended or process identity changed. Refresh sessions.')
        if p['realm'] not in ('prime', 'test') or not owns_listener(p['pid'], p['port']):
            raise ServiceError('Cannot verify the session realm and detachable listener ownership.')
        return p

    def _allocate(self, base=8000):
        with self.guard:
            used = {r['local'] for r in (tcp_rows() or [])} | self.reserved
            for port in range(base, 65536):
                if port in used:
                    continue
                try:
                    with socket.socket() as sock:
                        sock.bind(('127.0.0.1', port))
                    self.reserved.add(port)
                    return port
                except OSError:
                    continue
        raise ServiceError('No free port is available.')

    def launch(self, character, realm, client='vellum_despana'):
        with self._lock(('client-launch', client)):
            self._check_client(client)
            return self.attach(self.ensure_backend(character, realm)['id'], client)

    def _check_client(self, client):
        if client not in CLIENTS:
            raise ServiceError('Unknown client choice.')
        if client == 'saga':
            binary = saga_binary(self.config)
            if not binary or not Path(binary).is_file():
                raise ServiceError('Saga is not installed. Set paths.saga_bin to its executable or Linux AppImage.')
            if binary.lower().endswith('.exe'):
                # Saga's single-instance relay drops host/port. Never send an
                # attachment request to an already running instance.
                try:
                    result = subprocess.run(['/mnt/c/Windows/System32/tasklist.exe', '/FO', 'CSV', '/NH', '/FI', 'IMAGENAME eq Saga.exe'], capture_output=True, text=True, timeout=10, check=True)
                except (OSError, subprocess.SubprocessError):
                    raise ServiceError('Cannot check running Windows Saga instances.') from None
                if '"saga.exe"' in result.stdout.lower():
                    raise ServiceError('Close Saga first, then retry. Its running-instance relay cannot attach to a different Lich port.')
            else:
                for root in Path('/proc').iterdir():
                    p = process_info(root.name) if root.name.isdigit() else None
                    if p and any(Path(a).name.lower() in ('saga', Path(binary).name.lower()) for a in p['args'][:1]):
                        raise ServiceError('Close Saga first, then retry this attachment.')
        elif client in ('vellum_gui', 'vellum_tui'):
            if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
                raise ServiceError('No desktop display is available on the Gempy host. Use Connection details to run Vellum on your computer.')
            if client == 'vellum_tui':
                try:
                    terminal_command(self.config, [])
                except ValueError as error:
                    raise ServiceError(str(error)) from None

    def _attach_native(self, p, client):
        if p['attachment'] == 'Attached' and not self._multi_client(p):
            raise ServiceError('This Lich version accepts one client. Close the attached frontend and retry.')
        binary = saga_binary(self.config) if client == 'saga' else self.vellum
        command = [binary] if client == 'saga' else vellum_command(binary, p['character'], p['realm'], p['port'], 'gui' if client == 'vellum_gui' else 'tui')
        if client != 'saga':
            for root in Path('/proc').iterdir():
                current = process_info(root.name) if root.name.isdigit() else None
                if current and current['args'] == command:
                    return {'session_id': p['id'], 'message': 'This Vellum client is already open on the Gempy host.'}
        if client == 'vellum_tui':
            command = terminal_command(self.config, command)
        try:
            child = subprocess.Popen(command, env=saga_environment(p['port']) if client == 'saga' else None,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self._track(child)
        except OSError:
            raise ServiceError('Cannot start the selected client. Check its executable and the host desktop environment.') from None
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            # Establishment must be a new backend socket, not the preexisting
            # web client's attachment. Windows processes are not in /proc.
            rows = tcp_rows() or []
            inodes = socket_inodes(p['pid']) or set()
            connected = {r['inode'] for r in rows if r['local'] == p['port'] and r['state'] == '01' and r['inode'] in inodes}
            if connected - p['_connections']:
                return {'session_id': p['id'], 'message': ('Saga' if client == 'saga' else 'Vellum') + ' connected on the Gempy host.'}
            status = child.poll()
            if status is not None and status != 0:
                raise ServiceError('The selected client exited during startup. Check its installation and desktop display.')
            time.sleep(.2)
        raise ServiceError('The client was started but no new attachment was detected. Check its window on the Gempy host before retrying.')

    def ensure_backend(self, character, realm):
        configured = [c for chars in self.config.get('accounts', {}).values() for c in chars]
        if character not in configured or realm not in ('prime', 'test'):
            raise ServiceError('Unknown configured character or realm.')
        with self._lock(('launch', character.lower(), realm)):
            existing = next((p for p in self._discover() if p['character'].lower() == character.lower() and p['realm'] == realm), None)
            if existing:
                return existing
            port = self._allocate()
            try:
                flags = self.config.get('realms', {}).get(realm, DEFAULT_REALM_FLAGS[realm])
                if isinstance(flags, str):
                    flags = flags.split()
                child = start_backend(self.lich, character, port, flags, self.active_dir)
                self._track(child)
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise ServiceError('Lich exited during startup. Check its saved login and logs.')
                    if owns_listener(child.pid, port):
                        found = next((p for p in self._discover() if p['pid'] == child.pid), None)
                        if found:
                            return found
                    time.sleep(0.3)
                raise ServiceError('Lich did not open its listener before the startup timeout.')
            finally:
                with self.guard:
                    self.reserved.discard(port)

    def _vellum_entries(self):
        roots = [Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'vellum-fe/runtime/web-sessions',
                 Path.home() / '.vellum-fe/web-sessions']
        if os.environ.get('VELLUM_FE_RUNTIME_DIR'):
            roots.insert(0, Path(os.environ['VELLUM_FE_RUNTIME_DIR']) / 'web-sessions')
        if os.environ.get('VELLUM_FE_DIR'):
            roots.append(Path(os.environ['VELLUM_FE_DIR']) / 'web-sessions')
        for root in roots:
            for file in root.glob('*.json'):
                try:
                    entry = json.loads(file.read_text())
                    p = process_info(entry['pid'])
                    if not p or not any('vellum' in Path(a).name.lower() for a in p['args']):
                        continue
                    if entry.get('process_started_at') is not None and entry['process_started_at'] != p['epoch_start']:
                        continue
                    if owns_listener(p['pid'], int(entry['port'])):
                        entry['_start'] = p['start']
                        yield entry
                except (OSError, ValueError, KeyError, TypeError):
                    continue

    def _client_for(self, p):
        rows = tcp_rows() or []
        for entry in self._vellum_entries():
            sockets = socket_inodes(entry['pid']) or set()
            identity = (entry.get('launch') or {}).get('connection', {})
            backend_sockets = socket_inodes(p['pid']) if 'pid' in p else None
            connected = any(r['remote'] == p['port'] and r['remote_address'] in ('0100007F', '0000000000000000FFFF00000100007F')
                            and r['state'] == '01' and r['inode'] in sockets
                            and backend_sockets is not None and any(
                                backend['state'] == '01' and backend['inode'] in backend_sockets
                                and backend['local'] == r['remote'] and backend['remote'] == r['local']
                                and backend['address'] == r['remote_address']
                                and backend['remote_address'] == r['address'] for backend in rows)
                            for r in rows)
            if connected or (p.get('attachment') != 'Attached' and identity.get('kind') == 'lich' and identity.get('port') == p['port'] and identity.get('host') in ('127.0.0.1', 'localhost')):
                return entry
        return None

    def _token(self, entry):
        root = Path(entry.get('data_root') or os.environ.get('VELLUM_FE_DIR') or Path.home() / '.vellum-fe')
        try:
            return (root / 'web-token').read_text().strip()
        except OSError:
            raise ServiceError('Cannot read the Vellum pairing token.') from None

    def _websocket(self, entry, message):
        import websocket
        try:
            ws = websocket.create_connection(f"ws://127.0.0.1:{int(entry['port'])}/ws", timeout=5,
                                             origin=f"http://127.0.0.1:{int(entry['port'])}")
            try:
                ws.send(json.dumps({'t': 'auth', 'd': {'token': self._token(entry)}}))
                reply = json.loads(ws.recv())
                if reply.get('t') != 'hello':
                    raise ServiceError('Vellum pairing authentication failed.')
                ws.send(json.dumps(message))
            finally:
                ws.close()
        except ServiceError:
            raise
        except Exception:
            raise ServiceError('Unable to communicate with Vellum.') from None

    def attach(self, session_id, client='vellum_despana'):
        with self._lock(('client-launch', client)):
            return self._attach(session_id, client)

    def _attach(self, session_id, client):
        self._check_client(client)
        with self._lock(session_id):
            p = self._validated(session_id)
            if client == 'connection':
                return {'session_id': session_id, 'connection': connection_details(p['character'], p['port'])}
            if client in ('vellum_gui', 'vellum_tui', 'saga'):
                rows = tcp_rows() or []
                inodes = socket_inodes(p['pid']) or set()
                p['_connections'] = {r['inode'] for r in rows if r['local'] == p['port'] and r['state'] == '01' and r['inode'] in inodes}
                return self._attach_native(p, client)
            entry = self._client_for(p)
            if entry is None:
                if p['attachment'] == 'Attached' and not self._multi_client(p):
                    raise ServiceError('Another frontend is attached. Close that frontend before attaching Vellum.')
                web_port = self._allocate(18080)
                try:
                    child = subprocess.Popen([self.vellum, '--frontend', 'headless', '--character', p['character'],
                                              '--profile', f"gempy-{p['character']}-{p['realm']}", '--port', str(p['port']),
                                              '--host', '127.0.0.1', '--web-port', str(web_port), '--web-bind', '0.0.0.0', '--nosound'],
                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             start_new_session=True)
                    self._track(child)
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        if child.poll() is not None:
                            raise ServiceError('Vellum exited during startup.')
                        entry = next((e for e in self._vellum_entries() if e['pid'] == child.pid), None)
                        if entry:
                            break
                        time.sleep(0.2)
                    if entry is None:
                        raise ServiceError('Vellum did not publish its web listener before the startup timeout.')
                    self._validated(session_id)
                    self._websocket(entry, {'t': 'connect', 'd': {'mode': 'lich', 'host': '127.0.0.1', 'port': p['port'], 'character': p['character']}})
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        fresh = self._validated(session_id)
                        if fresh['attachment'] == 'Attached' and self._client_for(fresh):
                            break
                        time.sleep(0.2)
                    else:
                        raise ServiceError('Vellum could not attach to the Lich session.')
                finally:
                    with self.guard:
                        self.reserved.discard(web_port)
            if p['attachment'] != 'Attached' and entry is not None:
                fresh = self._validated(session_id)
                if fresh['attachment'] != 'Attached':
                    self._websocket(entry, {'t': 'connect', 'd': {'mode': 'lich', 'host': '127.0.0.1', 'port': p['port'], 'character': p['character']}})
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        fresh = self._validated(session_id)
                        if fresh['attachment'] == 'Attached' and self._client_for(fresh):
                            break
                        time.sleep(0.2)
                    else:
                        raise ServiceError('Vellum could not reattach to the Lich session.')
            return {'session_id': session_id, 'web_port': entry['port'],
                    'pairing_path': ('/play' if client == 'vellum_web' else '/despana') + '#token=' + quote(self._token(entry), safe='')}

    def disconnect(self, session_id, force=False):
        with self._lock(session_id):
            p = self._validated(session_id)
            entry = self._client_for(p)
            deadline = time.monotonic() + (10 if force else 70)
            if force:
                # Revalidate immediately before signaling; pidfd closes PID-reuse race.
                if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
                    raise ServiceError('Safe force disconnect requires Linux pidfd support.')
                fd = os.pidfd_open(p['pid'])
                try:
                    self._validated(session_id)
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
                finally:
                    os.close(fd)
            elif p['attachment'] == 'Attached' and entry:
                self._websocket(entry, {'t': 'cmd', 'd': {'text': 'exit'}})
            else:
                if p['attachment'] == 'Attached' and not self._multi_client(p):
                    raise ServiceError('This Lich version cannot accept an additional client. Close the attached frontend and retry.')
                self._validated(session_id)
                try:
                    with socket.create_connection(('127.0.0.1', p['port']), timeout=3) as sock:
                        # Revalidate after connect before submitting the destructive command.
                        self._validated(session_id)
                        sock.sendall(b'exit\n')
                        # Keep reading startup output until Lich consumes exit and closes.
                        sock.settimeout(0.5)
                        read_deadline = deadline
                        while time.monotonic() < read_deadline:
                            current = process_info(p['pid'])
                            if not current or current['start'] != p['start']:
                                break
                            try:
                                if not sock.recv(8192):
                                    break
                            except socket.timeout:
                                continue
                except OSError:
                    raise ServiceError('Unable to send the orderly exit command. Refresh and retry.') from None
            while time.monotonic() < deadline:
                current = process_info(p['pid'])
                if not current or current['start'] != p['start']:
                    if entry:
                        self._stop_frontend(entry)
                    return {'session_id': session_id, 'disconnected': True}
                time.sleep(0.25)
            raise ServiceError('Session did not terminate after orderly cleanup. Refresh and separately confirm Force Disconnect.')

    def _stop_frontend(self, entry):
        current = process_info(entry['pid'])
        if not current:
            return
        args = current['args']
        managed = any(i + 1 < len(args) and args[i + 1].startswith('gempy-')
                      and (arg == '--launch-profile' or (arg == '--profile' and '--frontend' in args and 'headless' in args))
                      for i, arg in enumerate(args))
        if not managed:
            return
        if current and current['start'] == entry['_start'] and hasattr(os, 'pidfd_open'):
            try:
                fd = os.pidfd_open(entry['pid'])
                try:
                    current = process_info(entry['pid'])
                    if current and current['start'] == entry['_start']:
                        signal.pidfd_send_signal(fd, signal.SIGTERM)
                finally:
                    os.close(fd)
            except OSError:
                pass
