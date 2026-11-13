"""Exercise every labctl scenario sequentially against the running local stack."""
import argparse
from dataclasses import dataclass
import json
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from scripts.labctl import COMMANDS, run


@dataclass(frozen=True)
class Scenario:
    name: str
    expression: str = ""
    alerts: tuple = ()
    restore: str = ""
    defect: str = ""


SCENARIOS = (
    Scenario("object-mix"),
    Scenario("person-zone", 'yolo_class_detections{class="person"} > 0',
             ("PersonInRestrictedZone", "VisionPersonInRestrictedZone")),
    Scenario("fallen-object", alerts=("VisualQualityFailure",),
             defect="product-marker-outside-conveyor"),
    Scenario("crowded-line"),
    Scenario("stalled-product", 'vision_stalled_object_detected{camera="process"} == 1',
             ("ProductStalled", "ProductExcessiveDwell")),
    Scenario("wrong-direction", 'vision_wrong_direction_detected{camera="process"} == 1',
             ("ProductWrongDirection",)),
    Scenario("misaligned-product", alerts=("VisualQualityFailure",),
             defect="orientation-marker-horizontal"),
    Scenario("count-mismatch", "vision_count_mismatch == 1 and vision_count_reconciliation_ready == 1",
             ("ProductionCountMismatch", "ProductMissingExit")),
    Scenario("jam", "factory_blocked_sensor == 1 and factory_conveyor_speed_mps < 0.1",
             ("ProductionLineBlocked", "ComputerVisionAnomaly", "MLAnomaly")),
    Scenario("overheat", "factory_motor_temperature_c == 95", ("MotorOverheating",)),
    Scenario("vibration", "factory_motor_vibration_g > 0.5", ("ExcessiveVibration",)),
    Scenario("quality-drop", "factory_quality_score < 0.9", ("QualityDegradation",)),
    Scenario("stopped", "factory_conveyor_speed_mps == 0"),
    Scenario("dirty-camera", "cv_center_to_border_brightness_ratio < 0.25", ("ComputerVisionAnomaly",)),
    Scenario("dark-camera", "cv_frame_brightness < 25", ("ComputerVisionAnomaly",)),
    Scenario("blur-camera", "cv_laplacian_variance < 30", ("ComputerVisionAnomaly",)),
    Scenario("camera-offline", "cv_stream_up == 0", ("CameraStreamDown", "VisionCameraUnavailable"),
             restore="camera-online"),
    Scenario("opcua-down", "bridge_opcua_connected == 0", ("OPCUAConnectionLost",), restore="opcua-up"),
    Scenario("edge-ot-cut", "bridge_opcua_connected == 0", ("OPCUAConnectionLost",), restore="edge-ot-restore"),
    Scenario("cv-ot-cut", "cv_stream_up == 0", ("CameraStreamDown", "VisionCameraUnavailable"),
             restore="cv-ot-restore"),
)


def validate_coverage():
    covered = {"normal", "state"} | {s.name for s in SCENARIOS} | {s.restore for s in SCENARIOS if s.restore}
    if covered != set(COMMANDS):
        raise RuntimeError(f"Scenario coverage differs from labctl: missing={set(COMMANDS) - covered}, "
                           f"unknown={covered - set(COMMANDS)}")


def get(port, path):
    with urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=5) as response:
        return json.load(response)


def query(expression):
    path = "/api/v1/query?" + urllib.parse.urlencode({"query": expression})
    result = get(9090, path)
    if result["status"] != "success":
        raise RuntimeError(f"Prometheus query failed: {result}")
    return result["data"]["result"]


def state():
    return get(8083, "/api/state")


def wait(label, check, timeout):
    print(f"WAIT {label} (up to {timeout:g}s)", flush=True)
    deadline = time.monotonic() + timeout
    heartbeat = time.monotonic() + 20
    last = "condition still false"
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                print(f"PASS {label}", flush=True)
                return result
            last = "condition still false"
        except (OSError, ValueError, KeyError) as exc:
            last = str(exc)
        if time.monotonic() >= heartbeat:
            print(f"WAIT {label}: {last}", flush=True)
            heartbeat = time.monotonic() + 20
        time.sleep(2)
    raise RuntimeError(f"FAIL {label}: {last}")


def normal_ready():
    current = state()
    plc = current["plc"]
    cameras = current["cameras"]
    return (get(8081, "/state")["scenario"] == "normal"
            and get(8082, "/state")["scenario"] == "normal"
            and plc and current["plc_fresh"] and plc["LineStatus"] == "RUNNING"
            and not plc["BlockedSensor"] and plc["MotorTemperature"] < 50
            and plc["Vibration"] < 0.5 and plc["QualityScore"] > 0.9
            and {c["camera"] for c in cameras} == {"entry", "process", "exit"}
            and all(c["up"] and c["tracking_ready"] and not c["anomalies"] and not c["reasons"]
                    and time.time() - c["processed"] < 3 for c in cameras)
            and current["counts"]["ready"] and not current["counts"]["mismatch"]
            and not current["counts"]["missing_exit"]
            and bool(query("bridge_opcua_connected == 1"))
            and bool(query("time() - ml_last_input_timestamp_seconds < 10")))


def restore_normal(timeout):
    print("\n>>> normal", flush=True)
    run("normal")
    wait("normal PLC, all three cameras, tracking, telemetry and count baseline", normal_ready, timeout)
    wait("all Prometheus alerts recovered", lambda: not query('ALERTS{alertstate="firing"}'), timeout)
    wait("all incident source alerts recovered", lambda: not any(
        a["status"] == "firing" for a in get(8090, "/alerts")["alerts"]), timeout)


def incident_alerts():
    return {a["alertname"] for a in get(8090, "/alerts")["alerts"] if a["status"] == "firing"}


def process_camera():
    return next(c for c in state()["cameras"] if c["camera"] == "process")


def verify(scenario, timeout):
    name = scenario.name
    camera_only = {"object-mix", "person-zone", "fallen-object", "crowded-line", "dirty-camera",
                   "dark-camera", "blur-camera", "misaligned-product", "stalled-product", "wrong-direction"}
    if name in camera_only or name in {"count-mismatch", "jam"}:
        wait(f"{name}: actual camera scenario applied", lambda: get(8082, "/state")["scenario"] == name, timeout)
    if name in {"jam", "overheat", "vibration", "quality-drop", "stopped", "count-mismatch"}:
        wait(f"{name}: actual PLC scenario applied", lambda: get(8081, "/state")["scenario"] == name, timeout)
    if scenario.expression:
        wait(f"{name}: measured signal", lambda: query(scenario.expression), timeout)
    if scenario.defect:
        wait(f"{name}: OpenCV {scenario.defect}", lambda: any(
            d["reason"] == scenario.defect for d in process_camera()["quality"]), timeout)
    if name == "object-mix":
        for kind in ("bottle", "cup", "package"):
            wait(f"object-mix: actual {kind} detection", lambda k=kind: any(
                t["class"] == k for c in state()["cameras"] for t in c["tracks"]), timeout)
    elif name == "crowded-line":
        wait("crowded-line: at least four tracked products in the process view",
             lambda: process_camera()["objects"] >= 4, timeout)
    elif name == "count-mismatch":
        wait("count-mismatch: real unmatched entry ages into missing-exit signal",
             lambda: state()["counts"]["missing_exit"], timeout)
    elif name == "stopped":
        wait("stopped: planned stop and unavailable count comparison", lambda:
             state()["plc"]["LineStatus"] == "STOPPED" and not state()["counts"]["ready"], timeout)
    elif name in {"camera-offline", "cv-ot-cut"}:
        wait(f"{name}: all three raw views unavailable",
             lambda: all(not c["up"] for c in state()["cameras"]), timeout)
    for alert in scenario.alerts:
        wait(f"{name}: {alert} firing in Prometheus",
             lambda a=alert: query(f'ALERTS{{alertname="{a}",alertstate="firing"}}'), timeout)
        wait(f"{name}: {alert} received by incident portal",
             lambda a=alert: a in incident_alerts(), timeout)


def execute(timeout=180, observe_seconds=15):
    validate_coverage()
    completed = []
    try:
        restore_normal(timeout)
        wait("YOLO enabled and ready (required to test every scenario)", lambda:
             state()["yolo"]["enabled"] and state()["yolo"]["ready"], timeout)
        initial = state()["counts"]
        wait("real entry and exit counting-line crossings", lambda:
             state()["counts"]["entered"] > initial["entered"]
             and state()["counts"]["exited"] > initial["exited"], timeout)
        for index, scenario in enumerate(SCENARIOS, 1):
            print(f"\n[{index}/{len(SCENARIOS)}] >>> {scenario.name}", flush=True)
            started = time.monotonic()
            run(scenario.name)
            verify(scenario, timeout)
            remaining = observe_seconds - (time.monotonic() - started)
            while remaining > 0:
                print(f"Observing {scenario.name}: {remaining:.0f}s remaining", flush=True)
                time.sleep(min(remaining, 20))
                remaining = observe_seconds - (time.monotonic() - started)
            if scenario.restore:
                print(f">>> {scenario.restore}", flush=True)
                run(scenario.restore)
                expression = ("bridge_opcua_connected == 1" if scenario.restore in
                              {"opcua-up", "edge-ot-restore"} else "cv_stream_up == 1")
                wait(f"{scenario.restore}: connection recovered", lambda: query(expression), timeout)
            restore_normal(timeout)
            completed.append(scenario.name)
            print(f"PASS {scenario.name} and normal recovery", flush=True)
        run("state")
    finally:
        # Applies to failed assertions, Ctrl+C and SIGTERM as well as success.
        # A cleanup failure propagates too: never report success with a broken lab.
        restore_normal(timeout)
        print(f"Normal restored; {len(completed)}/{len(SCENARIOS)} scenarios completed.", flush=True)
    print(f"PASS all {len(SCENARIOS)} scenarios and all {len(COMMANDS)} controller commands", flush=True)


def interrupted(signum, frame):
    raise KeyboardInterrupt(f"Received signal {signum}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Print the sequence without changing the lab")
    parser.add_argument("--timeout", type=float, default=180, help="Maximum seconds per verification (default: 180)")
    parser.add_argument("--observe-seconds", type=float, default=15,
                        help="Minimum seconds per scenario, including verification (default: 15)")
    args = parser.parse_args()
    if not (0 < args.timeout < float("inf") and 0 <= args.observe_seconds < float("inf")):
        parser.error("timeout must be positive and observation time nonnegative; both must be finite")
    validate_coverage()
    if args.list:
        print("normal")
        for scenario in SCENARIOS:
            print(scenario.name)
            if scenario.restore:
                print(scenario.restore)
            print("normal")
        print("state\nnormal")
        return 0
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        execute(args.timeout, args.observe_seconds)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, KeyboardInterrupt) as exc:
        print(f"FAIL {exc}\nInspect docker compose ps/logs; retry recovery with make normal.", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0


if __name__ == "__main__":
    sys.exit(main())
