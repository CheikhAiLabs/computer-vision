"""Local persistent Incident Management portal; legacy webhook/alert API retained."""
from contextlib import asynccontextmanager
from datetime import datetime
import logging
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from prometheus_client import CollectorRegistry, REGISTRY, start_http_server
from sqlalchemy.exc import SQLAlchemyError
import uvicorn
from common.runtime import setup
from services.incident_receiver.enrichment import Enrichment
from services.incident_receiver.metrics import Metrics
from services.incident_receiver.models import utc
from services.incident_receiver.rules import RULES, SEVERITIES, STATUSES
from services.incident_receiver.store import Conflict, NotFound, Store

LOG=logging.getLogger(__name__)
ROOT=Path(__file__).parent
Status=Literal['FIRING','ACKNOWLEDGED','INVESTIGATING','MITIGATED','RESOLVED']
Severity=Literal['INFO','WARNING','HIGH','CRITICAL']


class Alert(BaseModel):
    status: Literal['firing','resolved']
    labels: dict[str,str] = Field(min_length=1,max_length=50)
    annotations: dict[str,str] = Field(default_factory=dict,max_length=50)
    startsAt: datetime
    endsAt: datetime | None = None
    fingerprint: str = Field(default='',max_length=128)

    @field_validator('endsAt',mode='before')
    @classmethod
    def empty_end(cls,value):
        return None if value=='' else value

    @field_validator('labels','annotations')
    @classmethod
    def bounded_strings(cls,value):
        if any(len(key)>100 or len(text)>4000 for key,text in value.items()):
            raise ValueError('Alert label/annotation too long')
        if 'alertname' in value and not 1<=len(value['alertname'])<=200:
            raise ValueError('Invalid alert name')
        for key in ('site','line'):
            if key in value and not 1<=len(value[key])<=100:
                raise ValueError('Invalid site/line')
        return value

    @model_validator(mode='after')
    def recovered_timestamp(self):
        if self.status=='resolved' and (not self.endsAt or utc(self.endsAt)<utc(self.startsAt)):
            raise ValueError('Recovered alerts require endsAt at or after startsAt')
        return self


class Webhook(BaseModel):
    status: Literal['firing','resolved']
    alerts: list[Alert] = Field(min_length=1,max_length=500)


class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    note: str = Field(default='',max_length=10000)


class Notes(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title: str | None = Field(default=None,min_length=1,max_length=200)
    root_cause: str | None = Field(default=None,max_length=10000)
    impact: str | None = Field(default=None,max_length=10000)
    remediation_actions: str | None = Field(default=None,max_length=10000)
    resolution_summary: str | None = Field(default=None,max_length=10000)


def duration(value):
    if value is None:
        return '—'
    seconds=max(0,int(value))
    if seconds<60:
        return f'{seconds}s'
    minutes,seconds=divmod(seconds,60)
    if minutes<60:
        return f'{minutes}m {seconds:02d}s'
    hours,minutes=divmod(minutes,60)
    return f'{hours}h {minutes:02d}m'


def create_app(store=None, *, runtime=True, registry=None):
    database=store or Store.from_env()
    registry=registry if registry is not None else (REGISTRY if runtime else CollectorRegistry())
    metrics=Metrics(database,registry)
    enrichment=Enrichment(database,metrics)

    @asynccontextmanager
    async def lifespan(app):
        if runtime:
            server,thread=start_http_server(9106,registry=registry)
            enrichment.start()
        else:
            database.initialize()
        try:
            yield
        finally:
            if runtime:
                enrichment.close()
                server.shutdown()
                server.server_close()
            database.engine.dispose()

    app=FastAPI(title='Local Incident Management',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.store=database
    app.state.metrics=metrics
    app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
    templates=Jinja2Templates(directory=ROOT/'templates')
    templates.env.filters['duration']=duration
    templates.env.filters['readable']=lambda value:value.replace('_',' ').title()

    @app.middleware('http')
    async def local_headers(request, call_next):
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; frame-ancestors 'self'"
        if request.url.path=='/docs':
            # Swagger's renderer uses inline styles; its scripts/assets remain local.
            response.headers['Content-Security-Policy']=response.headers['Content-Security-Policy'].replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
        return response

    @app.exception_handler(NotFound)
    async def missing(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=409)

    @app.exception_handler(SQLAlchemyError)
    async def database_failure(request,exc):
        LOG.error('Incident database operation failed; request can be retried')
        if not request.url.path.startswith(('/api/','/webhook','/alerts','/readyz')):
            return templates.TemplateResponse(request=request,name='unavailable.html',context={'nav':'', 'title':'Temporarily unavailable'},status_code=503)
        return JSONResponse({'detail':'Incident database unavailable; retry later'},status_code=503)

    def render(request, name, **context):
        return templates.TemplateResponse(request=request,name=name,context={
            'severities':SEVERITIES,'statuses':STATUSES,'types':RULES,
            'quiet_seconds':database.quiet_seconds,**context})

    @app.get('/docs',include_in_schema=False)
    def api_docs(request:Request):
        return render(request,'api.html',nav='',title='API reference')

    @app.get('/healthz')
    def health():
        return {'status':'ok','note':'Application alive; /readyz checks persistent storage'}

    @app.get('/readyz')
    def ready():
        if not database.ready():
            raise HTTPException(503,'Incident database is initializing')
        return {'status':'ready','database':'PostgreSQL','schema_version':1}

    @app.post('/webhook')
    def webhook(payload:Webhook):
        result=database.ingest([a.model_dump() for a in payload.alerts])
        metrics.notifications.labels(payload.status).inc()
        return result

    @app.get('/alerts')
    def legacy_alerts():
        return database.legacy_alerts()

    @app.get('/api/statistics')
    def statistics():
        return database.stats()

    @app.get('/api/incidents')
    def incidents(status:Status | None=None,severity:Severity | None=None,
                  kind:str | None=Query(None,alias='type',max_length=50),
                  line:str | None=Query(None,max_length=100),site:str | None=Query(None,max_length=100),
                  since:datetime | None=None,until:datetime | None=None,active:bool | None=None,
                  limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):
        if kind and kind not in RULES:
            raise HTTPException(422,'Unknown incident type')
        if since and until and utc(since)>utc(until):
            raise HTTPException(422,'since must precede until')
        return database.list(status=status,severity=severity,kind=kind,line=line,site=site,
                             since=since,until=until,active=active,limit=limit,offset=offset)

    @app.get('/api/incidents/{incident_id}')
    def detail(incident_id:int):
        return database.detail(incident_id)

    @app.patch('/api/incidents/{incident_id}')
    def edit(incident_id:int,body:Notes):
        return database.edit(incident_id,body.model_dump(exclude_none=True))

    @app.post('/api/incidents/{incident_id}/{action}')
    def transition(incident_id:int,action:Literal['acknowledge','investigate','mitigate','resolve'],body:Action | None=None):
        return database.transition(incident_id,action,body.note if body else '')

    @app.get('/api/incidents/{incident_id}/report')
    def report(incident_id:int):
        return database.report(incident_id)

    @app.get('/api/incidents/{incident_id}/report.md',response_class=PlainTextResponse)
    def markdown(incident_id:int):
        content=database.report(incident_id,markdown=True)
        return PlainTextResponse(content,media_type='text/markdown; charset=utf-8',
            headers={'Content-Disposition':f'attachment; filename="INC-{incident_id:06d}.md"'})

    @app.get('/')
    def dashboard(request:Request):
        return render(request,'dashboard.html',nav='dashboard',title='Operations overview',stats=database.stats(),recent=database.list(limit=8)['incidents'])

    @app.get('/incidents')
    def active(request:Request):
        return render(request,'incidents.html',nav='active',title='Active incidents',
                      data=database.list(active=True,limit=200),filters={})

    @app.get('/history')
    def history(request:Request,status:Status | None=None,severity:Severity | None=None,
                kind:str | None=Query(None,alias='type'),line:str | None=None,site:str | None=None,
                since:datetime | None=None,until:datetime | None=None,offset:int=Query(0,ge=0)):
        if kind and kind not in RULES:
            raise HTTPException(422,'Unknown incident type')
        if since and until and utc(since)>utc(until):
            raise HTTPException(422,'since must precede until')
        data=database.list(status=status,severity=severity,kind=kind,line=line,site=site,since=since,until=until,limit=50,offset=offset)
        return render(request,'incidents.html',nav='history',title='Incident history',data=data,
                      filters={'status':status or '','severity':severity or '','type':kind or '',
                               'line':line or '','site':site or '',
                               'since':since.isoformat() if since else '','until':until.isoformat() if until else ''})

    @app.get('/incidents/{incident_id}')
    def incident_page(request:Request,incident_id:int):
        data=database.detail(incident_id)
        if data['incident']['merged_into_id']:
            return RedirectResponse('/incidents/'+str(data['incident']['merged_into_id']),status_code=307)
        initial,latest={},{}
        for item in data['evidence']:
            initial.setdefault(item['source'],item)
            latest[item['source']]=item
        return render(request,'detail.html',nav='active' if data['incident']['status']!='RESOLVED' else 'history',
                      title=data['incident']['number'],data=data,initial=initial,latest=latest)

    @app.get('/statistics')
    def stats_page(request:Request):
        return render(request,'statistics.html',nav='statistics',title='Response statistics',stats=database.stats())

    return app


app=create_app()

if __name__=='__main__':
    setup()
    uvicorn.run(app,host='0.0.0.0',port=8090)
