"""Prepare a real demo state for manual screenshots; never generate images."""
import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from labctl import ROOT, compose, run

URLS = (
    ("Camera", "http://localhost:8888/line1/"),
    ("Grafana", "http://localhost:3000"),
    ("Alertmanager", "http://localhost:9093"),
    ("Incident Management Portal", "http://localhost:8090/"),
)


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def wait_for(label, check, timeout=120):
    print(f"Waiting for {label} (up to {timeout}s)...", flush=True)
    deadline = time.monotonic() + timeout
    last_error = "condition not yet met"
    while time.monotonic() < deadline:
        try:
            if check():
                print(f"Confirmed: {label}", flush=True)
                return
        except (OSError, ValueError, KeyError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {label}: {last_error}")


def metrics_ready(jam):
    desired = {
        "bridge_opcua_connected": 1,
        "cv_stream_up": 1,
        "factory_blocked_sensor": int(jam),
        "cv_anomaly_detected": int(jam),
        "ml_anomaly_detected": int(jam),
    }
    for metric, expected in desired.items():
        url = "http://localhost:9090/api/v1/query?" + urllib.parse.urlencode({"query": metric})
        samples = get_json(url)["data"]["result"]
        if not samples or any(float(s["value"][1]) != expected for s in samples):
            return False
    fresh = get_json("http://localhost:9090/api/v1/query?" + urllib.parse.urlencode(
        {"query": "time() - ml_last_input_timestamp_seconds"}))["data"]["result"]
    return bool(fresh) and all(float(s["value"][1]) < 15 for s in fresh)


def alerts_ready():
    expected = {"ProductionLineBlocked", "ComputerVisionAnomaly", "MLAnomaly"}
    alerts = get_json("http://localhost:9093/api/v2/alerts")
    firing = {a["labels"].get("alertname") for a in alerts if a["status"]["state"] == "active"}
    incidents = get_json("http://localhost:8090/alerts")["alerts"]
    delivered = {a["alertname"] for a in incidents if a["status"] == "firing"}
    return expected <= firing and expected <= delivered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("jam", "normal"))
    parser.add_argument("--open", action="store_true", help="Optionally open the URLs on macOS")
    args = parser.parse_args()
    try:
        compose("up", "-d", "--build")
        run("normal")
        wait_for("normal telemetry, video and inference", lambda: metrics_ready(False))
        if args.scenario == "jam":
            print("Recording 15 seconds of normal baseline for the Grafana charts...", flush=True)
            time.sleep(15)
            run("jam")
            wait_for("jam telemetry, CV and ML anomalies", lambda: metrics_ready(True))
            wait_for("firing alerts in Alertmanager and the incident receiver", alerts_ready)
        wait_for("Grafana health", lambda: get_json("http://localhost:3000/api/health").get("database") == "ok")
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Demo preparation failed: {exc}", file=sys.stderr)
        print("Inspect docker compose ps/logs; restore with ./scripts/demo_screenshots.sh normal.", file=sys.stderr)
        return 1

    print(f"\nDemo state: {args.scenario}. No screenshots have been captured.")
    for label, url in URLS:
        print(f"\n{label}:\n{url}")
    if args.scenario == "jam":
        (ROOT / "docs" / "images").mkdir(parents=True, exist_ok=True)
        print("\nSave real browser captures in docs/images/:")
        print("  camera-jam.png\n  grafana-jam.png\n  alertmanager-jam.png")
        print("Grafana: admin/admin; open Industrial Computer Vision & OT Lab, use Last 5 minutes.")
        print("Capture the process panels and CV/ML anomalies; see docs/images/README.md.")
        print("Jam stays active until you run ./scripts/demo_screenshots.sh normal.")
    else:
        print("\nNormal restored. Allow time for alert resolution notifications to arrive.")
    if args.open:
        if sys.platform == "darwin" and shutil.which("open"):
            for _, url in URLS:
                result = subprocess.run(["open", url], check=False)
                if result.returncode:
                    print(f"Could not open {url}; open it manually.", file=sys.stderr)
        else:
            print("Automatic URL opening is optional and macOS-only; open the URLs manually.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Restore with ./scripts/demo_screenshots.sh normal.", file=sys.stderr)
        sys.exit(130)
