"""Shared cross-platform controller. Shell wrappers need Python 3, Docker and no pip packages."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ('normal object-mix person-zone fallen-object crowded-line jam overheat vibration quality-drop stopped dirty-camera dark-camera blur-camera '
            'stalled-product wrong-direction misaligned-product count-mismatch '
            'camera-offline camera-online opcua-down opcua-up edge-ot-cut edge-ot-restore '
            'cv-ot-cut cv-ot-restore state').split()


def docker(*args, capture=False):
    result = subprocess.run(["docker", *args], cwd=ROOT, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def compose(*args, capture=False):
    return docker("compose", *args, capture=capture)


def request(port, path, method="POST"):
    url = f"http://localhost:{port}{path}"
    for attempt in range(30):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=3) as response:
                return json.load(response)
        except OSError:
            if attempt == 29:
                raise
            time.sleep(1)


def network(service, restore):
    container = compose("ps", "-q", service, capture=True)
    if not container:
        raise RuntimeError(f"{service} is not running")
    info = json.loads(docker("inspect", container, capture=True))[0]
    project = info["Config"]["Labels"]["com.docker.compose.project"]
    networks = docker("network", "ls", "--filter", f"label=com.docker.compose.project={project}",
                      "--filter", "label=com.docker.compose.network=ot_net", "-q", capture=True).splitlines()
    if len(networks) != 1:
        raise RuntimeError(f"Expected one OT network for project={project}: {networks}")
    target = json.loads(docker("network", "inspect", networks[0], capture=True))[0]
    connected = target["Name"] in info["NetworkSettings"]["Networks"]
    if restore and not connected:
        docker("network", "connect", "--alias", service, target["Id"], container)
    elif not restore and connected:
        docker("network", "disconnect", target["Id"], container)
    print(f"{service}: OT {'connected' if restore else 'disconnected'}; cloud network preserved")


def run(command):
    if command == "normal":
        compose("start", "opcua-sim", "camera-sim", "telemetry-bridge", "cv-detector")
        network("telemetry-bridge", True)
        network("cv-detector", True)
        request(8081, "/scenario/normal")
        request(8082, "/scenario/normal")
        # Explicitly start a new observation baseline, retaining lifetime vision counters.
        request(8083, "/api/reconciliation/reset")
    elif command in ('stalled-product','wrong-direction','misaligned-product','count-mismatch'):
        request(8081, '/scenario/'+('count-mismatch' if command=='count-mismatch' else 'normal'))
        request(8082, '/scenario/'+command)
    elif command in ("jam", "overheat", "vibration", "quality-drop", "stopped"):
        request(8081, "/scenario/" + command)
        request(8082, "/scenario/" + ("jam" if command == "jam" else "normal"))
    elif command in ("dirty-camera", "dark-camera", "blur-camera", "object-mix",
                      "person-zone", "fallen-object", "crowded-line"):
        request(8082, "/scenario/" + command)
    elif command in ("camera-offline", "camera-online", "opcua-down", "opcua-up"):
        service = "camera-sim" if command.startswith("camera") else "opcua-sim"
        compose("stop" if command.endswith(("offline", "down")) else "start", service)
    elif command.startswith(("edge-ot-", "cv-ot-")):
        network("telemetry-bridge" if command.startswith("edge") else "cv-detector", command.endswith("restore"))
    elif command == "state":
        compose("ps")
        for port in (8081,8082):
            try:
                print(json.dumps(request(port,"/state","GET"), indent=2))
            except OSError as exc:
                print(f"API {port} unavailable: {exc}")
    print(f"Completed: {command}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    run(parser.parse_args().command)
