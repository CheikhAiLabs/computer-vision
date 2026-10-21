"""Transactional incident lifecycle, idempotent alerts and deterministic correlation."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import os
import threading
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from services.incident_receiver.migrations import LOCK_ID, migrate
from services.incident_receiver.models import (AlertOccurrence, Evidence, Incident, IncidentEvent,
                                               Report, Signal, utc, utcnow)
from services.incident_receiver.reports import markdown_report
from services.incident_receiver.rules import (JAM_ALERTS, RULES, SEVERITIES, STATUSES, classify,
                                             jam_compatible)


class NotFound(ValueError):
    pass


class Conflict(ValueError):
    pass


def stamp(value):
    return utc(value).isoformat() if value else None


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False,default=str).encode()).hexdigest()


def elapsed(end, start):
    return max(0, (utc(end)-utc(start)).total_seconds())


def incident_dict(row, now):
    result = {column.name: getattr(row,column.name) for column in Incident.__table__.columns}
    for key,value in list(result.items()):
        if isinstance(value,datetime):
            result[key] = stamp(value)
    result['duration_seconds'] = elapsed(row.resolved_at or now, row.started_at)
    return result


def alert_dict(row):
    return {'id':row.id,'incident_id':row.incident_id,'fingerprint':row.fingerprint,
            'name':row.name,'alertname':row.name,'status':row.status,
            'severity':row.labels.get('severity','unknown'),'labels':row.labels,
            'annotations':row.annotations,'starts_at':stamp(row.starts_at),'ends_at':stamp(row.ends_at),
            'startsAt':stamp(row.starts_at),'endsAt':stamp(row.ends_at) or '',
            'received_at':stamp(row.received_at),'last_received_at':stamp(row.last_received_at)}


def event_dict(row):
    return {**{name:getattr(row,name) for name in ('id','source','event_type','message','alert_name','status','labels','evidence')},
            'timestamp':stamp(row.timestamp)}


def evidence_dict(row):
    return {'id':row.id,'source':row.source,'timestamp':stamp(row.timestamp),
            'received_at':stamp(row.received_at),'payload':row.payload}


class Store:
    def __init__(self, url=None, *, clock=utcnow, correlation_seconds=90,
                 quiet_seconds=30, signal_max_age=30, signal_interval=10):
        if url is None:
            url = os.getenv('INCIDENT_DATABASE_URL') or URL.create('postgresql+psycopg',
                username=os.getenv('POSTGRES_USER','incidents'),
                password=os.getenv('POSTGRES_PASSWORD','local-demo-only'),
                host=os.getenv('POSTGRES_HOST','incident-db'),port=5432,
                database=os.getenv('POSTGRES_DB','computer_vision'))
        options = {'pool_pre_ping':True}
        if str(url).startswith('sqlite'):
            options.update(connect_args={'check_same_thread':False},poolclass=StaticPool)
        else:
            options.update(connect_args={'connect_timeout':3},pool_size=5,max_overflow=5,pool_timeout=3)
        self.engine = create_engine(url,**options)
        self.sessions = sessionmaker(self.engine,expire_on_commit=False)
        self.clock = clock
        self.window = timedelta(seconds=correlation_seconds)
        self.quiet_seconds = quiet_seconds
        self.signal_max_age = signal_max_age
        self.signal_interval = signal_interval
        self.lock = threading.RLock()
        self.initialized = False

    @classmethod
    def from_env(cls):
        return cls(correlation_seconds=int(os.getenv('INCIDENT_CORRELATION_WINDOW_SECONDS','90')),
                   quiet_seconds=int(os.getenv('INCIDENT_AUTO_RESOLVE_SECONDS','30')),
                   signal_max_age=int(os.getenv('INCIDENT_SIGNAL_MAX_AGE_SECONDS','30')),
                   signal_interval=int(os.getenv('INCIDENT_SIGNAL_INTERVAL_SECONDS','10')))

    def initialize(self):
        migrate(self.engine)
        self.initialized = True

    def ready(self):
        if not self.initialized:
            return False
        with self.engine.connect() as connection:
            return connection.execute(text('SELECT 1')).scalar() == 1

    @contextmanager
    def transaction(self):
        if not self.initialized:
            raise SQLAlchemyError('Incident schema is not initialized; retry after readiness')
        # PostgreSQL lock also serializes multiple app processes during correlation.
        with self.lock, self.sessions.begin() as session:
            if self.engine.dialect.name == 'postgresql':
                session.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':LOCK_ID})
            yield session

    def event(self, session, incident, source, kind, message, **kwargs):
        session.add(IncidentEvent(incident_id=incident.id,timestamp=kwargs.pop('timestamp',self.clock()),
                    source=source,event_type=kind,message=message,**kwargs))

    def _signals(self, session, site, line, now):
        rows = session.scalars(select(Signal).where(Signal.site==site,Signal.line==line,
              Signal.received_at >= now-timedelta(seconds=self.signal_max_age),
              Signal.timestamp >= now-timedelta(seconds=self.signal_max_age))).all()
        return {row.source:row for row in rows}

    def _new(self, session, kind, family, site, line, started, now):
        rule = RULES[kind]
        incident = Incident(title=rule.title,type=kind,family=family,severity=rule.severity,status='FIRING',
            site=site,line=line,created_at=now,started_at=started,detected_at=now,last_updated_at=now,
            suggested_root_cause=rule.cause,remediation=list(rule.steps))
        session.add(incident)
        session.flush()
        incident.number = f'INC-{incident.id:06d}'
        self.event(session,incident,'correlation','DETECTED','Incident detected from an actual Alertmanager notification.')
        self.event(session,incident,'correlation','FIRING','Incident opened; alert state and operator workflow are tracked separately.',status='FIRING')
        for signal in self._signals(session,site,line,now).values():
            self._evidence(session,incident,signal)
        return incident

    def _evidence(self, session, incident, signal):
        session.add(Evidence(incident_id=incident.id,source=signal.source,timestamp=signal.timestamp,
                            received_at=signal.received_at,payload=signal.payload))
        self.event(session,incident,signal.source,'SIGNAL_SNAPSHOT',
                   f'{signal.source} evidence recorded from an actual source sample.',
                   timestamp=signal.timestamp,evidence={'payload':signal.payload,'received_at':stamp(signal.received_at)})

    def _promote(self, session, incident, kind, family):
        if incident.type == kind:
            return
        previous = incident.type
        rule = RULES[kind]
        incident.type,incident.family,incident.title = kind,family,rule.title
        incident.severity = max((incident.severity,rule.severity),key=SEVERITIES.index)
        incident.suggested_root_cause,incident.remediation = rule.cause,list(rule.steps)
        self.event(session,incident,'correlation','CLASSIFICATION_CHANGED',
                   f'Classification changed from {previous} to {kind} using correlated source alerts.')

    def _merge(self, session, primary, secondary, now):
        secondary_status=secondary.status
        for field in ('root_cause','impact','remediation_actions','resolution_summary'):
            if not getattr(primary,field) and getattr(secondary,field):
                setattr(primary,field,getattr(secondary,field))
        for model in (AlertOccurrence,IncidentEvent,Evidence):
            session.execute(update(model).where(model.incident_id==secondary.id).values(incident_id=primary.id))
        secondary.merged_into_id = primary.id
        secondary.status,secondary.resolved_at = 'RESOLVED',now
        secondary.last_updated_at = now
        secondary.resolution_summary = f'Correlated into {primary.number}; source history retained there.'
        primary.started_at = min(utc(primary.started_at),utc(secondary.started_at))
        for field in ('acknowledged_at','investigating_at','mitigated_at'):
            values = [utc(v) for v in (getattr(primary,field),getattr(secondary,field)) if v]
            if values:
                setattr(primary,field,min(values))
        if primary.acknowledged_at:
            primary.mtta_seconds = elapsed(primary.acknowledged_at,primary.detected_at)
        if STATUSES.index(secondary_status) > STATUSES.index(primary.status):
            primary.status = secondary_status
        self.event(session,primary,'correlation','INCIDENT_CORRELATED',
                   f'{secondary.number} correlated into {primary.number}; original number remains an audit reference.',
                   evidence={'merged_incident_id':secondary.id,'root_cause':secondary.root_cause,
                             'impact':secondary.impact,'remediation_actions':secondary.remediation_actions})

    def _choose(self, session, name, labels, site, line, started, now):
        signals = self._signals(session,site,line,now)
        monitoring = signals.get('Monitoring')
        cv = signals.get('OpenCV')
        kind,family = classify(name,labels,monitoring.payload if monitoring else {})
        candidates = session.scalars(select(Incident).where(Incident.site==site,Incident.line==line,
                  Incident.status!='RESOLVED',Incident.merged_into_id.is_(None)).order_by(Incident.id)).all()
        recent = [i for i in candidates if abs(utc(i.started_at)-utc(started)) <= self.window]
        if name == 'ProductionLineBlocked':
            compatible=[]
            for incident in recent:
                names=session.scalars(select(AlertOccurrence.name).where(AlertOccurrence.incident_id==incident.id)).all()
                if names and all(jam_compatible(n,cv.payload if cv else {}) for n in names):
                    compatible.append(incident)
            primary = compatible[0] if compatible else self._new(session,kind,family,site,line,started,now)
            self._promote(session,primary,'PRODUCTION_JAM','PRODUCTION_JAM')
            for secondary in compatible[1:]:
                self._merge(session,primary,secondary,now)
            return primary
        if jam_compatible(name,cv.payload if cv else {}):
            jam=next((i for i in recent if i.type=='PRODUCTION_JAM'),None)
            if jam:
                return jam
        if name == 'MLAnomaly':
            process=next((i for i in recent if i.type in {'MOTOR_OVERHEAT','EXCESSIVE_VIBRATION','QUALITY_DEGRADATION'}),None)
            if process:
                return process
        if name == 'TelemetryStale':
            parent=next((i for i in recent if i.family=='plc-connectivity'),None)
            if parent:
                return parent
        same=next((i for i in candidates if i.family==family and
                   (i in recent or session.scalar(select(func.count()).select_from(AlertOccurrence).where(
                       AlertOccurrence.incident_id==i.id,AlertOccurrence.status=='firing')))),None)
        if same:
            # Independent endpoint probes override an earlier tentative network-path attribution.
            if kind in {'OPCUA_CONNECTIVITY','CAMERA_OUTAGE'}:
                self._promote(session,same,kind,family)
            return same
        # An ML symptom can arrive before its specific process alert.
        if kind in {'MOTOR_OVERHEAT','EXCESSIVE_VIBRATION','QUALITY_DEGRADATION'}:
            symptom=next((i for i in recent if i.type=='PROCESS_ANOMALY'),None)
            if symptom:
                self._promote(session,symptom,kind,family)
                return symptom
        return self._new(session,kind,family,site,line,started,now)

    def ingest(self, alerts):
        now=self.clock()
        accepted=duplicates=0
        with self.transaction() as session:
            # Anchors first for mixed groups; late anchors also merge earlier symptoms.
            for alert in sorted(alerts,key=lambda a:a['labels'].get('alertname')!='ProductionLineBlocked'):
                labels=alert['labels']
                name=labels.get('alertname','unknown')
                site,line=labels.get('site','local'),labels.get('line','line1')
                started=utc(alert['startsAt'])
                ended=utc(alert['endsAt']) if alert.get('endsAt') and alert['status']=='resolved' else None
                fingerprint=alert.get('fingerprint') or digest(labels)
                key=digest([fingerprint,stamp(started),alert['status'],alert.get('annotations',{}),stamp(ended)])
                if session.scalar(select(IncidentEvent.id).where(IncidentEvent.dedupe_key==key)):
                    duplicates+=1
                    continue
                occurrence=session.scalar(select(AlertOccurrence).where(AlertOccurrence.fingerprint==fingerprint,
                                                   AlertOccurrence.starts_at==started))
                if occurrence:
                    incident=session.get(Incident,occurrence.incident_id)
                    occurrence.last_received_at=now
                    if occurrence.status=='resolved' and alert['status']=='firing':
                        self.event(session,incident,'Alertmanager','LATE_NOTIFICATION_IGNORED',
                            f'Late firing notification ignored for recovered {name}.',alert_name=name,
                            dedupe_key=key,labels=labels,evidence={'annotations':alert.get('annotations',{})})
                        accepted+=1
                        continue
                else:
                    incident=self._choose(session,name,labels,site,line,started,now)
                    occurrence=AlertOccurrence(incident_id=incident.id,fingerprint=fingerprint,name=name,
                        status=alert['status'],starts_at=started,received_at=now,last_received_at=now,
                        labels=labels,annotations=alert.get('annotations',{}))
                    session.add(occurrence)
                occurrence.status,occurrence.ends_at=alert['status'],ended
                occurrence.annotations=alert.get('annotations',{})
                incident.started_at=min(utc(incident.started_at),started)
                incident.last_updated_at=now
                self.event(session,incident,'Alertmanager','ALERT_'+alert['status'].upper(),
                    f"{name} {alert['status']}.",alert_name=name,status=alert['status'],labels=labels,
                    evidence={'starts_at':stamp(started),'ends_at':stamp(ended),'annotations':occurrence.annotations},
                    dedupe_key=key)
                session.flush()
                firing=session.scalar(select(func.count()).select_from(AlertOccurrence).where(
                    AlertOccurrence.incident_id==incident.id,AlertOccurrence.status=='firing'))
                if firing:
                    incident.quiet_since=None
                elif incident.quiet_since is None and incident.status!='RESOLVED':
                    incident.quiet_since=now
                    self.event(session,incident,'correlation','SIGNALS_RECOVERED','All correlated alert occurrences have recovered; quiet period started.')
                accepted+=1
        return {'accepted':accepted,'duplicates':duplicates}

    def record_signal(self, source, site, line, payload, timestamp=None):
        now=self.clock()
        json.dumps(payload,allow_nan=False)
        with self.transaction() as session:
            row=session.scalar(select(Signal).where(Signal.source==source,Signal.site==site,Signal.line==line))
            if row and elapsed(now,row.received_at) < self.signal_interval:
                return False
            observed=utc(timestamp) if timestamp else now
            if observed > now+timedelta(seconds=60) or elapsed(now,observed)>self.signal_max_age:
                return False
            if row is None:
                row=Signal(source=source,site=site,line=line)
                session.add(row)
            row.timestamp,row.received_at,row.payload=observed,now,payload
            incidents=session.scalars(select(Incident).where(Incident.site==site,Incident.line==line,
                        Incident.status!='RESOLVED',Incident.merged_into_id.is_(None))).all()
            for incident in incidents:
                self._evidence(session,incident,row)
            return True

    def _detail(self, session, incident):
        return {'incident':incident_dict(incident,self.clock()),
                'alerts':[alert_dict(a) for a in session.scalars(select(AlertOccurrence).where(
                    AlertOccurrence.incident_id==incident.id).order_by(AlertOccurrence.starts_at,AlertOccurrence.id))],
                'timeline':[event_dict(e) for e in session.scalars(select(IncidentEvent).where(
                    IncidentEvent.incident_id==incident.id).order_by(IncidentEvent.timestamp,IncidentEvent.id))],
                'evidence':[evidence_dict(e) for e in session.scalars(select(Evidence).where(
                    Evidence.incident_id==incident.id).order_by(Evidence.received_at,Evidence.id))]}

    def detail(self, incident_id):
        with self.sessions() as session:
            incident=session.get(Incident,incident_id)
            if not incident:
                raise NotFound('Incident not found')
            return self._detail(session,incident)

    def _resolve(self, session, incident, summary, now, actor):
        incident.status,incident.resolved_at,incident.last_updated_at='RESOLVED',now,now
        incident.mttr_seconds=elapsed(now,incident.detected_at)
        incident.resolution_summary=summary
        self.event(session,incident,actor,'RESOLVED',summary,status='RESOLVED')
        self.event(session,incident,'reports','REPORT_GENERATED','Final report generated from persisted alerts, evidence and lifecycle events.')
        session.flush()
        data=self._detail(session,incident)
        data.update(final=True,generated_at=stamp(now),guidance='DEMONSTRATION / RUNBOOK GUIDANCE; follow approved site safety procedures.')
        session.add(Report(incident_id=incident.id,generated_at=now,data=data,markdown=markdown_report(data)))

    def transition(self, incident_id, action, note=''):
        mapping={'acknowledge':('ACKNOWLEDGED','acknowledged_at'),
                 'investigate':('INVESTIGATING','investigating_at'),
                 'mitigate':('MITIGATED','mitigated_at'),'resolve':('RESOLVED','resolved_at')}
        allowed={'FIRING':{'acknowledge','resolve'},'ACKNOWLEDGED':{'investigate','mitigate','resolve'},
                 'INVESTIGATING':{'mitigate','resolve'},'MITIGATED':{'resolve'},'RESOLVED':set()}
        if action not in mapping:
            raise Conflict('Unknown incident action')
        now=self.clock()
        with self.transaction() as session:
            incident=session.get(Incident,incident_id)
            if not incident:
                raise NotFound('Incident not found')
            if incident.merged_into_id:
                raise Conflict(f'Incident correlated into INC-{incident.merged_into_id:06d}')
            target,field=mapping[action]
            if incident.status==target:
                return incident_dict(incident,now)
            if action not in allowed[incident.status]:
                raise Conflict(f'Cannot {action} an incident in {incident.status}')
            if action=='resolve':
                if session.scalar(select(func.count()).select_from(AlertOccurrence).where(
                        AlertOccurrence.incident_id==incident.id,AlertOccurrence.status=='firing')):
                    raise Conflict('Resolve requires all underlying alerts to recover; mitigation does not clear alerts')
                self._resolve(session,incident,note or incident.resolution_summary or 'Manually resolved after all source alerts recovered.',now,'operator')
            else:
                incident.status,incident.last_updated_at=target,now
                setattr(incident,field,now)
                if action=='acknowledge':
                    incident.mtta_seconds=elapsed(now,incident.detected_at)
                self.event(session,incident,'operator',target,note or target.replace('_',' ').capitalize()+'.',status=target)
            return incident_dict(incident,now)

    def edit(self, incident_id, fields):
        editable={'title','root_cause','impact','remediation_actions','resolution_summary'}
        if not fields or not set(fields)<=editable:
            raise Conflict('No editable incident fields supplied')
        with self.transaction() as session:
            incident=session.get(Incident,incident_id)
            if not incident:
                raise NotFound('Incident not found')
            if incident.status=='RESOLVED' or incident.merged_into_id:
                raise Conflict('Closed incident reports are immutable')
            for key,value in fields.items():
                setattr(incident,key,value)
            incident.last_updated_at=self.clock()
            self.event(session,incident,'operator','NOTES_UPDATED','Operator investigation notes updated.',evidence=fields)
            return incident_dict(incident,self.clock())

    def recover(self):
        if self.quiet_seconds < 0:
            return 0
        now=self.clock()
        count=0
        with self.transaction() as session:
            rows=session.scalars(select(Incident).where(Incident.status!='RESOLVED',Incident.merged_into_id.is_(None),
                                Incident.quiet_since<=now-timedelta(seconds=self.quiet_seconds))).all()
            for incident in rows:
                active=session.scalar(select(func.count()).select_from(AlertOccurrence).where(
                    AlertOccurrence.incident_id==incident.id,AlertOccurrence.status=='firing'))
                if not active:
                    self._resolve(session,incident,
                        incident.resolution_summary or f'All correlated source alerts recovered; automatically resolved after {self.quiet_seconds}s quiet.',now,'policy')
                    count+=1
        return count

    def report(self, incident_id, markdown=False):
        with self.sessions() as session:
            if not session.get(Incident,incident_id):
                raise NotFound('Incident not found')
            report=session.scalar(select(Report).where(Report.incident_id==incident_id))
            if not report:
                raise Conflict('Final report is available after resolution')
            return report.markdown if markdown else report.data

    def list(self, *, status=None, severity=None, kind=None, line=None, site=None,
             since=None, until=None, active=None, limit=50, offset=0):
        filters=[Incident.merged_into_id.is_(None)]
        for column,value in [(Incident.status,status),(Incident.severity,severity),(Incident.type,kind),
                             (Incident.line,line),(Incident.site,site)]:
            if value:
                filters.append(column==value)
        if active is not None:
            filters.append(Incident.status!='RESOLVED' if active else Incident.status=='RESOLVED')
        if since:
            filters.append(Incident.started_at>=utc(since))
        if until:
            filters.append(Incident.started_at<=utc(until))
        with self.sessions() as session:
            count=session.scalar(select(func.count()).select_from(Incident).where(*filters))
            rows=session.scalars(select(Incident).where(*filters).order_by(Incident.created_at.desc(),Incident.id.desc()).limit(limit).offset(offset))
            return {'incidents':[incident_dict(row,self.clock()) for row in rows],'total':count,'limit':limit,'offset':offset}

    def legacy_alerts(self):
        with self.sessions() as session:
            rows=session.scalars(select(AlertOccurrence).order_by(AlertOccurrence.last_received_at.desc()).limit(1000)).all()
            # Preserve the legacy contract: latest occurrence for each alert identity.
            latest={}
            for row in rows:
                latest.setdefault(row.fingerprint,alert_dict(row))
            return {'alerts':list(latest.values()),'storage':'PostgreSQL; persistent alert occurrences and incident history'}

    def stats(self):
        with self.sessions() as session:
            scope=Incident.merged_into_id.is_(None)
            total=session.scalar(select(func.count()).select_from(Incident).where(scope))
            resolved=session.scalar(select(func.count()).select_from(Incident).where(scope,Incident.status=='RESOLVED'))
            critical=session.scalar(select(func.count()).select_from(Incident).where(scope,Incident.status!='RESOLVED',Incident.severity=='CRITICAL'))
            mtta,mttr=session.execute(select(func.avg(Incident.mtta_seconds),func.avg(Incident.mttr_seconds)).where(scope)).one()
            groups={name:dict(session.execute(select(column,func.count()).where(scope).group_by(column)).all())
                    for name,column in [('by_severity',Incident.severity),('by_type',Incident.type),('by_status',Incident.status)]}
            firing=session.scalar(select(func.count()).select_from(AlertOccurrence).where(AlertOccurrence.status=='firing'))
            acknowledged=session.scalar(select(func.count()).select_from(Incident).where(scope,Incident.acknowledged_at.is_not(None)))
            return {'total':total,'active':total-resolved,'resolved':resolved,'critical':critical,
                    'mtta_seconds':float(mtta) if mtta is not None else None,
                    'mttr_seconds':float(mttr) if mttr is not None else None,
                    'active_alerts':firing,'acknowledged':acknowledged,**groups}
