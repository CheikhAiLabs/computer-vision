# Local validation record — 2026-10-21

The subsequent [Incident Management validation](INCIDENT_VALIDATION.md) records
persistent correlation, the local portal, PostgreSQL and incident lifecycle checks.

The subsequent [YOLO upgrade validation](YOLO_VALIDATION.md) records the richer
scene, 21 unit tests, actual offline inference and the extended runtime checks.
The original baseline results below are preserved for reference.

Executed on macOS arm64 with Docker Desktop 4.96.0, Docker Engine 29.9.1,
Compose v5.6.0, and Python 3.12 in the application image. No cloud account,
paid API or API key was used. The first build downloaded public open-source
images and packages.

## Results

| Check | Actual result |
|---|---|
| Repository tree and required files | Passed |
| Python compileall, AST, YAML, dashboard JSON, Bash syntax | Passed |
| Docker Compose configuration | Passed |
| Docker image builds | Passed |
| Python installed dependencies (`pip check`) | Passed |
| Focused unit tests | 6 passed |
| Prometheus configuration and rules | Passed; 11 alert rules |
| Alertmanager configuration | Passed |
| Alloy native configuration validator | Passed |
| Loki native configuration validator | Passed |
| Final full smoke test | Passed |
| OPC-UA browse and reads | Seven actual variable values printed |
| OPC-UA subscription | Real data changes observed; subscription deleted on cancellation |
| OPC-UA SignAndEncrypt | Actual secure read passed |
| Pinned server certificate | Sign and SignAndEncrypt reads passed |
| Wrong server certificate | Connection failed/timed out as expected |
| MQTT | QoS 1 publish acknowledgement, round-trip reception, telemetry, ML and CV topics verified |
| RTSP | OpenCV decoded real streamed frames |
| HLS | Player HTML and generated M3U8 playlist returned successfully after cookie-check redirect |
| Prometheus | All 14 scrape targets up and all seven Blackbox probes successful in final smoke test |
| Grafana | Health, provisioned dashboard UID and both data sources verified through API |
| Alloy → Loki | Actual telemetry-bridge container logs queried successfully |
| README metrics | All 25 named application metrics found on live exporters |
| Manual PLC override | MotorTemperature=105 applied; invalid values rejected; normal restored |

## Failure and recovery suite

`python3 scripts/integration_test.py` passed and restored normal in its finalizer.

- Normal: fresh telemetry, connected bridge, decoded video, healthy camera image.
- Overheat: temperature=95, Prometheus firing, actual Alertmanager webhook received.
  Returning to normal delivered the resolved notification.
- Jam: blocked sensor, slow conveyor, red-object CV detection, ML anomaly and incident.
- Camera offline/online: MediaMTX remained alive; CV recovered without container restart.
- OPC-UA down/up: bridge remained alive and reconnected without container restart.
- Edge OT cut/restore: PLC stayed alive and its Blackbox TCP probe stayed successful;
  bridge lost only its OT path and recovered automatically.
- CV OT cut/restore: vision detected stream loss and recovered automatically.
- Dark, blurred and dirty camera: corresponding image statistics and CV anomaly verified.
- MediaMTX outage: camera control plane stayed alive; FFmpeg publishing and CV recovered.
- MQTT outage: ML input age increased; reconnect restored fresh inference input.

The bridge and CV container identities/restart counts were unchanged throughout
the final scenario suite. The full stack was left running in normal state.
Final sampled metrics: bridge_opcua_connected=1, cv_stream_up=1,
cv_anomaly_detected=0, ml_model_ready=1, ml_anomaly_detected=0,
factory_blocked_sensor=0, temperature approximately 45 C.

## Calibration and limits

The initial IsolationForest boundary missed single-feature overheating/vibration.
The final model uses contamination=0.12, documented as a sensitive educational
threshold over broad synthetic normal training data. Across 158 deterministic
process samples spanning 3,000 simulated seconds, normal produced no flags,
overheat was flagged in 151 samples and vibration in 158. These are synthetic
calibration checks, not accuracy claims for industrial data. Runtime overheating
also showed occasional false negatives; the independent temperature alert still
fired and resolved correctly.

A direct HTTP client initially needed redirect/cookie handling to fetch the HLS
playlist; the corrected client passed. A trial in-process API harness attempted
to bind a second metrics server inside the live PLC container; that harness was
replaced by successful HTTP checks against the actual API.

PowerShell is not installed on this host: the Windows wrapper was reviewed but
not executed or parsed locally. CI includes a native PowerShell parser check,
but the GitHub Actions workflow itself has not been run on GitHub. Browser visual
rendering and Windows/amd64 runtime operation were not manually tested. Certificates,
anonymous MQTT, admin/admin and Docker socket access remain explicitly lab-only.

## Commands used

```bash
python3 -m compileall -q .
docker compose --profile tools config --quiet
docker compose build
docker compose up -d
docker compose ps
docker compose --profile tools run --rm -v "$PWD:/workspace:ro" tools python /workspace/scripts/validate.py
docker compose --profile tools run --rm -v "$PWD/tests:/tests:ro" tools python -m unittest discover -s /tests -v
docker compose exec opcua-sim python -m pip check
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
docker compose exec alloy alloy validate /etc/alloy/config.alloy
docker compose exec loki /usr/bin/loki -config.file=/etc/loki/loki.yml -verify-config=true
docker compose --profile tools run --rm tools python /tools/opcua_browse.py
docker compose --profile tools run --rm tools python /tools/opcua_secure_read.py
mkdir -p certs
docker compose cp opcua-sim:/certs/server.der certs/server.der
docker compose --profile tools run --rm -v "$PWD/certs/server.der:/trust/server.der:ro" tools python /tools/opcua_security_test.py
python3 scripts/integration_test.py
docker compose --profile tools run --rm tools python /tools/smoke_test.py
```
