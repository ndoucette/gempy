"""Administrator-only command API, sharing the app's existing session boundary."""
import json
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from command_service import CommandError


def register_command_routes(app, commands, authenticated):
    def call(function, *args):
        try:
            return function(*args)
        except CommandError as error:
            raise HTTPException(error.status, str(error)) from None

    @app.get('/api/command-targets')
    def targets(request: Request):
        authenticated(request)
        return {'targets': commands.targets()}

    @app.post('/api/command-batches/prepare')
    def prepare(request: Request):
        admin = authenticated(request, mutation=True)
        return commands.prepare(admin['csrf'])

    @app.post('/api/command-batches')
    async def submit(request: Request):
        admin = authenticated(request, mutation=True)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                raise HTTPException(413, 'Command batch is too large.')
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise HTTPException(400, 'Invalid command batch JSON.') from None
        return call(commands.submit, body, admin['csrf'])

    @app.get('/api/command-batches')
    def recent(request: Request, limit: int = 20):
        authenticated(request)
        return {'batches': call(commands.recent, limit)}

    @app.get('/api/command-batches/{request_id}')
    def receipt(request: Request, request_id: str):
        authenticated(request)
        return call(commands.get, request_id)

    @app.get('/api/control/script')
    def bridge_script(request: Request):
        authenticated(request)
        return FileResponse(Path(__file__).parent/'scripts/gempy_control.lic',
                            filename='gempy_control.lic', media_type='text/plain')
