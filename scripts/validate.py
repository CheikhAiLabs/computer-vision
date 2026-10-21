"""Fast, offline repository validation (PyYAML required)."""
import ast
import json
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ['docker-compose.yml','Dockerfile','Makefile','.env.example','requirements.txt','LICENSE','SOURCES.md','README.md',
    'mosquitto/mosquitto.conf','mediamtx/mediamtx.yml','prometheus/prometheus.yml',
    'prometheus/rules.yml','prometheus/blackbox.yml','alertmanager/alertmanager.yml',
    'loki/loki.yml','alloy/config.alloy','grafana/dashboards/computer-vision.json',
    'scripts/labctl.sh','scripts/labctl.ps1','.github/workflows/ci.yml',
    'tools/opcua_browse.py','tools/opcua_secure_read.py','tools/opcua_subscribe.py',
    'tools/mqtt_tail.py','tools/smoke_test.py']
SERVICES = {'mqtt','opcua-sim','mediamtx','camera-sim','telemetry-bridge','cv-detector',
    'ml-anomaly','incident-receiver','prometheus','blackbox-exporter','alertmanager',
    'loki','alloy','grafana','tools'}


def main():
    for path in REQUIRED:
        assert (ROOT/path).is_file(), f'Missing {path}'
    for path in ROOT.rglob('*'):
        if any(part in {'.git','.venv','__pycache__','artifacts'} for part in path.parts):
            continue
        if path.suffix == '.py':
            ast.parse(path.read_text(),filename=str(path))
        elif path.suffix in {'.yml','.yaml'}:
            yaml.safe_load(path.read_text())
        elif path.suffix == '.json':
            json.loads(path.read_text())
    compose = yaml.safe_load((ROOT/'docker-compose.yml').read_text())
    assert set(compose['services']) == SERVICES
    for service in compose['services'].values():
        for port in service.get('ports',[]):
            assert port.startswith('127.0.0.1:'),port
    assert compose['services']['opcua-sim']['networks'] == ['ot_net']
    for edge in ['telemetry-bridge','cv-detector']:
        assert set(compose['services'][edge]['networks']) == {'ot_net','cloud_net'}
    dashboard = json.loads((ROOT/'grafana/dashboards/computer-vision.json').read_text())
    assert dashboard['uid'] == 'industrial-computer-vision'
    assert len({p['id'] for p in dashboard['panels']}) == len(dashboard['panels'])
    readme = (ROOT/'README.md').read_text()
    for obsolete in ['computer-fusion','Computer Fusion','cerrion-lab','Cerrion-style']:
        assert obsolete not in readme,obsolete
    subprocess.run(['bash','-n',str(ROOT/'scripts/labctl.sh')],check=True)
    print('PASS Python AST, YAML, JSON/dashboard, shell syntax, structure, networks, localhost ports, naming')


if __name__ == '__main__':
    main()
