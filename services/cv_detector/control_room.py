"""Local visual operations UI, colocated with CV; no additional service or CDN."""
import asyncio
from pathlib import Path
import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from common.line import CAMERAS

ROOT=Path(__file__).parent


def create_app(hub):
    app=FastAPI(title='Industrial Vision Control Room',docs_url=None,redoc_url=None)
    app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
    templates=Jinja2Templates(directory=ROOT/'templates')

    @app.middleware('http')
    async def headers(request,call_next):
        response=await call_next(request)
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'"
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/')
    def room(request:Request):
        return templates.TemplateResponse(request=request,name='control_room.html',context={'cameras':CAMERAS})

    @app.get('/healthz')
    def health():
        with hub.lock:
            return dict(status='ok',stream_fresh=any(time.time()-s['updated']<3 for s in hub.cameras.values()))

    @app.get('/api/state')
    def state():
        return hub.snapshot()

    @app.post('/api/reconciliation/reset')
    def reset():
        with hub.lock:
            hub.reconcile.reset()
            hub.emit('events',dict(timestamp=time.time(),site='local',line='line1',camera='entry',
                event='reconciliation_reset',state='NEW_OBSERVATION_SESSION',duration_seconds=0))
        return dict(status='reset',note='Counting totals retained; PLC comparison starts a new observation baseline')

    @app.get('/api/twin')
    def twin():
        state=hub.snapshot()
        nodes=[]
        for camera in state['cameras']:
            available=camera['up'] and time.time()-camera['updated']<3
            nodes.append(dict(id=camera['camera'],type='camera',state='unavailable' if not available else
                ('incident' if camera['anomalies'] else ('warning' if camera['reasons'] or not camera['tracking_ready'] else 'healthy')),
                objects=camera['objects'],last_frame=camera['updated']))
        plc=state['plc']
        nodes.insert(1,dict(id='conveyor',type='equipment',state='unavailable' if not plc else
            ('healthy' if plc['LineStatus']=='RUNNING' else ('incident' if plc['BlockedSensor'] else 'warning')),
            speed_mps=plc['ConveyorSpeed'] if plc else None))
        nodes.insert(3,dict(id='quality',type='inspection',state='unavailable' if not plc else
            ('warning' if plc['QualityScore']<.9 or any(c['quality'] for c in state['cameras']) else 'healthy'),
            score=plc['QualityScore'] if plc else None))
        return dict(timestamp=state['timestamp'],nodes=nodes,
                    edges=[['entry','conveyor'],['conveyor','process'],['process','quality'],['quality','exit']],
                    health=state['health'])

    def camera_check(camera):
        if camera not in CAMERAS:
            raise HTTPException(404,'Unknown camera')

    def current(camera,heat=False):
        camera_check(camera)
        with hub.lock:
            if time.time()-hub.cameras[camera]['updated']>3 or not hub.annotated:
                return None
            if heat:
                return hub.heatmaps.get(camera)
            saved=hub.jpeg.get(camera)
            return saved[0] if saved and time.time()-saved[1]<3 else None

    @app.get('/cameras/{camera}/snapshot.jpg')
    def snapshot(camera:str):
        jpeg=current(camera)
        if jpeg is None:
            raise HTTPException(503,'No recent annotated frame')
        return Response(jpeg,media_type='image/jpeg')

    @app.get('/cameras/{camera}/heatmap.jpg')
    def heatmap(camera:str):
        jpeg=current(camera,True)
        if jpeg is None:
            raise HTTPException(503,'No recent activity image')
        return Response(jpeg,media_type='image/jpeg')

    @app.get('/cameras/{camera}/annotated.mjpg')
    async def stream(camera:str,request:Request):
        camera_check(camera)
        if not hub.annotated:
            raise HTTPException(503,'Annotated output disabled')
        async def frames():
            while not hub.stop.is_set() and not await request.is_disconnected():
                jpeg=current(camera)
                if jpeg:
                    yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+jpeg+b'\r\n'
                await asyncio.sleep(.1)
        return StreamingResponse(frames(),media_type='multipart/x-mixed-replace; boundary=frame')

    @app.get('/snapshot.jpg')
    def legacy_snapshot():
        return snapshot('process')

    @app.get('/annotated.mjpg')
    async def legacy_stream(request:Request):
        return await stream('process',request)
    return app
