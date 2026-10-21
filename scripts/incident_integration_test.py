"""Real local scenarios only: persistent correlation, workflow, reports and recovery.
Temporarily disrupts the lab and restores normal. Never injects fabricated alerts.
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from integration_test import get, eventually, normal, value
from labctl import compose, run

BASE='http://localhost:8090'


def api(path,method='GET',body=None):
    content=json.dumps(body).encode() if body is not None else None
    request=urllib.request.Request(BASE+path,data=content,method=method,
        headers={'Content-Type':'application/json'} if content else {})
    with urllib.request.urlopen(request,timeout=10) as response:
        return json.load(response)


def incidents(**filters):
    return api('/api/incidents?'+urllib.parse.urlencode(filters))['incidents']


def detail(incident_id):
    return api(f'/api/incidents/{incident_id}')


def canonical_active(kind):
    return incidents(active='true',type=kind,site='local',line='line1')


def finish(incident_id):
    normal()
    eventually('underlying alerts recovered',lambda:all(a['status']=='resolved' for a in detail(incident_id)['alerts']),timeout=120)
    eventually('incident resolved and retained',lambda:detail(incident_id)['incident']['status']=='RESOLVED',timeout=150)
    report=api(f'/api/incidents/{incident_id}/report')
    assert report['final'] and report['timeline'] and report['alerts']
    with urllib.request.urlopen(BASE+f'/api/incidents/{incident_id}/report.md',timeout=10) as response:
        assert '# INC-' in response.read().decode()
    print('PASS final JSON/Markdown report',report['incident']['number'],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quick',action='store_true',help='Jam/workflow/persistence only; skip other scenarios')
    parser.add_argument('--restart-stack',action='store_true',help='Also restart the complete Compose stack without deleting volumes')
    args=parser.parse_args()
    try:
        normal()
        eventually('persistent incident service ready',lambda:api('/readyz')['status']=='ready')
        eventually('baseline incident alerts recovered',lambda:not any(a['status']=='firing' for a in api('/alerts')['alerts']),timeout=150)
        run('jam')
        eventually('one correlated Production Line Jam',lambda:len(canonical_active('PRODUCTION_JAM'))==1,timeout=120)
        incident_id=canonical_active('PRODUCTION_JAM')[0]['id']
        expected={'ProductionLineBlocked','ComputerVisionAnomaly','ExcessiveVibration','QualityDegradation','MLAnomaly'}
        eventually('all five real jam alerts correlated',lambda:expected <= {a['name'] for a in detail(incident_id)['alerts']},timeout=120)
        eventually('actual blocked PLC and OpenCV evidence persisted',lambda:
            any(e['source']=='PLC' and e['payload'].get('values',{}).get('BlockedSensor') is True for e in detail(incident_id)['evidence'])
            and any(e['source']=='OpenCV' and 'red-object' in e['payload'].get('reasons',[]) for e in detail(incident_id)['evidence']))
        assert len([i for i in incidents(active='true') if i['type'] in {'PRODUCTION_JAM','EXCESSIVE_VIBRATION','QUALITY_DEGRADATION','PROCESS_ANOMALY'}])==1
        api(f'/api/incidents/{incident_id}/acknowledge','POST',{'note':'Reviewed actual correlated jam signals.'})
        api(f'/api/incidents/{incident_id}/investigate','POST',{'note':'Inspecting persisted PLC and image evidence.'})
        api(f'/api/incidents/{incident_id}','PATCH',{
            'root_cause':'Blocked-sensor and red-obstruction signals confirmed during the controlled jam scenario.',
            'impact':'Simulated production flow was blocked; PLC and image evidence retained.'})
        number=detail(incident_id)['incident']['number']
        before_events=len(detail(incident_id)['timeline'])
        compose('restart','incident-receiver')
        eventually('incident service restart preserves number and history',lambda:
            api('/readyz')['status']=='ready' and detail(incident_id)['incident']['number']==number
            and len(detail(incident_id)['timeline'])>=before_events)
        run('normal')
        api(f'/api/incidents/{incident_id}/mitigate','POST',{'note':'Applied the normal scenario recovery; waiting for source alert confirmation.'})
        api(f'/api/incidents/{incident_id}','PATCH',{'remediation_actions':'Restored normal using the existing lab controller after inspecting the jam evidence.'})
        finish(incident_id)
        report=api(f'/api/incidents/{incident_id}/report')
        assert report['incident']['mtta_seconds'] is not None
        assert report['incident']['mttr_seconds'] is not None
        if not args.quick:
            for scenario,kind in [('overheat','MOTOR_OVERHEAT'),('vibration','EXCESSIVE_VIBRATION'),
                ('quality-drop','QUALITY_DEGRADATION'),('dark-camera','CAMERA_DEGRADATION'),
                ('camera-offline','CAMERA_OUTAGE'),('opcua-down','OPCUA_CONNECTIVITY'),
                ('edge-ot-cut','OT_NETWORK_CONNECTIVITY')]:
                run(scenario)
                eventually(scenario+' creates an incident from real alerts',lambda k=kind:bool(canonical_active(k)),timeout=150)
                current=canonical_active(kind)[0]['id']
                if scenario in {'camera-offline','opcua-down'}:
                    source_names=({'CameraStreamDown','EndpointUnavailable','ExporterDown'}
                                  if scenario=='camera-offline' else
                                  {'OPCUAConnectionLost','EndpointUnavailable','ExporterDown'})
                    eventually('source exporter and endpoint alerts join the same outage',lambda:
                        source_names <= {a['name'] for a in detail(current)['alerts']},timeout=120)
                    assert len(canonical_active(kind))==1
                finish(current)
        if args.restart_stack:
            compose('restart')
            eventually('full stack restart preserves final report',lambda:
                api('/readyz')['status']=='ready' and api(f'/api/incidents/{incident_id}/report')==report,timeout=150)
            normal()
        print('All incident scenario checks passed; historical reports retained',flush=True)
    finally:
        compose('start','incident-db','incident-receiver','mediamtx','mqtt')
        normal()


if __name__=='__main__':
    main()
