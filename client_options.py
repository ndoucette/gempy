"""Shell-free commands for local clients and portable connection instructions."""
import os
from pathlib import Path
import shlex
import shutil

CLIENTS = ('vellum_despana', 'vellum_web', 'vellum_gui', 'vellum_tui', 'connection', 'saga')


def saga_binary(config):
    configured = config.get('paths', {}).get('saga_bin')
    if configured:
        return str(Path(configured).expanduser())
    for candidate in ('/opt/Saga/saga', '/mnt/c/Program Files/Saga/Saga.exe'):
        if Path(candidate).is_file():
            return candidate
    return ''


def vellum_command(binary, character, realm, port, frontend):
    return [binary, '--frontend', frontend, '--character', character,
            '--profile', f'gempy-{character}-{realm}', '--host', '127.0.0.1', '--port', str(port)]


def terminal_command(config, command):
    # A list of arguments, never a shell template. Append the executable argv.
    configured = config.get('clients', {}).get('terminal_command')
    if configured:
        if not isinstance(configured, list) or not all(isinstance(a, str) for a in configured) or not configured:
            raise ValueError('clients.terminal_command must be a nonempty list of arguments.')
        return [*configured, *command]
    for executable, flag in (('x-terminal-emulator', '-e'), ('xterm', '-e'), ('gnome-terminal', '--')):
        if shutil.which(executable):
            return [executable, flag, *command]
    raise ValueError('No terminal emulator found. Configure clients.terminal_command or use Connection details.')


def saga_environment(port):
    env = os.environ.copy()
    # No key: Saga sends SET_FRONTEND_PID for Lich's detachable protocol.
    # A key would select the distinct authenticated proxy handshake.
    for key in ('SAGA_LICH_KEY', 'SAGA_AUTO_LOGIN', 'SAGA_AUTO_LOGIN_ACCOUNT', 'SAGA_AUTO_LOGIN_MODE'):
        env.pop(key, None)
    env.update(SAGA_LICH_MODE='1', SAGA_LICH_HOST='127.0.0.1', SAGA_LICH_PORT=str(port))
    names = ['SAGA_LICH_MODE', 'SAGA_LICH_HOST', 'SAGA_LICH_PORT']
    existing = [item for item in env.get('WSLENV', '').split(':') if item and item.split('/')[0] not in names]
    env['WSLENV'] = ':'.join([*existing, *names])
    return env


def connection_details(character, port):
    common = ['--host', '127.0.0.1', '--port', str(port), '--character', character]
    return {'host': '127.0.0.1', 'port': port,
            'desktop_command': shlex.join(['vellum-fe', '--frontend', 'gui', *common]),
            'terminal_command': shlex.join(['vellum-fe', '--frontend', 'tui', *common]),
            'ssh_command': f'ssh -N -L {port}:127.0.0.1:{port} USER@SERVER',
            'note': 'Run the client on the Gempy host. For another computer, first open this SSH tunnel (replace USER@SERVER), then run the client there. If the local port is busy, choose another local port in both commands. Mobile Vellum can use the Vellum Web session URL.'}
