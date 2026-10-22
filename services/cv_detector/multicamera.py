"""Three bounded acquisition queues, one CPU YOLO model and per-camera tracking."""
from collections import deque
import json
import logging
import os
import threading
import time
import cv2
import httpx
import numpy as np
from prometheus_client import Counter, Gauge, REGISTRY
from common.config import RTSP_URL
from common.line import CAMERAS
from services.cv_detector.yolo import Settings, Metrics, load_model, parse_results, messages, flag
from services.cv_detector.tracking import Tracker
from services.cv_detector.analytics import inspect_markers, Reconciliation, health_score
from services.cv_detector.vision import analyze
from services.cv_detector.annotated import label

LOG = logging.getLogger(__name__)


class Hub:
    def __init__(self, publish, registry=REGISTRY):
        self.publish = publish
        self.lock = threading.RLock()
        self.enabled = flag('ENABLE_YOLO')
        self.annotated = flag('ENABLE_ANNOTATED_STREAM')
        self.configuration_valid = True
        try:
            self.settings = Settings.from_env()
        except (ValueError,TypeError):
            LOG.exception('Invalid optional YOLO configuration; raw streams and OpenCV continue')
            self.settings = Settings()
            self.configuration_valid = False
        self.trackers = {c:Tracker(c,self.settings.zone,
            stalled_seconds=float(os.getenv('VISION_STALLED_SECONDS','5')),
            dwell_seconds=float(os.getenv('VISION_DWELL_SECONDS','13'))) for c in CAMERAS}
        self.cameras = {c:dict(camera=c,up=False,updated=0,processed=0,tracks=[],objects=0,
                              reasons=[],quality=[],anomalies=[],fps=0,inference_ms=None,tracking_ms=None,
                              dropped_frames=0,tracking_ready=False) for c in CAMERAS}
        self.jpeg, self.heatmaps, self.motion, self.gray = {}, {}, {}, {}
        self.frame_times = {c:deque(maxlen=30) for c in CAMERAS}
        self.frame_numbers = {c:0 for c in CAMERAS}
        self.quality_updated = {c:0 for c in CAMERAS}
        self.events = deque(maxlen=100)
        self.flow = deque(maxlen=300)
        self.plc, self.ml, self.monitoring = None, None, None
        self.scenario, self.scenario_updated = None, 0
        self.incidents, self.incidents_updated = [], 0
        self.ready = False
        self.stop = threading.Event()
        self.reconcile = Reconciliation(int(os.getenv('VISION_COUNT_TOLERANCE','3')),
            float(os.getenv('VISION_COUNT_HOLD_SECONDS','15')),
            float(os.getenv('VISION_MISSING_EXIT_SECONDS','45')))
        self.reconciled = dict(ready=False,difference=None,mismatch=False,in_process=None,missing_exit=False,epoch=0)
        self.score, self.components = health_score({})
        self.legacy = Metrics(self.enabled,registry)
        self.metrics = {}
        descriptions = {
          'camera_up':'Recent decoded raw camera frame', 'objects_detected':'Current confirmed image-inferred tracks',
          'tracking_ready':'Recent tracking update including empty results', 'effective_fps':'Decoded frames per second',
          'last_frame_timestamp_seconds':'Last decoded frame wall time',
          'last_processed_frame_timestamp_seconds':'Capture time of latest inferred frame',
          'inference_latency_seconds':'Last YOLO inference and parse duration',
          'tracking_latency_seconds':'Last tracking/quality update duration',
          'restricted_zone_violation':'Current tracked person overlaps restricted demonstration zone',
          'quality_failure':'OpenCV inspection marker orientation defect',
          'stalled_object_detected':'Stationary tracked product while PLC expects movement',
          'wrong_direction_detected':'Tracked product moving against normal flow',
          'excessive_dwell_detected':'Tracked product exceeds inspection dwell limit'}
        for name,description in descriptions.items():
            self.metrics[name] = Gauge('vision_'+name,description,['camera'],registry=registry)
            for c in CAMERAS:
                self.metrics[name].labels(c).set(0)
        self.dropped = Counter('vision_dropped_frames','Overwritten inference queue frames',['camera'],registry=registry)
        self.skipped = Counter('vision_skipped_frames','Frames intentionally skipped for CPU sampling',['camera'],registry=registry)
        for camera in CAMERAS:
            self.dropped.labels(camera).inc(0)
            self.skipped.labels(camera).inc(0)
        self.counts = {c:Counter('vision_products_'+word,'Forward counting-line crossings; resets only at CV process restart',registry=registry)
                       for c,word in [('entry','entered'),('exit','exited')]}
        self.global_metrics = {name:Gauge(name,description,registry=registry) for name,description in {
          'vision_products_in_process':'Unmatched entry crossings in current available observation session',
          'vision_product_flow_per_minute':'Exit crossings over trailing 60 seconds; warm-up is partial',
          'vision_plc_count_difference':'PLC and vision entry deltas since synchronized baseline; NaN when unavailable',
          'vision_count_reconciliation_ready':'Fresh telemetry and entry/exit inference available',
          'vision_count_mismatch':'Absolute count difference above tolerance for configured hold',
          'vision_missing_exit_detected':'Unmatched entry older than configured flow window',
          'vision_count_epoch':'Reconciliation baseline epoch, including PLC resets and stream loss',
          'factory_line_health_score':'Deterministic 0-100 health score; unknown components earn zero',
          'vision_line_health_score':'Alias of factory_line_health_score',
          'cv_stream_up':'Recent process camera frame', 'cv_anomaly_detected':'Process image or stream anomaly',
          'cv_last_frame_timestamp_seconds':'Last process camera frame time',
          'cv_annotated_enabled':'Annotated HTTP outputs configured on',
          **{'cv_'+n:n.replace('_',' ') for n in ('red_pixel_ratio','frame_brightness','laplacian_variance','center_to_border_brightness_ratio')}
        }.items()}
        self.global_metrics['cv_annotated_enabled'].set(self.annotated)

    def emit(self, topic, event):
        if topic!='counts':
            self.events.append(event)
        self.publish('factory/line1/vision/'+topic,event)

    def receive(self, client, userdata, message):
        try:
            payload = json.loads(message.payload)
            if not isinstance(payload,dict):
                return
            if message.topic=='factory/line1/telemetry':
                values=payload['values']
                if not isinstance(values,dict) or not isinstance(payload.get('timestamp'),(int,float)):
                    return
                with self.lock:
                    self.plc=payload
            elif message.topic=='factory/line1/ml/anomaly':
                with self.lock:
                    self.ml=payload
        except (ValueError,KeyError,TypeError):
            LOG.warning('Invalid analytics input topic=%s',message.topic)

    def frame(self,camera,frame,now):
        values,reasons=analyze(frame)
        with self.lock:
            state=self.cameras[camera]
            state.update(up=True,updated=now,reasons=reasons)
            times=self.frame_times[camera]
            times.append(now)
            self.frame_numbers[camera]+=1
            state['fps']=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0
            self.metrics['camera_up'].labels(camera).set(1)
            self.metrics['effective_fps'].labels(camera).set(state['fps'])
            self.metrics['last_frame_timestamp_seconds'].labels(camera).set(now)
            if camera=='process':
                for name,value in values.items():
                    self.global_metrics['cv_'+name].set(value)
                self.global_metrics['cv_stream_up'].set(1)
                self.global_metrics['cv_last_frame_timestamp_seconds'].set(now)
                self.global_metrics['cv_anomaly_detected'].set(bool(reasons))
            if now-self.quality_updated[camera]>=.5:
                _,defects=inspect_markers(frame)
                had_defects=bool(state['quality'])
                state['quality']=defects
                state['anomalies']=[a for a in state['anomalies'] if a!='visual_quality_failure']+(['visual_quality_failure'] if defects else [])
                self.quality_updated[camera]=now
                self.metrics['quality_failure'].labels(camera).set(bool(defects))
                if defects or had_defects:
                    self.emit('quality',dict(timestamp=now,source_timestamp=now,site='local',line='line1',
                        camera=camera,event='visual_quality_failure',active=bool(defects),defects=defects,method='OpenCV fiducial geometry'))
            if self.frame_numbers[camera]%3==0 or camera not in self.gray:
                gray=cv2.resize(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),(160,90))
                previous=self.gray.get(camera,gray)
                activity=cv2.absdiff(gray,previous).astype(np.float32)
                heat=self.motion.get(camera,np.zeros((90,160),np.float32))*.96+activity*.04
                self.motion[camera],self.gray[camera]=heat,gray
                colored=cv2.applyColorMap(np.clip(heat*12,0,255).astype(np.uint8),cv2.COLORMAP_TURBO)
                self.heatmaps[camera]=cv2.imencode('.jpg',cv2.resize(colored,(640,360)))[1].tobytes()
            if self.annotated:
                self.jpeg[camera]=(self.draw(frame,state,camera,now),now)
            if camera=='process' and (now-getattr(self,'last_cv_publish',0)>=5 or reasons!=getattr(self,'last_reasons',None)):
                self.publish('factory/line1/cv/anomaly',dict(timestamp=now,anomaly=bool(reasons),reasons=reasons,metrics=values))
                self.last_cv_publish,self.last_reasons=now,reasons

    def unavailable(self,camera):
        with self.lock:
            self.cameras[camera].update(up=False,tracks=[],objects=0,anomalies=[],quality=[],tracking_ready=False)
            self.trackers[camera].reset()
            self.jpeg.pop(camera,None)
            self.gray.pop(camera,None)
            for name in ('camera_up','objects_detected','tracking_ready','restricted_zone_violation','quality_failure',
                         'stalled_object_detected','wrong_direction_detected','excessive_dwell_detected','effective_fps'):
                self.metrics[name].labels(camera).set(0)
            if camera=='process':
                self.legacy.clear()
                self.global_metrics['cv_stream_up'].set(0)
                self.global_metrics['cv_anomaly_detected'].set(1)
                self.publish('factory/line1/cv/anomaly',dict(timestamp=time.time(),anomaly=True,reasons=['stream-unavailable']))

    def inferred(self,camera,frame,detections,timestamp,duration):
        started=time.perf_counter()
        packages,defects=inspect_markers(frame)
        # A known marker ROI and a YOLO box can refer to the same product.
        packages=[p for p in packages if not any(abs((p['bbox'][0]+p['bbox'][2]-d['bbox'][0]-d['bbox'][2])/2)<45
                    for d in detections if d['class']!='person')]
        with self.lock:
            now=time.time()
            plc=self.plc if self.plc and now-self.plc['timestamp']<8 else None
            moving=bool(plc and plc['values'].get('LineStatus')=='RUNNING' and plc['values'].get('ConveyorSpeed',0)>.1)
            tracks,events=self.trackers[camera].update(detections+packages,timestamp,moving)
            previous=self.cameras[camera]
            previous.update(processed=timestamp,tracks=tracks,objects=len(tracks),
                            tracking_ready=True,inference_ms=round(duration*1000,2),
                            tracking_ms=round((time.perf_counter()-started)*1000,2))
            states={state for track in tracks for state in track['states']}
            previous['anomalies']=sorted(states | ({'visual_quality_failure'} if previous['quality'] else set()))
            self.metrics['last_processed_frame_timestamp_seconds'].labels(camera).set(timestamp)
            self.metrics['inference_latency_seconds'].labels(camera).set(duration)
            self.metrics['tracking_latency_seconds'].labels(camera).set(previous['tracking_ms']/1000)
            self.metrics['objects_detected'].labels(camera).set(len(tracks))
            self.metrics['tracking_ready'].labels(camera).set(1)
            for metric,state in [('restricted_zone_violation','person_in_restricted_zone'),
                                 ('stalled_object_detected','object_stalled'),('wrong_direction_detected','wrong_direction'),
                                 ('excessive_dwell_detected','excessive_dwell')]:
                self.metrics[metric].labels(camera).set(state in states)
            for event in events:
                self.emit('safety' if event['event']=='person_in_restricted_zone' else 'events',event)
                if event['event']=='product_crossed' and camera in self.counts:
                    self.counts[camera].inc()
                    if camera=='exit':
                        self.flow.append(timestamp)
            if camera=='process':
                payload,safety=messages(detections,self.settings,640,360,now,timestamp)
                self.legacy.record(detections,safety,now,duration)
                self.publish('factory/line1/cv/detections',payload)
                for event in safety:
                    self.publish('factory/line1/cv/safety',event)

    def draw(self,frame,state,camera,now):
        image=frame.copy()
        a,b,c,d=self.settings.zone
        cv2.rectangle(image,(int(a*640),int(b*360)),(int(c*640),int(d*360)),(80,190,220),1)
        cv2.rectangle(image,(160,108),(499,274),(140,112,60),1)
        label(image,'RESTRICTED / DEMO',int(a*640),max(60,int(b*360)-4),(80,190,220))
        cv2.line(image,(320,110),(320,275),(210,200,60),2)
        label(image,'COUNT >',325,272,(210,200,60))
        if now-state['processed']<self.settings.ttl:
            for obj in state['tracks']:
                x1,y1,x2,y2=obj['bbox']
                color=(85,115,245) if obj['states'] else (170,225,60)
                cv2.rectangle(image,(x1,y1),(x2,y2),color,2)
                method='CV' if obj.get('method') else 'YOLO'
                label(image,f"{obj['class']} #{obj['track_id']} {obj['confidence']:.2f} {method}",x1,max(73,y1-5),color)
                cx,cy=(x1+x2)//2,(y1+y2)//2
                cv2.arrowedLine(image,(cx,cy),(int(cx+obj['velocity'][0]*.35),int(cy+obj['velocity'][1]*.35)),color,2)
                if obj['states']:
                    label(image,f"{obj['states'][0]} {obj['dwell_seconds']:.1f}s",x1,y2+13,color)
            for defect in state['quality']:
                x1,y1,x2,y2=defect['bbox']
                cv2.rectangle(image,(x1,y1),(x2,y2),(70,90,250),2)
                label(image,'ORIENTATION / OpenCV',x1,y1-4,(70,90,250))
        cv2.rectangle(image,(0,293),(640,314),(25,32,36),-1)
        status=', '.join(state['anomalies']+state['reasons']) or 'normal'
        label(image,f"{camera.upper()} | crossed {self.trackers[camera].count} | {status}",10,308,(220,235,240))
        return cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])[1].tobytes()

    def maintain(self):
        with self.lock:
            now=time.time()
            for camera,state in self.cameras.items():
                if now-state['updated']>3 and state['up']:
                    self.unavailable(camera)
                if now-state['processed']>self.settings.ttl:
                    state.update(tracks=[],objects=0,anomalies=['visual_quality_failure'] if state['quality'] else [],tracking_ready=False)
                    for name in ('objects_detected','tracking_ready','restricted_zone_violation',
                                 'stalled_object_detected','wrong_direction_detected','excessive_dwell_detected'):
                        self.metrics[name].labels(camera).set(0)
            if now-self.cameras['process']['processed']>self.settings.ttl:
                self.legacy.clear()
            fresh=bool(self.plc and 0<=now-self.plc['timestamp']<8)
            values=self.plc['values'] if fresh else {}
            self.reconciled=self.reconcile.update(values.get('BottleCount'),self.trackers['entry'].count,
                self.trackers['exit'].count,now,fresh and values.get('LineStatus')=='RUNNING'
                and values.get('ConveyorSpeed',0)>.1
                and all(self.cameras[c]['tracking_ready'] and not self.cameras[c]['reasons'] for c in ('entry','exit')))
            r=self.reconciled
            while self.flow and now-self.flow[0]>60:
                self.flow.popleft()
            for name,value in [('vision_count_reconciliation_ready',r['ready']),('vision_plc_count_difference',r['difference']),
                ('vision_count_mismatch',r['mismatch']),('vision_products_in_process',r['in_process']),
                ('vision_missing_exit_detected',r['missing_exit']),('vision_count_epoch',r['epoch']),
                ('vision_product_flow_per_minute',len(self.flow))]:
                self.global_metrics[name].set(float('nan') if value is None else value)
            monitoring=self.monitoring if self.monitoring and now-self.monitoring['timestamp']<15 else None
            network_samples=[s for s in monitoring['samples'] if s['name'] in {'probe_success','bridge_opcua_connected'}] if monitoring else []
            network=all(s['value']==1 for s in network_samples) if len(network_samples)>=8 else None
            ml=self.ml if self.ml and now-self.ml.get('timestamp',0)<15 else None
            allcams=all(s['up'] for s in self.cameras.values())
            self.score,self.components=health_score(dict(plc=fresh,
                conveyor=values.get('LineStatus')=='RUNNING' and values.get('ConveyorSpeed',0)>.1 if fresh else None,
                temperature=values.get('MotorTemperature',999)<=80 if fresh else None,
                vibration=values.get('Vibration',999)<=.5 if fresh else None,
                quality=values.get('QualityScore',0)>=.9 if fresh else None,
                opencv=all(not s['reasons'] and not s['anomalies'] for s in self.cameras.values()) and not r['mismatch'] and not r['missing_exit'] if allcams else None,
                yolo=self.ready and all(s['tracking_ready'] for s in self.cameras.values()),
                cameras=allcams,ml=not ml['anomaly'] if ml and 'anomaly' in ml else None,network=network))
            self.global_metrics['factory_line_health_score'].set(self.score)
            self.global_metrics['vision_line_health_score'].set(self.score)
            payload=dict(timestamp=now,site='local',line='line1',entered=self.trackers['entry'].count,
                         exited=self.trackers['exit'].count,plc_count=values.get('BottleCount'),
                         flow_per_minute=len(self.flow),**r)
            self.emit('counts',payload)

    def snapshot(self):
        with self.lock:
            now=time.time()
            fresh=bool(self.plc and now-self.plc['timestamp']<8)
            return json.loads(json.dumps(dict(timestamp=now,scenario=self.scenario if now-self.scenario_updated<10 else None,
                cameras=list(self.cameras.values()),plc=self.plc['values'] if fresh else None,
                plc_fresh=fresh,yolo=dict(enabled=self.enabled,ready=self.ready,model=os.path.basename(self.settings.model),
                    tracker='Class-gated constant-velocity global assignment',camera_local_ids=True),
                counts=dict(entered=self.trackers['entry'].count,exited=self.trackers['exit'].count,
                    flow_per_minute=len(self.flow),**self.reconciled),
                health=dict(score=self.score,components=self.components),
                incidents=self.incidents if now-self.incidents_updated<15 else None,
                events=list(self.events)[-30:]),allow_nan=False))


class SharedInference:
    def __init__(self,hub,loader=load_model):
        self.hub,self.loader=hub,loader
        self.condition=threading.Condition()
        self.pending={}
        self.generations={c:0 for c in CAMERAS}
        self.frames={c:0 for c in CAMERAS}
        self.thread=None

    def submit(self,camera,frame,timestamp):
        with self.condition:
            self.frames[camera]+=1
            if not self.hub.enabled or self.frames[camera]%self.hub.settings.every:
                self.hub.skipped.labels(camera).inc()
                return
            if camera in self.pending:
                self.hub.dropped.labels(camera).inc()
                with self.hub.lock:
                    self.hub.cameras[camera]['dropped_frames']+=1
            self.pending[camera]=(frame.copy(),timestamp,self.generations[camera])
            self.condition.notify()

    def invalidate(self,camera):
        with self.condition:
            self.generations[camera]+=1
            self.pending.pop(camera,None)
        self.hub.unavailable(camera)

    def start(self):
        if self.hub.enabled and self.hub.configuration_valid:
            self.thread=threading.Thread(target=self.run,name='shared-yolo-cpu',daemon=True)
            self.thread.start()

    def run(self):
        model=None
        while not self.hub.stop.is_set():
            try:
                if model is None:
                    model=self.loader(self.hub.settings)
                    self.hub.ready=True
                    self.hub.legacy.ready.set(1)
                with self.condition:
                    self.condition.wait_for(lambda:self.pending or self.hub.stop.is_set(),timeout=1)
                    if not self.pending:
                        continue
                    camera=min(self.pending,key=lambda c:self.pending[c][1])
                    frame,timestamp,generation=self.pending.pop(camera)
                if time.time()-timestamp>self.hub.settings.ttl:
                    continue
                started=time.perf_counter()
                results=model.predict(frame,device='cpu',conf=self.hub.settings.confidence,
                    imgsz=640,verbose=False,save=False,
                    classes=[i for i,n in model.names.items() if n in ('person','bottle','cup','backpack','suitcase','handbag')])
                detections=parse_results(results,640,360,self.hub.settings.confidence)
                duration=time.perf_counter()-started
                with self.condition:
                    if generation!=self.generations[camera] or time.time()-timestamp>self.hub.settings.ttl:
                        continue
                    self.hub.inferred(camera,frame,detections,timestamp,duration)
            except Exception:
                LOG.exception('Shared YOLO inference unavailable; raw streams and OpenCV continue')
                self.hub.ready=False
                self.hub.legacy.ready.set(0)
                for camera in CAMERAS:
                    with self.hub.lock:
                        self.hub.trackers[camera].reset()
                model=None
                self.hub.stop.wait(5)

    def close(self):
        with self.condition:
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=5)


def capture_camera(hub,inference,camera):
    url=RTSP_URL.rsplit('/',1)[0]+'/line1-'+camera
    while not hub.stop.is_set():
        capture=cv2.VideoCapture(url,cv2.CAP_FFMPEG,[cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,4000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,4000])
        try:
            while not hub.stop.is_set():
                ok,frame=capture.read()
                if not ok:
                    break
                now=time.time()
                hub.frame(camera,frame,now)
                inference.submit(camera,frame,now)
        except Exception:
            LOG.exception('Camera acquisition failed view=%s',camera)
        finally:
            capture.release()
            inference.invalidate(camera)
        hub.stop.wait(2)


def context_loop(hub):
    while not hub.stop.is_set():
        try:
            response=httpx.get('http://camera-sim:8082/state',timeout=2)
            response.raise_for_status()
            with hub.lock:
                hub.scenario=response.json()['scenario']
                hub.scenario_updated=time.time()
        except (httpx.HTTPError,ValueError,KeyError):
            pass
        try:
            response=httpx.get('http://prometheus:9090/api/v1/query',params={'query':'{__name__=~"probe_success|bridge_opcua_connected"}'},timeout=2)
            response.raise_for_status()
            samples=[dict(name=s['metric']['__name__'],value=float(s['value'][1]),labels=s['metric']) for s in response.json()['data']['result']]
            with hub.lock:
                hub.monitoring=dict(timestamp=time.time(),samples=samples)
        except (httpx.HTTPError,ValueError,KeyError):
            pass
        try:
            response=httpx.get('http://incident-receiver:8090/api/incidents',params={'active':'true','limit':20},timeout=2)
            response.raise_for_status()
            with hub.lock:
                hub.incidents=response.json()['incidents']
                hub.incidents_updated=time.time()
        except (httpx.HTTPError,ValueError,KeyError):
            pass
        hub.stop.wait(3)
