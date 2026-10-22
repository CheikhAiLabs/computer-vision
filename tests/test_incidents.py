"""Isolated incident tests. Synthetic alert fixtures are confined to test databases."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from prometheus_client import CollectorRegistry, generate_latest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from services.incident_receiver.models import SchemaVersion
from services.incident_receiver.metrics import Metrics
from services.incident_receiver.rules import RULES, classify
from services.incident_receiver.store import Store, Conflict


class Clock:
    def __init__(self):
        self.now=datetime(2026,1,1,12,tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now+=timedelta(seconds=seconds)


def alert(name='ProductionLineBlocked', *, status='firing', start=None, end=None, site='local', line='line1', **labels):
    start=start or datetime(2026,1,1,12,tzinfo=timezone.utc)
    return {'status':status,'startsAt':start,'endsAt':end,
            'labels':{'alertname':name,'site':site,'line':line,'severity':'warning',**labels},
            'annotations':{'summary':f'Test fixture for {name}'},'fingerprint':''}


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.store=Store('sqlite://',clock=self.clock)
        self.store.initialize()
        self.addCleanup(self.store.engine.dispose)

    def open(self, name='ProductionLineBlocked', **kwargs):
        self.store.ingest([alert(name,**kwargs)])
        return self.store.list()['incidents'][0]['id']

    def recover(self, name='ProductionLineBlocked', **kwargs):
        self.clock.advance(5)
        self.store.ingest([alert(name,status='resolved',end=self.clock(),**kwargs)])

    def test_creation_and_supported_severity(self):
        incident_id=self.open()
        row=self.store.detail(incident_id)['incident']
        self.assertEqual(row['number'],'INC-000001')
        self.assertEqual(row['type'],'PRODUCTION_JAM')
        self.assertEqual(row['severity'],'HIGH')
        self.assertEqual(row['status'],'FIRING')
        self.assertTrue(row['remediation'])
        self.assertIsNone(row['mtta_seconds'])
        self.assertEqual([e['event_type'] for e in self.store.detail(incident_id)['timeline']][:2],['DETECTED','FIRING'])

    def test_duplicate_firing_and_resolved_notifications(self):
        original=alert()
        self.store.ingest([original])
        before=self.store.detail(1)
        repeat={**original,'endsAt':self.clock()+timedelta(minutes=5)}
        self.assertEqual(self.store.ingest([repeat]),{'accepted':0,'duplicates':1})
        self.assertEqual(len(self.store.detail(1)['timeline']),len(before['timeline']))
        self.recover()
        recovered=alert(status='resolved',end=self.clock())
        self.assertEqual(self.store.ingest([recovered])['duplicates'],1)
        self.assertEqual(self.store.stats()['total'],1)

    def test_jam_batch_is_one_incident(self):
        names=['MLAnomaly','QualityDegradation','ExcessiveVibration','ComputerVisionAnomaly','ProductionLineBlocked']
        self.store.ingest([alert(name) for name in names])
        self.assertEqual(self.store.stats()['total'],1)
        self.assertEqual({a['name'] for a in self.store.detail(1)['alerts']},set(names))

    def test_visual_dwell_and_stall_share_incident_then_join_jam(self):
        self.open('ProductExcessiveDwell')
        self.clock.advance(5)
        self.open('ProductStalled')
        self.assertEqual(self.store.stats()['total'],1)
        self.assertEqual(self.store.detail(1)['incident']['type'],'PRODUCT_STALLED')
        self.open('ProductionLineBlocked')
        self.assertEqual(self.store.stats()['total'],1)
        self.assertEqual(self.store.detail(1)['incident']['type'],'PRODUCTION_JAM')

    def test_missing_exit_and_count_difference_share_flow_incident(self):
        self.open('ProductMissingExit')
        self.open('ProductionCountMismatch')
        self.assertEqual(self.store.stats()['total'],1)
        self.assertEqual(self.store.detail(1)['incident']['type'],'COUNT_MISMATCH')

    def test_late_jam_anchor_merges_symptoms_without_losing_events(self):
        self.open('ComputerVisionAnomaly')
        self.open('ExcessiveVibration')
        self.assertEqual(self.store.stats()['total'],2)
        self.clock.advance(8)
        self.open('ProductionLineBlocked')
        self.assertEqual(self.store.stats()['total'],1)
        incident=self.store.list()['incidents'][0]
        data=self.store.detail(incident['id'])
        self.assertEqual(incident['type'],'PRODUCTION_JAM')
        self.assertEqual(len(data['alerts']),3)
        self.assertTrue(any(e['event_type']=='INCIDENT_CORRELATED' for e in data['timeline']))

    def test_late_merge_preserves_operator_progress_and_notes(self):
        first=self.open('ComputerVisionAnomaly')
        second=self.open('ExcessiveVibration')
        self.store.transition(second,'acknowledge')
        self.store.transition(second,'investigate')
        self.store.edit(second,{'root_cause':'Mechanical vibration under investigation'})
        self.open('ProductionLineBlocked')
        primary=self.store.detail(first)['incident']
        self.assertEqual(primary['status'],'INVESTIGATING')
        self.assertEqual(primary['root_cause'],'Mechanical vibration under investigation')
        self.assertEqual(self.store.detail(second)['incident']['merged_into_id'],first)

    def test_scope_and_correlation_window_prevent_unrelated_merges(self):
        self.open()
        self.open(line='line2')
        self.open(site='other')
        self.assertEqual(self.store.stats()['total'],3)
        self.clock.advance(200)
        self.open('QualityDegradation',start=self.clock())
        self.assertEqual(self.store.stats()['total'],4)

    def test_dark_camera_does_not_join_jam(self):
        self.store.record_signal('OpenCV','local','line1',{'anomaly':True,'reasons':['dark-camera']})
        self.open()
        self.open('ComputerVisionAnomaly')
        self.assertEqual(self.store.stats()['total'],2)

    def test_stale_evidence_is_not_attached(self):
        self.store.record_signal('PLC','local','line1',{'values':{'BlockedSensor':True}})
        self.clock.advance(40)
        incident_id=self.open()
        self.assertEqual(self.store.detail(incident_id)['evidence'],[])

    def test_ml_symptom_promoted_by_specific_process_alert(self):
        self.open('MLAnomaly')
        self.open('MotorOverheating')
        self.assertEqual(self.store.stats()['total'],1)
        self.assertEqual(self.store.detail(1)['incident']['type'],'MOTOR_OVERHEAT')

    def test_real_monitoring_facts_determine_network_attribution(self):
        healthy={'samples':[{'labels':{'__name__':'probe_success','instance':'opcua-sim:4840'},'value':1}]}
        self.store.record_signal('Monitoring','local','line1',healthy)
        self.open('OPCUAConnectionLost')
        self.assertEqual(self.store.detail(1)['incident']['type'],'OT_NETWORK_CONNECTIVITY')
        kind,_=classify('OPCUAConnectionLost',{}, {'samples':[]})
        self.assertEqual(kind,'OPCUA_CONNECTIVITY')
        _,family=classify('ExporterDown',{'job':'custom','instance':'x'*4000},{})
        self.assertLessEqual(len(family),80)

    def test_source_exporter_outage_correlates_with_endpoint_and_path_alerts(self):
        self.store.ingest([alert('ExporterDown',job='camera-sim',instance='camera-sim:9105'),
            alert('EndpointUnavailable',instance='http://camera-sim:8082/healthz'),alert('CameraStreamDown')])
        self.assertEqual(self.store.stats()['total'],1)
        self.assertEqual(self.store.detail(1)['incident']['type'],'CAMERA_OUTAGE')
        self.assertEqual(len(self.store.detail(1)['alerts']),3)
        self.store.ingest([alert('ExporterDown',job='opcua-sim',instance='opcua-sim:9101'),
            alert('EndpointUnavailable',instance='opcua-sim:4840'),alert('OPCUAConnectionLost')])
        self.assertEqual(self.store.stats()['total'],2)
        self.assertEqual(self.store.detail(2)['incident']['type'],'OPCUA_CONNECTIVITY')
        self.assertEqual(len(self.store.detail(2)['alerts']),3)

    def test_all_categories_have_demonstration_guidance(self):
        for kind,rule in RULES.items():
            self.assertTrue(rule.steps,kind)
            self.assertIn(rule.severity,('INFO','WARNING','HIGH','CRITICAL'))
        self.open('PersonInRestrictedZone')
        self.assertEqual(self.store.detail(1)['incident']['severity'],'CRITICAL')

    def test_lifecycle_timestamps_mtta_and_mttr(self):
        incident_id=self.open()
        with self.assertRaises(Conflict):
            self.store.transition(incident_id,'investigate')
        with self.assertRaises(Conflict):
            self.store.transition(incident_id,'resolve')
        self.clock.advance(10)
        self.store.transition(incident_id,'acknowledge','Reviewed actual evidence')
        self.assertEqual(self.store.detail(incident_id)['incident']['mtta_seconds'],10)
        self.clock.advance(10)
        self.store.transition(incident_id,'investigate')
        self.clock.advance(10)
        self.store.transition(incident_id,'mitigate')
        self.recover()
        self.clock.advance(5)
        self.store.transition(incident_id,'resolve','Conveyor recovered')
        row=self.store.detail(incident_id)['incident']
        self.assertEqual(row['mttr_seconds'],40)
        self.assertEqual(row['status'],'RESOLVED')
        self.assertTrue(all(row[k] for k in ['acknowledged_at','investigating_at','mitigated_at','resolved_at']))

    def test_repeated_operator_action_is_idempotent(self):
        incident_id=self.open()
        self.store.transition(incident_id,'acknowledge')
        before=len(self.store.detail(incident_id)['timeline'])
        self.clock.advance(2)
        self.store.transition(incident_id,'acknowledge')
        self.assertEqual(len(self.store.detail(incident_id)['timeline']),before)
        self.assertEqual(self.store.detail(incident_id)['incident']['mtta_seconds'],0)

    def test_quiet_period_not_immediate_and_requires_all_alerts_recovered(self):
        self.store.ingest([alert(),alert('MLAnomaly')])
        self.recover()
        self.clock.advance(35)
        self.assertEqual(self.store.recover(),0)
        self.recover('MLAnomaly')
        self.clock.advance(29)
        self.assertEqual(self.store.recover(),0)
        self.clock.advance(1)
        self.assertEqual(self.store.recover(),1)
        self.assertEqual(self.store.stats()['resolved'],1)
        self.assertIsNone(self.store.detail(1)['incident']['mtta_seconds'])

    def test_manual_policy_retains_recovered_history(self):
        self.store.quiet_seconds=-1
        self.open()
        self.recover()
        self.clock.advance(300)
        self.assertEqual(self.store.recover(),0)
        self.assertEqual(self.store.stats()['active'],1)
        self.store.transition(1,'resolve')
        self.assertEqual(self.store.stats()['resolved'],1)

    def test_late_firing_does_not_reopen_and_new_epoch_creates_new_incident(self):
        original=alert()
        self.store.ingest([original])
        self.recover()
        self.store.transition(1,'resolve')
        self.store.ingest([original])
        self.assertEqual(self.store.stats()['active'],0)
        self.clock.advance(10)
        self.store.ingest([alert(start=self.clock())])
        self.assertEqual(self.store.stats()['total'],2)
        self.assertEqual(self.store.stats()['active'],1)

    def test_resolved_before_firing_is_retained_without_invented_firing_alert(self):
        self.store.ingest([alert(status='resolved',end=self.clock())])
        self.store.ingest([alert()])
        data=self.store.detail(1)
        self.assertEqual(data['alerts'][0]['status'],'resolved')
        self.assertFalse(any(e['event_type']=='ALERT_FIRING' for e in data['timeline']))

    def test_report_contains_persisted_evidence_and_operator_notes(self):
        self.store.record_signal('PLC','local','line1',{'values':{'BlockedSensor':True,'ConveyorSpeed':.02}})
        self.open()
        self.store.edit(1,{'root_cause':'Obstruction confirmed','impact':'Flow stopped','remediation_actions':'Inspected conveyor'})
        self.recover()
        self.store.transition(1,'resolve','Recovered after inspection')
        report=self.store.report(1)
        self.assertEqual(report['incident']['root_cause'],'Obstruction confirmed')
        self.assertEqual(report['evidence'][0]['payload']['values']['ConveyorSpeed'],.02)
        self.assertTrue(report['final'])
        self.assertIn('REPORT_GENERATED',[e['event_type'] for e in report['timeline']])
        markdown=self.store.report(1,markdown=True)
        self.assertIn('INC-000001',markdown)
        self.assertIn('Obstruction confirmed',markdown)
        with self.assertRaises(Conflict):
            self.store.edit(1,{'root_cause':'Changed after closing'})
        self.clock.advance(30)
        self.assertEqual(self.store.report(1),report)

    def test_metrics_and_statistics_are_database_derived(self):
        registry=CollectorRegistry()
        Metrics(self.store,registry)
        self.open()
        self.clock.advance(12)
        self.store.transition(1,'acknowledge')
        self.recover()
        self.store.transition(1,'resolve')
        data=generate_latest(registry).decode()
        self.assertIn('incident_total 1.0',data)
        self.assertIn('incident_resolved_total 1.0',data)
        self.assertIn('incident_mtta_seconds 12.0',data)
        self.assertNotIn('INC-000001',data)
        self.assertEqual(self.store.stats()['by_type'],{'PRODUCTION_JAM':1})

    def test_list_filters_and_pagination(self):
        self.open()
        self.open('PersonInRestrictedZone',line='line2')
        result=self.store.list(line='line2',severity='CRITICAL')
        self.assertEqual(result['total'],1)
        self.assertEqual(self.store.list(limit=1)['total'],2)
        self.assertEqual(self.store.list(since=self.clock()+timedelta(seconds=1))['total'],0)

    def test_migration_is_versioned_and_idempotent(self):
        self.store.initialize()
        with self.store.sessions() as session:
            self.assertEqual(session.scalars(select(SchemaVersion.version)).all(),[1])
        self.store.initialized=False
        with self.assertRaises(SQLAlchemyError):
            self.store.ingest([alert()])

    def test_file_database_survives_store_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            url='sqlite:///'+str(Path(folder)/'isolated.db')
            first=Store(url,clock=self.clock)
            first.initialize()
            first.ingest([alert()])
            first.engine.dispose()
            second=Store(url,clock=self.clock)
            try:
                second.initialize()
                self.assertEqual(second.detail(1)['incident']['number'],'INC-000001')
            finally:
                second.engine.dispose()


class IncidentAPITests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from services.incident_receiver.main import create_app
        self.clock=Clock()
        self.store=Store('sqlite://',clock=self.clock)
        self.client=TestClient(create_app(self.store,runtime=False))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)

    def post_alert(self):
        fixture=alert()
        fixture['startsAt']=fixture['startsAt'].isoformat()
        return self.client.post('/webhook',json={'status':'firing','alerts':[fixture]})

    def test_api_and_legacy_contract(self):
        self.assertEqual(self.client.get('/healthz').status_code,200)
        self.assertEqual(self.client.get('/readyz').status_code,200)
        self.assertEqual(self.post_alert().json()['accepted'],1)
        self.assertEqual(self.post_alert().json()['duplicates'],1)
        self.assertEqual(self.client.get('/alerts').json()['alerts'][0]['alertname'],'ProductionLineBlocked')
        self.assertEqual(self.client.get('/api/incidents').json()['total'],1)
        self.assertEqual(self.client.post('/api/incidents/1/acknowledge',json={'note':'Reviewing'}).status_code,200)
        self.assertEqual(self.client.post('/api/incidents/1/resolve').status_code,409)
        self.assertEqual(self.client.get('/api/incidents/1/report').status_code,409)
        self.assertEqual(self.client.get('/api/incidents/999').status_code,404)
        self.assertEqual(self.client.get('/api/incidents?status=invalid').status_code,422)
        fixture=alert('x'*201)
        fixture['startsAt']=fixture['startsAt'].isoformat()
        self.assertEqual(self.client.post('/webhook',json={'status':'firing','alerts':[fixture]}).status_code,422)
        self.assertEqual(self.client.patch('/api/incidents/1',json={'status':'RESOLVED'}).status_code,422)

    def test_portal_pages_and_escaping(self):
        self.post_alert()
        self.client.patch('/api/incidents/1',json={'title':'<script>alert(1)</script>'})
        for path in ['/','/incidents','/history','/statistics','/incidents/1','/docs','/static/portal.css','/static/portal.js','/static/openapi.js',
                     '/static/vendor/swagger-ui/swagger-ui-bundle.js','/static/vendor/swagger-ui/swagger-ui.css']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
        response=self.client.get('/incidents/1')
        self.assertIn('&lt;script&gt;',response.text)
        self.assertNotIn('<script>alert(1)</script>',response.text)
        self.assertIn('http://localhost:3000',response.text)
        docs=self.client.get('/docs').text
        self.assertIn('/static/vendor/swagger-ui/swagger-ui-bundle.js',docs)
        self.assertNotIn('https://cdn.',docs)
        self.assertEqual(self.client.get('/history?severity=HIGH&line=line1').status_code,200)

    def test_final_report_api_formats_and_saved_notes(self):
        self.post_alert()
        self.client.patch('/api/incidents/1',json={'root_cause':'Reviewed source evidence'})
        self.clock.advance(10)
        recovered=alert(status='resolved',end=self.clock())
        recovered['startsAt']=recovered['startsAt'].isoformat()
        recovered['endsAt']=recovered['endsAt'].isoformat()
        self.assertEqual(self.client.post('/webhook',json={'status':'resolved','alerts':[recovered]}).status_code,200)
        self.assertEqual(self.client.post('/api/incidents/1/resolve',json={'note':'Source recovered'}).status_code,200)
        report=self.client.get('/api/incidents/1/report')
        self.assertTrue(report.json()['final'])
        self.assertEqual(report.json()['incident']['root_cause'],'Reviewed source evidence')
        markdown=self.client.get('/api/incidents/1/report.md')
        self.assertIn('text/markdown',markdown.headers['content-type'])
        self.assertIn('INC-000001',markdown.headers['content-disposition'])

    def test_database_outage_returns_retryable_status(self):
        with patch.object(self.store,'ready',side_effect=OperationalError('test',{},Exception('offline'))):
            self.assertEqual(self.client.get('/readyz').status_code,503)
            self.assertEqual(self.client.get('/healthz').status_code,200)
        with patch.object(self.store,'ingest',side_effect=OperationalError('test',{},Exception('offline'))):
            self.assertEqual(self.post_alert().status_code,503)


class EvidenceEnrichmentTests(unittest.TestCase):
    def test_mqtt_only_enriches_and_invalid_payloads_are_contained(self):
        from types import SimpleNamespace
        from services.incident_receiver.enrichment import Enrichment
        store=Store('sqlite://')
        store.initialize()
        self.addCleanup(store.engine.dispose)
        metrics=Metrics(store,CollectorRegistry())
        collector=Enrichment(store,metrics)
        collector.received(None,None,SimpleNamespace(topic='factory/line1/telemetry',payload=b'{"values":{"BlockedSensor":true}}'))
        self.assertEqual(len(collector.pending),1)
        for work in collector.pending.values():
            store.record_signal(*work)
        self.assertEqual(store.stats()['total'],0)
        collector.received(None,None,SimpleNamespace(topic='factory/line1/cv/anomaly',payload=b'[]'))
        collector.received(None,None,SimpleNamespace(topic='factory/line1/cv/anomaly',payload=b'{"anomaly":NaN}'))
        self.assertEqual(metrics.invalid._value.get(),2)


@unittest.skipUnless(os.getenv('INCIDENT_TEST_POSTGRES')=='true','optional isolated PostgreSQL schema test')
class PostgreSQLPersistenceTests(unittest.TestCase):
    def test_actual_postgres_transactional_storage_and_restart(self):
        from sqlalchemy.engine import URL
        from uuid import uuid4
        admin=Store()
        schema='incident_test_'+uuid4().hex
        url=admin.engine.url.update_query_dict({'options':'-csearch_path='+schema})
        with admin.engine.begin() as connection:
            connection.execute(text('CREATE SCHEMA '+schema))
        first=Store(url)
        second=None
        try:
            first.initialize()
            first.ingest([alert()])
            first.engine.dispose()
            second=Store(url)
            second.initialize()
            self.assertEqual(second.stats()['total'],1)
            self.assertEqual(second.detail(1)['incident']['number'],'INC-000001')
            from concurrent.futures import ThreadPoolExecutor
            extra=Store(url)
            extra.initialize()
            try:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(lambda index:(second if index%2 else extra).ingest([alert()]),range(8)))
                self.assertEqual(second.stats()['total'],1)
                self.assertEqual(len(second.detail(1)['alerts']),1)
            finally:
                extra.engine.dispose()
        finally:
            first.engine.dispose()
            if second:
                second.engine.dispose()
            with admin.engine.begin() as connection:
                connection.execute(text('DROP SCHEMA '+schema+' CASCADE'))
            admin.engine.dispose()


if __name__=='__main__':
    unittest.main()
