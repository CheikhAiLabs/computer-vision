"""Bounded MQTT latest-sample enrichment and local Prometheus connectivity evidence."""
from datetime import datetime, timezone
import json
import logging
import os
import threading
import time
import httpx
from sqlalchemy.exc import SQLAlchemyError
from common.mqtt import start_client, close
from services.incident_receiver.models import utc, utcnow

LOG = logging.getLogger(__name__)
TOPICS = {'telemetry':'PLC','cv/anomaly':'OpenCV','cv/detections':'YOLO',
          'cv/safety':'Safety','ml/anomaly':'ML','vision/events':'VisionEvents',
          'vision/counts':'VisionCounts','vision/safety':'VisionSafety','vision/quality':'VisionQuality'}
MONITORING_QUERY = '{__name__=~"probe_success|up|bridge_opcua_connected|cv_stream_up|camera_publisher_up"}'


def source_timestamp(payload, now):
    raw=payload.get('source_timestamp',payload.get('timestamp'))
    if isinstance(raw,(int,float)):
        return datetime.fromtimestamp(raw,timezone.utc)
    if isinstance(raw,str):
        return utc(datetime.fromisoformat(raw.replace('Z','+00:00')))
    return now


class Enrichment:
    def __init__(self, store, metrics):
        self.store,self.metrics=store,metrics
        self.stop=threading.Event()
        self.lock=threading.Lock()
        self.pending={}
        self.client=None
        self.thread=None
        self.last_monitoring=0

    def received(self, client, userdata, message):
        try:
            parts=message.topic.split('/')
            if len(parts)<3 or parts[0]!='factory':
                return
            source=TOPICS.get('/'.join(parts[2:]))
            if source is None:
                return
            payload=json.loads(message.payload)
            if not isinstance(payload,dict):
                raise ValueError('MQTT evidence must be an object')
            json.dumps(payload,allow_nan=False)
            site,line=payload.get('site','local'),payload.get('line',parts[1])
            if not isinstance(site,str) or not isinstance(line,str) or not 1<=len(site)<=100 or not 1<=len(line)<=100 or line!=parts[1]:
                raise ValueError('Invalid MQTT signal scope')
            now=utcnow()
            work=(source,site,line,payload,source_timestamp(payload,now))
            key=(source,site,line)
            with self.lock:
                if key not in self.pending and len(self.pending)>=128:
                    self.metrics.dropped.inc()
                    return
                self.pending[key]=work
        except (ValueError,TypeError,KeyError,OverflowError):
            self.metrics.invalid.inc()
            LOG.warning('Invalid incident evidence message topic=%s',message.topic)

    def start(self):
        self.client=start_client('incident-evidence',self.received,'factory/+/#')
        self.thread=threading.Thread(target=self.run,name='incident-maintenance',daemon=True)
        self.thread.start()

    def monitoring(self):
        url=os.getenv('INCIDENT_PROMETHEUS_URL','http://prometheus:9090')
        response=httpx.get(url+'/api/v1/query',params={'query':MONITORING_QUERY},timeout=3)
        response.raise_for_status()
        result=response.json()
        if result.get('status')!='success':
            raise ValueError('Prometheus evidence query failed')
        groups={}
        for sample in result['data']['result']:
            labels=sample['metric']
            site,line=labels.get('site','local'),labels.get('line','line1')
            groups.setdefault((site,line),[]).append({'labels':labels,'value':float(sample['value'][1]),
                                                       'query_timestamp':float(sample['value'][0])})
        for (site,line),samples in groups.items():
            self.store.record_signal('Monitoring',site,line,{'samples':samples},utcnow())

    def run(self):
        while not self.stop.is_set():
            try:
                if not self.store.initialized:
                    self.store.initialize()
                    LOG.info('Incident database schema initialized')
                if time.monotonic()-self.last_monitoring>=5:
                    try:
                        self.monitoring()
                    except (httpx.HTTPError,ValueError,KeyError):
                        LOG.warning('Local monitoring evidence unavailable; webhook processing remains independent')
                    self.last_monitoring=time.monotonic()
                with self.lock:
                    batch=dict(self.pending)
                for key,work in batch.items():
                    self.store.record_signal(*work)
                    with self.lock:
                        if self.pending.get(key) is work:
                            del self.pending[key]
                self.store.recover()
            except (SQLAlchemyError,RuntimeError):
                LOG.exception('Incident database temporarily unavailable; webhooks return 503 for Alertmanager retry')
            self.stop.wait(2)

    def close(self):
        self.stop.set()
        if self.client:
            close(self.client)
        if self.thread:
            self.thread.join(timeout=5)
