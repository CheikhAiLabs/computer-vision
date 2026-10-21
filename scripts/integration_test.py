"""Destructive-to-lab scenarios only; restores normal in finally. No third-party deps."""
import json
import subprocess
import time
import urllib.parse
import urllib.request
from labctl import ROOT, run, compose, docker


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def query(expr):
    result = get('http://localhost:9090/api/v1/query?' + urllib.parse.urlencode({'query':expr}))
    return result['data']['result']


def value(expr):
    result = query(expr)
    return float(result[0]['value'][1]) if result else None


def eventually(label, check, timeout=90):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            if check():
                print('PASS',label,flush=True)
                return
        except Exception as exc:
            last = exc
        time.sleep(2)
    raise AssertionError(f'{label} failed; last exception={last}')


def stable_service(name):
    cid = compose('ps','-q',name,capture=True)
    info = json.loads(docker('inspect',cid,capture=True))[0]
    return cid,info['RestartCount'],info['State']['Running']


def incident(name,status):
    return any(a['alertname']==name and a['status']==status
               for a in get('http://localhost:8090/alerts')['alerts'])


def normal():
    run('normal')
    eventually('normal bridge, CV, process and fresh ML input', lambda:
        value('bridge_opcua_connected')==1 and value('cv_stream_up')==1
        and value('cv_anomaly_detected')==0 and value('factory_blocked_sensor')==0
        and value('factory_motor_temperature_c')<50
        and value('time() - ml_last_input_timestamp_seconds')<10)


def main():
    try:
        normal()
        before_bridge = stable_service('telemetry-bridge')
        before_cv = stable_service('cv-detector')
        run('overheat')
        eventually('overheat process metric',lambda:value('factory_motor_temperature_c')==95)
        eventually('overheat Prometheus firing',lambda:bool(query('ALERTS{alertname="MotorOverheating",alertstate="firing"}')))
        eventually('Alertmanager webhook reaches incident receiver',lambda:incident('MotorOverheating','firing'))
        assert value('cv_anomaly_detected')==0
        print('OBSERVED overheat ML result:',value('ml_anomaly_detected'),flush=True)
        normal()
        eventually('resolved webhook arrives',lambda:incident('MotorOverheating','resolved'))
        run('jam')
        eventually('jam PLC + real video + ML',lambda:value('factory_blocked_sensor')==1
            and value('factory_conveyor_speed_mps')<0.1 and value('cv_red_pixel_ratio')>0.025
            and value('cv_anomaly_detected')==1 and value('ml_anomaly_detected')==1)
        eventually('jam incident',lambda:incident('ProductionLineBlocked','firing'))
        normal()
        run('camera-offline')
        eventually('camera offline detected',lambda:value('cv_stream_up')==0)
        assert stable_service('mediamtx')[2]
        assert stable_service('cv-detector')==before_cv
        run('camera-online')
        eventually('CV recovers without restart',lambda:value('cv_stream_up')==1)
        normal()
        run('opcua-down')
        eventually('OPC-UA outage detected',lambda:value('bridge_opcua_connected')==0)
        assert stable_service('telemetry-bridge')==before_bridge
        run('opcua-up')
        eventually('bridge reconnects without restart',lambda:value('bridge_opcua_connected')==1)
        normal()
        run('edge-ot-cut')
        eventually('edge OT path lost',lambda:value('bridge_opcua_connected')==0)
        assert stable_service('opcua-sim')[2]
        assert value('probe_success{instance="opcua-sim:4840"}')==1
        assert stable_service('telemetry-bridge')==before_bridge
        run('edge-ot-restore')
        eventually('edge OT path restored',lambda:value('bridge_opcua_connected')==1)
        normal()
        run('cv-ot-cut')
        eventually('CV OT path lost',lambda:value('cv_stream_up')==0)
        run('cv-ot-restore')
        eventually('CV OT path restored',lambda:value('cv_stream_up')==1)
        for scenario,expr in [('dark-camera','cv_frame_brightness < 25'),
                              ('blur-camera','cv_laplacian_variance < 30'),
                              ('dirty-camera','cv_center_to_border_brightness_ratio < 0.25')]:
            normal()
            run(scenario)
            eventually(scenario+' image statistics and anomaly',lambda e=expr:bool(query(e)) and value('cv_anomaly_detected')==1)
        normal()
        compose('stop','mediamtx')
        eventually('MediaMTX outage visible',lambda:value('cv_stream_up')==0)
        assert stable_service('camera-sim')[2]
        compose('start','mediamtx')
        eventually('publisher and CV recover after MediaMTX outage',lambda:value('cv_stream_up')==1)
        compose('stop','mqtt')
        eventually('ML input becomes stale during MQTT outage',lambda:value('time() - ml_last_input_timestamp_seconds')>20)
        compose('start','mqtt')
        eventually('MQTT reconnect restores ML input',lambda:value('time() - ml_last_input_timestamp_seconds')<10)
        assert stable_service('cv-detector')==before_cv
        assert stable_service('telemetry-bridge')==before_bridge
        print('All scenario tests passed',flush=True)
    finally:
        compose('start','mediamtx','mqtt')
        normal()


if __name__=='__main__':
    main()
