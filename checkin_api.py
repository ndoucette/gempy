"""Authenticated HTTP surface for the Daily Check-in coordinator."""
from fastapi import HTTPException, Request
from daily_checkin import CheckinError


def register_checkin_routes(app, coordinator, authenticated, json_body):
    def invoke(action):
        try: return action()
        except CheckinError as error: raise HTTPException(409,str(error)) from None
        except ValueError as error: raise HTTPException(400,str(error)) from None

    @app.get('/api/checkin')
    def overview(request: Request):
        authenticated(request)
        return invoke(coordinator.snapshot)

    @app.post('/api/checkin/runs',status_code=202)
    async def start(request: Request):
        authenticated(request,mutation=True)
        body=await json_body(request)
        return invoke(lambda:coordinator.start_run(body.get('mode','due')))

    @app.get('/api/checkin/runs/{run_id}')
    def run(run_id: str,request: Request):
        authenticated(request)
        return invoke(lambda:coordinator.snapshot(run_id))

    @app.get('/api/checkin/runs/{run_id}/events')
    def events(run_id: str,request: Request,after: int=0):
        authenticated(request)
        if after<0:raise HTTPException(400,'Invalid event cursor.')
        return {'events':coordinator.events(run_id,after)}

    @app.post('/api/checkin/runs/{run_id}/{action}')
    def control(run_id: str,action: str,request: Request):
        authenticated(request,mutation=True)
        return invoke(lambda:coordinator.control(run_id,action))

    @app.post('/api/checkin/jobs/{job_id}/retry')
    def retry(job_id: str,request: Request):
        authenticated(request,mutation=True)
        return invoke(lambda:coordinator.retry(job_id))

    @app.post('/api/checkin/jobs/{job_id}/takeover')
    def takeover(job_id: str,request: Request):
        authenticated(request,mutation=True)
        return invoke(lambda:coordinator.takeover(job_id))

    @app.put('/api/checkin/settings')
    async def settings(request: Request):
        authenticated(request,mutation=True)
        body=await json_body(request)
        return invoke(lambda:coordinator.update_settings(body))
