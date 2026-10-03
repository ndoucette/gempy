"""Private Gempy administrator web interface; game processes outlive this app."""
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
import yaml
from client_options import CLIENTS

COOKIE = 'gempy_session'
SESSION_SECONDS = 12 * 60 * 60


def state_dir():
    return Path(os.environ.get('GEMPY_STATE_DIR', Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'gempy')).expanduser()


def setup_password(directory=None):
    password = getpass.getpass('New Gempy administrator password: ')
    if len(password) < 12:
        raise ValueError('Use a password with at least 12 characters.')
    if password != getpass.getpass('Confirm password: '):
        raise ValueError('Passwords do not match.')
    save_password(password, directory)


def save_password(password, directory=None):
    directory = Path(directory or state_dir())
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    salt = secrets.token_bytes(32)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
    temporary = directory / ('auth-' + secrets.token_hex(8))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'salt': salt.hex(), 'hash': digest}, stream)
    os.replace(temporary, directory / 'auth.json')


def create_app(config, service=None, directory=None, session_seconds=SESSION_SECONDS, config_path='config.yaml'):
    if service is None:
        from gempy_service import Service
        service = Service(config)
    directory = Path(directory or state_dir())
    config_path = Path(config_path).expanduser().resolve()
    try:
        credentials = json.loads((directory / 'auth.json').read_text())
    except FileNotFoundError:
        raise RuntimeError('Set the Gempy password first with ./run.sh --set-password') from None
    sessions, failures, operations = {}, {}, {}
    lock = threading.RLock()
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='gempy-web')

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def authenticated(request, mutation=False):
        now = time.monotonic()
        with lock:
            expired = [key for key, value in sessions.items() if value['expires'] <= now]
            for key in expired:
                del sessions[key]
            session = sessions.get(request.cookies.get(COOKIE, ''))
        if not session:
            raise HTTPException(401, 'Please log in.')
        if mutation:
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                raise HTTPException(403, 'Invalid origin.')
            if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
                raise HTTPException(403, 'Invalid CSRF token.')
        return session

    @app.get('/')
    def index():
        return FileResponse(Path(__file__).parent / 'static/index.html', headers={'Cache-Control': 'no-store'})

    @app.middleware('http')
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
        return response

    async def json_body(request):
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, 'Invalid JSON.') from None
        if not isinstance(body, dict):
            raise HTTPException(400, 'Expected a JSON object.')
        return body

    @app.post('/api/login')
    async def login(request: Request):
        if request.headers.get('origin') and request.headers['origin'] != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Invalid origin.')
        address = request.client.host if request.client else 'local'
        now = time.monotonic()
        with lock:
            for key in list(failures):
                failures[key] = [stamp for stamp in failures[key] if stamp > now - 300]
                if not failures[key]:
                    del failures[key]
            attempts = failures.get(address, [])
            if len(attempts) >= 5 or sum(map(len, failures.values())) >= 50:
                raise HTTPException(429, 'Too many attempts. Try again in five minutes.')
            failures.setdefault(address, []).append(now)
        body = await json_body(request)
        password = body.get('password', '')
        if not isinstance(password, str) or len(password) > 1024:
            raise HTTPException(401, 'Invalid credentials.')
        digest = await __import__('asyncio').to_thread(hashlib.scrypt, password.encode(), salt=bytes.fromhex(credentials['salt']), n=16384, r=8, p=1)
        if body.get('username', 'admin') != 'admin' or not hmac.compare_digest(digest.hex(), credentials['hash']):
            raise HTTPException(401, 'Invalid credentials.')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with lock:
            sessions[token] = {'csrf': csrf, 'expires': now + session_seconds}
            failures.pop(address, None)
        response = JSONResponse({'csrf': csrf})
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=request.url.scheme == 'https', max_age=session_seconds)
        return response

    @app.get('/api/auth')
    def auth(request: Request):
        return {'csrf': authenticated(request)['csrf']}

    @app.post('/api/logout')
    def logout(request: Request):
        authenticated(request, True)
        with lock:
            sessions.pop(request.cookies.get(COOKIE), None)
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE)
        return response

    @app.get('/api/characters')
    def characters(request: Request):
        authenticated(request)
        with lock:
            return {'accounts': {key: list(value) for key, value in config.get('accounts', {}).items()}, 'realms': ['prime', 'test']}

    @app.post('/api/characters')
    async def add_character(request: Request):
        authenticated(request, True)
        body = await json_body(request)
        character, account = body.get('character'), body.get('account')
        if not isinstance(character, str) or not re.fullmatch(r'[A-Za-z]{1,50}', character.strip()):
            raise HTTPException(400, 'Use a character name containing only letters (up to 50).')
        if not isinstance(account, str) or not account.strip() or len(account.strip()) > 100 or any(ord(c) < 32 for c in account):
            raise HTTPException(400, 'Use an account label of 1–100 characters.')
        character, account = character.strip(), account.strip()
        with lock:
            temporary = None
            try:
                # Read the current file so unrelated settings edited since startup survive.
                source = config_path.read_text()
                saved = yaml.safe_load(source)
                if not isinstance(saved, dict):
                    raise ValueError('Invalid configuration')
                roster = saved.get('accounts') or {}
                if not isinstance(roster, dict) or any(not isinstance(key, str) or not isinstance(chars, list) or any(not isinstance(char, str) for char in chars) for key, chars in roster.items()):
                    raise ValueError('Invalid roster')
                if any(char.casefold() == character.casefold() for chars in roster.values() for char in chars):
                    raise HTTPException(409, 'That character is already in your roster.')
                account = next((key for key in roster if key.casefold() == account.casefold()), account)
                roster.setdefault(account, []).append(character)
                saved['accounts'] = roster
                # Replace only the accounts section, preserving other settings and comments.
                document = yaml.compose(source)
                section = next(((key, value) for key, value in document.value if key.value == 'accounts'), None)
                replacement = yaml.safe_dump({'accounts': roster}, sort_keys=False, allow_unicode=True)
                if document.flow_style:
                    source = yaml.safe_dump(saved, sort_keys=False, allow_unicode=True)
                elif section:
                    key, value = section
                    end = value.end_mark.index
                    # YAML includes following comments in a block node's span.
                    # Leave those comments in place for the next setting.
                    lines = source[key.start_mark.index:end].splitlines(keepends=True)
                    while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith('#')):
                        end -= len(lines.pop())
                    source = source[:key.start_mark.index] + replacement + source[end:]
                else:
                    source = source.rstrip() + '\n\n' + replacement
                if yaml.safe_load(source) != saved:
                    raise ValueError('Could not preserve configuration')
                fd, temporary = tempfile.mkstemp(prefix='.gempy-config-', dir=config_path.parent)
                with os.fdopen(fd, 'w') as stream:
                    os.fchmod(stream.fileno(), config_path.stat().st_mode & 0o777)
                    stream.write(source)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, config_path)
            except HTTPException:
                raise
            except (OSError, ValueError, yaml.YAMLError):
                raise HTTPException(500, 'Could not save the character. Check the configuration file and its permissions.') from None
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            config['accounts'] = roster
            return {'accounts': roster, 'character': character, 'account': account}

    @app.get('/api/sessions')
    def list_sessions(request: Request):
        authenticated(request)
        return {'sessions': service.sessions()}

    def submit(action, hostname):
        operation_id = secrets.token_urlsafe(16)
        with lock:
            for key in list(operations):
                if operations[key]['time'] < time.monotonic() - 3600 and operations[key]['status'] != 'running':
                    del operations[key]
            if sum(op['status'] == 'running' for op in operations.values()) >= 16:
                raise HTTPException(429, 'Too many operations are running.')
            operations[operation_id] = {'status': 'running', 'time': time.monotonic()}
        def run():
            try:
                result = action()
                if isinstance(result, dict) and ('web_port' in result or 'port' in result) and 'pairing_path' in result:
                    host = '[' + hostname + ']' if ':' in hostname else hostname
                    path = result['pairing_path']
                    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
                        raise ValueError('Invalid client pairing path')
                    result = {'client_url': f"http://{host}:{int(result.get('web_port', result.get('port')))}{path}"}
                with lock:
                    operations[operation_id].update(status='done', result=result)
            except Exception as error:
                from gempy_service import ServiceError
                safe_error = str(error) if isinstance(error, ServiceError) else 'Operation failed. Check local session status and try again; force disconnect requires separate confirmation.'
                # Service errors may contain process paths or pairing secrets: keep them server-side.
                with lock:
                    operations[operation_id].update(status='failed', error=safe_error)
        executor.submit(run)
        return {'operation_id': operation_id}

    @app.post('/api/launch')
    async def launch(request: Request):
        authenticated(request, True)
        body = await json_body(request)
        character, realm = body.get('character'), body.get('realm')
        allowed = [char for chars in config.get('accounts', {}).values() for char in chars]
        if character not in allowed or realm not in ('prime', 'test'):
            raise HTTPException(400, 'Unknown character or realm.')
        client = body.get('client', 'vellum_despana')
        if client not in CLIENTS:
            raise HTTPException(400, 'Unknown client choice.')
        return submit(lambda: service.launch(character, realm) if client == 'vellum_despana' else service.launch(character, realm, client), request.url.hostname)

    @app.post('/api/sessions/{session_id}/{action}')
    async def session_action(session_id: str, action: str, request: Request):
        authenticated(request, True)
        if action == 'attach':
            body = await json_body(request) if await request.body() else {}
            client = body.get('client', 'vellum_despana')
            if client not in CLIENTS:
                raise HTTPException(400, 'Unknown client choice.')
            callback = lambda: service.attach(session_id) if client == 'vellum_despana' else service.attach(session_id, client)
        elif action in ('disconnect', 'force-disconnect'):
            callback = lambda: service.disconnect(session_id, force=action == 'force-disconnect')
        else:
            raise HTTPException(404)
        return submit(callback, request.url.hostname)

    @app.get('/api/operations/{operation_id}')
    def operation(operation_id: str, request: Request):
        authenticated(request)
        with lock:
            value = operations.get(operation_id)
            if value is None:
                raise HTTPException(404)
            return {key: item for key, item in value.items() if key != 'time'}

    return app
