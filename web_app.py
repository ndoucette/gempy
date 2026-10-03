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
    from telemetry import TelemetryStore
    telemetry = TelemetryStore(directory)
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
        telemetry.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.telemetry = telemetry

    def reporter_digest():
        try:
            return (directory / 'reporter-token.sha256').read_text().strip()
        except FileNotFoundError:
            return ''

    @app.post('/api/telemetry/token')
    def rotate_reporter_token(request: Request):
        authenticated(request, mutation=True)
        token = secrets.token_urlsafe(32)
        temporary = directory / ('reporter-token-' + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(hashlib.sha256(token.encode()).hexdigest())
        os.replace(temporary, directory / 'reporter-token.sha256')
        return {'token': token}

    @app.post('/api/telemetry/update')
    async def ingest_telemetry(request: Request):
        authorization = request.headers.get('authorization', '')
        digest = reporter_digest()
        if not digest or not authorization.startswith('Bearer ') or not hmac.compare_digest(
                hashlib.sha256(authorization[7:].encode()).hexdigest(), digest):
            raise HTTPException(401, 'Invalid reporter token.')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 256 * 1024:
                raise HTTPException(413, 'Telemetry snapshot is too large.')
        try:
            body = json.loads(raw)
            return telemetry.ingest(body, service.sessions())
        except RecursionError:
            raise HTTPException(400, 'Telemetry snapshot is too deeply nested.') from None
        except (ValueError, TypeError) as error:
            raise HTTPException(400, str(error)) from None

    @app.get('/api/settings')
    def get_settings(request: Request):
        authenticated(request)
        return {**telemetry.settings(), 'reporter_configured': bool(reporter_digest())}

    @app.post('/api/settings')
    async def change_settings(request: Request):
        authenticated(request, mutation=True)
        try:
            return telemetry.update_settings(await json_body(request))
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.get('/api/progress')
    def progress(request: Request, period: str = 'week', realm: str | None = None,
                 character: str | None = None, start: str | None = None, end: str | None = None):
        authenticated(request)
        try:
            return telemetry.progress(period=period, realm=realm, character=character, start=start, end=end)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.post('/api/history/import')
    def import_history(request: Request):
        authenticated(request, mutation=True)
        lich = config.get('paths', {}).get('lich_bin')
        roots = [Path(lich).expanduser().resolve().parent / 'data'] if lich else []
        return telemetry.import_saga(roots)

    @app.get('/api/history/backup')
    def backup_history(request: Request):
        authenticated(request)
        from fastapi.responses import Response
        # SQLite's backup API provides a consistent snapshot while reporters write.
        with tempfile.TemporaryDirectory(prefix='gempy-backup-') as temporary:
            path = Path(temporary) / 'history.sqlite3'
            telemetry.backup(path)
            return Response(path.read_bytes(), media_type='application/octet-stream',
                            headers={'Content-Disposition': 'attachment; filename="gempy-history.sqlite3"'})

    @app.get('/api/reporter/script')
    def reporter_script(request: Request):
        authenticated(request)
        return FileResponse(Path(__file__).parent / 'scripts/gempy_reporter.lic',
                            filename='gempy_reporter.lic', media_type='text/plain')

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
        except (ValueError, UnicodeDecodeError, RecursionError):
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
    @app.patch('/api/characters')
    @app.patch('/api/accounts')
    async def add_character(request: Request):
        authenticated(request, True)
        body = await json_body(request)
        character, account = body.get('character'), body.get('account')
        rename_account = request.url.path == '/api/accounts'
        if not rename_account and (not isinstance(character, str) or not re.fullmatch(r'[A-Za-z]{1,50}', character.strip())):
            raise HTTPException(400, 'Use a character name containing only letters (up to 50).')
        if not isinstance(account, str) or not account.strip() or len(account.strip()) > 100 or any(ord(c) < 32 for c in account):
            raise HTTPException(400, 'Use an account label of 1–100 characters.')
        character, account = character.strip() if isinstance(character, str) else None, account.strip()
        new_character = body.get('new_character', character)
        new_account = body.get('new_account')
        if not rename_account and (not isinstance(new_character, str) or not re.fullmatch(r'[A-Za-z]{1,50}', new_character.strip())):
            raise HTTPException(400, 'Use a character name containing only letters (up to 50).')
        if rename_account and (not isinstance(new_account, str) or not new_account.strip() or len(new_account.strip()) > 100 or any(ord(c) < 32 for c in new_account)):
            raise HTTPException(400, 'Use an account label of 1–100 characters.')
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
                account = next((key for key in roster if key.casefold() == account.casefold()), account)
                if rename_account:
                    if account not in roster:
                        raise HTTPException(404, 'Account label not found.')
                    new_account = new_account.strip()
                    if any(key != account and key.casefold() == new_account.casefold() for key in roster):
                        raise HTTPException(409, 'That account label already exists.')
                    roster = {new_account if key == account else key: chars for key, chars in roster.items()}
                    account = new_account
                elif request.method == 'PATCH':
                    source_account = next((key for key, chars in roster.items() if any(c.casefold() == character.casefold() for c in chars)), None)
                    if source_account is None:
                        raise HTTPException(404, 'Character not found.')
                    new_character = new_character.strip()
                    if any(c.casefold() == new_character.casefold() and c.casefold() != character.casefold() for chars in roster.values() for c in chars):
                        raise HTTPException(409, 'That character is already in your roster.')
                    roster[source_account] = [c for c in roster[source_account] if c.casefold() != character.casefold()]
                    roster.setdefault(account, []).append(new_character)
                    if source_account != account and not roster[source_account]:
                        del roster[source_account]
                    character = new_character
                else:
                    if any(char.casefold() == character.casefold() for chars in roster.values() for char in chars):
                        raise HTTPException(409, 'That character is already in your roster.')
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
        return {'sessions': telemetry.enrich(service.sessions())}

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
