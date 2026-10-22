"""Real local multi-camera scenarios; no injected alerts, detections or incidents.

Run with the normal stack already built: python3 scripts/vision_integration_test.py
Leaves normal camera/PLC settings and starts a fresh comparison observation epoch.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def get(port,path,method='GET'):
    for attempt in range(30 if method=='POST' else 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(f'http://localhost:{port}{path}',method=method),timeout=8) as response:
                return json.load(response)
        except OSError:
            if method!='POST' or attempt==29:
                raise
            time.sleep(1)


def wait(label,check,timeout=100):
    end=time.monotonic()+timeout
    last=None
    while time.monotonic()<end:
        try:
            result=check()
            if result:
                print('PASS '+label,flush=True)
                return result
        except (OSError,ValueError,KeyError,AssertionError) as exc:
            last=str(exc)
        time.sleep(2)
    raise RuntimeError(f'FAIL {label}: {last}')


def state():
    return get(8083,'/api/state')


def apply(name):
    get(8081,'/scenario/'+('jam' if name=='jam' else 'count-mismatch' if name=='count-mismatch' else 'normal'),'POST')
    get(8082,'/scenario/'+name,'POST')
    if name=='normal':
        get(8083,'/api/reconciliation/reset','POST')


def incident_with(alert):
    incidents=get(8090,'/api/incidents?active=true&limit=100')['incidents']
    for incident in incidents:
        detail=get(8090,f"/api/incidents/{incident['id']}")
        if any(a['name']==alert and a['status']=='firing' for a in detail['alerts']):
            return detail
    return None


def normal():
    apply('normal')
    wait('normal cameras, inference and health',lambda:all(c['up'] and c['tracking_ready'] and not c['anomalies'] and not c['reasons'] for c in state()['cameras']) and state()['health']['score']>=95)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quick',action='store_true',help='Normal and stalled-product demo only')
    args=parser.parse_args()
    performance=defaultdict(list)
    report=[]
    try:
        normal()
        initial=state()['counts']
        wait('real entry and exit counting-line crossings',lambda:state()['counts']['entered']>initial['entered'] and state()['counts']['exited']>initial['exited'],30)
        scenarios=[('stalled-product','object_stalled','ProductStalled')]
        if not args.quick:
            scenarios=[('jam',None,'ProductionLineBlocked'),('person-zone','person_in_restricted_zone','VisionPersonInRestrictedZone'),
                       ('stalled-product','object_stalled','ProductStalled'),('wrong-direction','wrong_direction','ProductWrongDirection'),
                       ('misaligned-product','visual_quality_failure','VisualQualityFailure'),('count-mismatch',None,'ProductionCountMismatch')]
        for name,event,alert in scenarios:
            apply(name)
            if event:
                wait(name+' derived image/track signal',lambda:any(event in c['anomalies'] for c in state()['cameras']))
            if name=='count-mismatch':
                wait('count mismatch derived from real PLC/entry deltas',lambda:state()['counts']['mismatch'])
            detail=wait(name+' → Alertmanager → persisted incident',lambda:incident_with(alert))
            if name=='count-mismatch':
                wait('aggregate missing exit derived from aged real entry crossings',lambda:state()['counts']['missing_exit'],150)
                related=wait('missing exit joins the count mismatch incident',lambda:incident_with('ProductMissingExit'))
                assert related['incident']['id']==detail['incident']['id'],(related['incident'],detail['incident'])
            current=state()
            for camera in current['cameras']:
                performance[camera['camera']].append(camera['inference_ms'])
            report.append(dict(scenario=name,incident=detail['incident']['number'],type=detail['incident']['type'],
                               alerts=[a['name'] for a in detail['alerts']],counts=current['counts'],health=current['health']['score']))
            print(json.dumps(report[-1]),flush=True)
            normal()
            wait(name+' underlying alert recovered',lambda:not incident_with(alert),100)
        if not args.quick:
            subprocess.run(['docker','compose','stop','camera-sim'],cwd=ROOT,check=True)
            wait('all cameras unavailable',lambda:all(not c['up'] for c in state()['cameras']))
            detail=wait('camera outage incident',lambda:incident_with('VisionCameraUnavailable'))
            assert detail['incident']['type']=='CAMERA_OUTAGE',detail['incident']
            subprocess.run(['docker','compose','start','camera-sim'],cwd=ROOT,check=True)
            normal()
            wait('camera outage underlying alerts recovered',lambda:not incident_with('VisionCameraUnavailable'))
        summary=dict(scenarios=report,performance_ms={c:dict(mean=statistics.mean(v),min=min(v),max=max(v)) for c,v in performance.items()})
        print(json.dumps(summary,indent=2),flush=True)
        print('All multi-camera runtime checks passed',flush=True)
    finally:
        subprocess.run(['docker','compose','start','camera-sim'],cwd=ROOT,check=False)
        apply('normal')


if __name__=='__main__':
    main()
