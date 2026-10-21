"""Database-derived statistics survive restarts; no incident identities as labels."""
from prometheus_client import Counter
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy.exc import SQLAlchemyError
from services.incident_receiver.rules import RULES, SEVERITIES, STATUSES


class Metrics:
    def __init__(self, store, registry):
        self.store=store
        self.notifications=Counter('incident_notifications','Successful Alertmanager webhook deliveries',['status'],registry=registry)
        self.dropped=Counter('incident_evidence_dropped','Evidence samples rejected by the bounded latest-sample buffer',registry=registry)
        self.invalid=Counter('incident_evidence_invalid','Invalid evidence payloads rejected',registry=registry)
        registry.register(self)

    def describe(self):
        # No database calls while registering the collector.
        for name in ('incident_database_ready','incident_total','incident_active_total','incident_resolved_total',
                     'incident_active_alerts','incident_mtta_seconds','incident_mttr_seconds','incident_acknowledged_total'):
            yield GaugeMetricFamily(name,name)
        yield GaugeMetricFamily('incident_by_severity','Stored incidents by fixed severity',labels=['severity'])
        yield GaugeMetricFamily('incident_by_type','Stored incidents by fixed type',labels=['type'])
        yield GaugeMetricFamily('incident_by_status','Stored incidents by fixed workflow status',labels=['status'])

    def collect(self):
        ready=False
        stats=None
        try:
            ready=self.store.ready()
            if ready:
                stats=self.store.stats()
        except SQLAlchemyError:
            ready=False
        yield GaugeMetricFamily('incident_database_ready','Incident database is reachable and initialized',value=int(ready))
        if not stats:
            return  # Do not turn unavailable history into fictitious zero counts.
        for name,key in [('incident_total','total'),('incident_active_total','active'),('incident_resolved_total','resolved'),
                         ('incident_active_alerts','active_alerts'),('incident_mtta_seconds','mtta_seconds'),
                         ('incident_mttr_seconds','mttr_seconds'),('incident_acknowledged_total','acknowledged')]:
            yield GaugeMetricFamily(name,'Database-derived '+key,value=stats[key] if stats[key] is not None else 0)
        for metric,key,label,values in [('incident_by_severity','by_severity','severity',SEVERITIES),
                                        ('incident_by_type','by_type','type',RULES),('incident_by_status','by_status','status',STATUSES)]:
            family=GaugeMetricFamily(metric,'Stored incidents by fixed '+label,labels=[label])
            for value in values:
                family.add_metric([value],stats[key].get(value,0))
            yield family
