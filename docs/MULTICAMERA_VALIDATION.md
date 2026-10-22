# Multi-camera industrial vision validation

Validation date: 2026-10-22, macOS ARM64 with Docker Desktop, CPU inference only.
This is a record of executed local checks, not a live CI badge.

## Implementation inventory

| Files | Change |
|---|---|
| `common/line.py` | Shared nominal physical cadence, camera offsets and independent PLC photoeye schedule |
| `services/camera_sim/{main,scene}.py` | Three FFmpeg publishers, reusable scene, camera roles, industrial station details, marked parcels/cans, local motion/quality faults |
| `mediamtx/mediamtx.yml` | Three raw paths and backward-compatible `line1` process alias |
| `services/cv_detector/main.py` | Multi-camera runtime entry point; legacy `open_capture` retained |
| `services/cv_detector/multicamera.py` | Three bounded acquisition queues, one shared CPU model, per-camera analytics/metrics, telemetry/monitoring/incident context |
| `services/cv_detector/{tracking,analytics}.py` | Class-gated global assignment, velocity/dwell/zones/crossings, pixel marker geometry, reset-aware counts and deterministic health |
| `services/cv_detector/control_room.py`, `templates/control_room.html`, `static/control_room.{css,js}` | Local visual operations UI, three MJPEG/JPEG outputs, activity views, read-only state and twin APIs, explicit reconciliation reset |
| `services/opcua_sim/{main,process}.py` | Independent photoeye cadence and bouncing-sensor count-mismatch scenario |
| `services/incident_receiver/{rules,store,enrichment}.py` | Visual incident families/correlation and four sampled MQTT evidence channels |
| `prometheus/rules.yml` | Eight visual rules; original person-zone freshness window aligned to the five-second scrape cadence |
| `grafana/dashboards/computer-vision.json` | Compact Multi-Camera Vision section and Control Room links; original sections retained |
| `docker-compose.yml`, `.env.example`, `requirements.txt` | Five vision settings and explicit SciPy pin, no new runtime service or GPU dependency |
| `scripts/labctl.{py,sh,ps1}`, `Makefile` | Validated scenarios and visual integration/MQTT test targets |
| `tools/{smoke_test,vision_events_test}.py`, `scripts/vision_integration_test.py` | Actual streams, derived signals, MQTT, alert/incident and recovery checks |
| `tests/test_multicamera.py`, `tests/test_incidents.py`, `scripts/validate.py`, `.github/workflows/ci.yml` | Offline tracking/analytics/UI tests, correlation regression cases and validation |
| `README.md`, `SOURCES.md`, validation records, `docs/images/control-room.png` | URLs, exact rules/limits, sources and real browser capture |

## Architecture and semantics

The default stack still has 15 running services and an optional tools service.
All new video/analytics/UI work stays in the existing camera and CV services.
One shared YOLO26n CPU model serves entry/process/exit, with separate class-gated
constant-velocity global-assignment trackers. SciPy supplies the assignment
solver; there is no re-identification model or model download in unit tests.

Each raw path is `line1-<camera>` on RTSP port 8554 and HLS port 8888. `line1`
remains the process-camera alias. Annotation uses the explicitly permitted
simpler HTTP/MJPEG approach:

- `http://localhost:8083/cameras/entry/annotated.mjpg`
- `http://localhost:8083/cameras/process/annotated.mjpg`
- `http://localhost:8083/cameras/exit/annotated.mjpg`

JPEG and activity images use the same camera path with `snapshot.jpg` and
`heatmap.jpg`. `/annotated.mjpg` and `/snapshot.jpg` still mean process camera.
`http://localhost:8083/` is the Control Room; `/api/state` and `/api/twin` expose
actual data. The five-node twin uses camera/image/tracking and fresh PLC states.

YOLO provides only its actual semantic boxes/classes/confidences. OpenCV checks
known cyan inspection fiducials and marks approximate package ROIs explicitly
as `CV`. No pretrained factory-defect, damage, missing-label or wrong-color
classification is claimed. Model results never come from scenario names or
renderer object coordinates. Tracking gets only inferred boxes and times.

Counting totals are Prometheus counters scoped to the CV process lifetime;
scenario changes and camera reconnects preserve them. Counting-line crossings
are camera-local and at most once per track. Track loss can fragment identity.
The in-process gauge counts unmatched observed entries, not unknown initial
inventory. Aggregate exit matching assumes a minimum 20-second transit (nominal
22.4 seconds), with a 45-second missing-exit limit; it is not cross-camera ID matching.

PLC reconciliation compares **deltas** from an explicit fresh baseline. Camera,
inference, image quality and telemetry availability gate it; planned stopped/
blocked PLC states suspend comparison. A PLC count rollback also starts a new
epoch. `normal` calls `POST /api/reconciliation/reset` and keeps vision totals.
This action starts a new observation session, without asserting that missing
products physically recovered. Difference is NaN in metrics/null in JSON while
unavailable. The original PLC count metric remains a gauge despite its suffix.

The health formula awards 15 points for fresh PLC telemetry, 10 each for running
conveyor, temperature, vibration, PLC quality, clear visual/count checks, ready
YOLO with fresh per-camera tracking, camera availability, and independent
network/bridge checks, plus 5 for fresh normal ML. False or unavailable earns
zero. Total 100; details are returned in `/api/state` and documented in README.

## Executed validation

- Python AST/compilation, YAML/JSON/shell and Compose syntax.
- **77 tests passed**, without model/Ultralytics downloads, including an actual isolated
  PostgreSQL schema test. The original 50 tests remain in the suite.
- Docker image builds and startup with existing named volumes retained; `pip check` clean.
- Full smoke test passed: original HTTP/TCP, encrypted OPC-UA, MQTT, legacy video,
  all three RTSP/HLS streams, all annotated JPEG/MJPEG outputs and activity images,
  count changes, Control Room/twin, Prometheus/Grafana/incident portal and Loki logs.
- Promtool: 22 valid rules; original 14 rules retained.
- Real YOLO-inferred bottle/person tracks and per-camera counting, not injected
  detector fixtures. Legacy process-camera metrics/topics remain available.
- Browser checks with installed local Chrome: desktop 1550px and mobile 390px,
  no JavaScript page errors, no external requests, no horizontal mobile overflow,
  and all three activity/AI-overlay switches working.
- Existing incident regression passed: all five real jam alerts correlated, PLC/
  OpenCV evidence retained, acknowledge/investigate/mitigate workflow and notes,
  receiver restart preserved history, final JSON/Markdown reports generated after
  recovery with non-null MTTA/MTTR.
- Four actual MQTT topics observed during scenarios: `vision/events`,
  `vision/counts`, `vision/safety`, `vision/quality`.

The runtime runner exercises normal, jam, person-zone, stalled-product,
wrong-direction, misaligned-product, count-mismatch and camera-offline, with
normal recovery. It verifies persisted Alertmanager-delivered occurrences,
not fabricated webhooks. Count mismatch models faulty photoeye input and
missing exit products; its alerts read real derived counters/ages.

A live timing issue was found in the inherited person-zone alert: fresh source
results sampled by Prometheus were 3.8–4.1 seconds old at rule evaluation, above
its old three-second threshold. The exporter still expires stale detections at
three seconds; the alert now allows two scrape intervals (10 seconds), alongside
live-stream, enabled/readiness and violation flags. This avoids suppressing a
continuous fresh signal solely because scrape/evaluation schedules differ. A real
follow-up person-zone run delivered both the original and tracked alerts into
the same persisted incident; both recovered while counting totals were retained.

## Runtime results

The complete actual scenario matrix passed, including normal recovery after each
fault and after restarting the camera simulator. Observed persisted cases:

| Scenario | Actual derived signal and persisted result |
|---|---|
| Normal | Three raw feeds and recent inference; observed entry/exit counts increased; health 100 |
| Jam | PLC blocked sensor, red obstruction and existing process alert → PRODUCTION_JAM |
| Person zone | Real YOLO person track and overlap → RESTRICTED_ZONE_VIOLATION |
| Stalled product | Nearly stationary inferred process tracks with fresh running PLC → PRODUCT_STALLED |
| Wrong direction | Sustained negative inferred track velocity → WRONG_DIRECTION |
| Misaligned product | OpenCV pixel fiducial aspect ratio → VISUAL_QUALITY_FAILURE |
| Count mismatch | Actual PLC/vision difference reached +35; missing-exit age became active and joined the same COUNT_MISMATCH incident |
| Camera offline | All three raw frame states became unavailable → one CAMERA_OUTAGE family; normal frames/health recovered after startup |

The matrix sampled six real inference latencies per view during its scenario
checks. These are observed runtime samples, not a statistically controlled
throughput benchmark:

| Camera | Mean inference | Range |
|---|---|---|
| Entry | 80.8 ms | 54.1–159.3 ms |
| Process | 76.7 ms | 54.9–138.3 ms |
| Exit | 67.0 ms | 57.1–82.4 ms |

Normal decoded video was about **9.8 fps per camera**; sampled inference is about
**2 Hz per camera**, six total through one model. A live Docker stats sample
showed CV at ~180% CPU (~1.8 cores) / 408 MiB and camera simulation at ~10% CPU /
223 MiB. These values depend on host load and exclude the rest of the stack.

Final restored state: scenario **normal**, health **100/100**, all three cameras
available with fresh tracking, PLC/vision delta **0**, about **9.82 fps** per view.
One final sample measured tracking/quality updates at **0.37–0.39 ms**. Cumulative
overwritten inference slots were entry=2, process=1, exit=2 after browser/demo
load; these are intentionally dropped queued inference frames, not a raw-camera
frame-loss measurement. Recent camera/CV/incident logs had no application errors.

## Metrics and event contracts

Bounded `camera` values are entry/process/exit. No object IDs are metric labels.
Per-camera metrics: availability, object count, tracking readiness, FPS, YOLO and
tracking latency, skipped/dropped frames, last decoded/processed timestamps,
tracked restriction, stall, reverse direction, dwell and OpenCV quality flags.
Global metrics: entry/exit counters, unmatched in-process gauge, trailing-minute
exit flow, PLC difference/readiness/mismatch/epoch, missing exit and two health
score names (`factory_line_health_score`, `vision_line_health_score`).

`vision/events` publishes actual crossing/motion/inspection transitions;
`vision/safety` publishes ENTERED/PRESENT/EXITED and person dwell;
`vision/quality` publishes actual marker geometry and active/clear state;
`vision/counts` publishes count values, scope, time and baseline state. IDs stay
inside payloads. Incident evidence is sampled using the existing bounded
coalescing policy, not stored as a lossless event journal. Alertmanager remains
the incident trigger; MQTT only enriches its persisted evidence.

## Limitations

- Synthetic composite scenes and known markers, not a custom industrial dataset.
- Camera-local lightweight assignment can swap/fragment IDs through occlusion,
  dense products or sudden appearance changes. Counts are approximate observations.
- Process station scenarios are local visual demonstrations; this is not a full
  synchronized material-flow or mechanical dynamics simulator.
- Aggregate flow assumes nominal transit and cannot identify an individual
  missing product. No cross-camera re-identification or calibrated metric speed.
- Frame timestamps are decoder receipt times; no camera latency synchronization
  or capture-time calibration is claimed. Heatmaps also include conveyor motion.
- The 0–100 health score is deterministic, not learned or a safety rating.
- No certified personnel protection, safety interlock or autonomous machine control.
- CPU measurements vary with load; this run covers ARM64 Docker Desktop only.
  Windows/PowerShell runtime, GPU, real cameras and other architectures were not run.
- No additional authentication/RBAC; existing localhost-only demo boundaries apply.

## Exact demo and verification commands

```bash
docker compose up -d --build
./scripts/labctl.sh normal
# Open http://localhost:8083/ and http://localhost:3000/
./scripts/labctl.sh object-mix
./scripts/labctl.sh normal
./scripts/labctl.sh stalled-product
# Allow about 20–40 seconds; inspect track dwell, alerts and incident portal.
# Open http://localhost:8090/incidents
./scripts/labctl.sh normal
./scripts/labctl.sh person-zone
./scripts/labctl.sh normal
./scripts/labctl.sh misaligned-product
./scripts/labctl.sh normal
./scripts/labctl.sh wrong-direction
./scripts/labctl.sh normal
./scripts/labctl.sh count-mismatch
# Count alert takes roughly 30–50s; missing-exit correlation takes longer (~90s).
./scripts/labctl.sh normal
make validate
make test
make smoke
make vision-test
# Run in a separate terminal during vision-test:
make vision-events
```

`python3 scripts/vision_integration_test.py --quick` runs the normal/stall/recovery
path only. Scenario wrappers share one Python implementation; PowerShell takes
the same command argument. No source push or deployment is part of this upgrade.
