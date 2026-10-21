# YOLO upgrade validation — 2026-10-21

Local macOS ARM64 host, Linux/aarch64 Docker Desktop containers, Python 3.12.
Ultralytics headless 8.4.183; PyTorch 2.9.1+cpu and Torchvision 0.24.1.
`torch.version.cuda` is `None`; runtime `ONLINE` and settings `sync` are both false.
No paid service, API key, remote inference or proprietary dataset is used.

## Implementation and changed files

| Files | Change |
|---|---|
| `services/camera_sim/scene.py` | Steel conveyor, seams, shadows, rails, fasteners, walkway, moving photographic assets, parcels and four additional scenarios; original fault rendering retained |
| `assets/objects/{bottle,cup,person}.png` | Three local public-domain/CC0 transparent cutouts; approximately 268 KiB total |
| `scripts/prepare_assets.py`, `SOURCES.md` | Offline asset preparation recipe and source/license/modification records |
| `services/cv_detector/yolo.py` | Local-file model loader, sampled latest-frame worker, parser, normalized rectangle overlap, MQTT contracts, bounded metrics, failure isolation and stale/in-flight invalidation |
| `services/cv_detector/annotated.py`, `services/cv_detector/main.py` | Optional HTTP JPEG/MJPEG annotation and CV worker integration; original heuristics and anomaly contract retained |
| `Dockerfile`, `Dockerfile.cv`, `requirements-cv.txt`, `docker-compose.yml`, `.env.example` | Shared image plus dedicated CPU CV image, build-time checksummed model, flags, localhost preview port and CV health check |
| `tools/fetch_yolo.py`, `tools/yolo_test.py` | Build-time model fetch and optional real offline CPU inference validation |
| `tools/smoke_test.py` | Optional YOLO readiness/freshness, real detection messages, annotated frame decoding and raw HLS playlist checks |
| `tests/test_yolo.py` | Mocked model tests with no weights/Ultralytics installation required |
| `scripts/integration_test.py` | Person-zone metric, actual MQTT safety contract and alert/incident firing/resolution checks; existing outage suite retained |
| `scripts/labctl.py`, `Makefile` | New scenario commands and `make yolo-test`; existing shell and PowerShell wrappers already dispatch through this controller |
| `scripts/validate.py` | Required feature files and local assets included in static checks |
| `prometheus/rules.yml`, `grafana/dashboards/computer-vision.json` | Two alerts and eight compact YOLO panels; all original rules/panels retained |
| `README.md`, `docs/VALIDATION.md`, `docs/YOLO_VALIDATION.md` | Three-layer architecture, operations, demo, limitations, roadmap and validation records |

The default model is **YOLO26n**, trained on COCO. Its actual class list was printed
and inspected. Application output is limited to `person`, `bottle`, `cup`,
`backpack`, `handbag` and `suitcase`. There is no invented jam, box or defect class.

Additional scenarios: `object-mix`, `person-zone`, `fallen-object`, `crowded-line`.
A representative object-mix frame produced actual bottle and cup predictions;
the cup confidence was 0.867. A representative person-zone frame produced an
actual person prediction at 0.904 confidence. These are individual observations,
not recognition accuracy estimates or guarantees for every animation frame.

MQTT additions:

- `factory/line1/cv/detections`: actual class, confidence, pixel xyxy boxes, model,
  UTC completion timestamp and source-frame receipt time; empty detections valid.
- `factory/line1/cv/safety`: actual person-box overlap with the configured zone.
  Repeated sampled observations are not unique-person events.

Metrics: `yolo_enabled`, `yolo_model_ready`,
`yolo_inference_duration_seconds` (histogram), `yolo_objects_detected`,
`yolo_detections_total`, `yolo_last_inference_timestamp_seconds`,
`yolo_restricted_zone_violation`, `yolo_class_detections{class="..."}`.
The class label has six fixed values; boxes, confidence and IDs never become labels.
`cv_annotated_enabled` advertises preview configuration to smoke tests.

Alerts: `YOLOModelUnavailable` (enabled, not ready for 60s) and
`PersonInRestrictedZone` (fresh inference, live stream and zone violation for 5s).
Existing Alertmanager routing and Incident Receiver contracts are reused.

Raw video stays at `rtsp://localhost:8554/line1` and
`http://localhost:8888/line1/`. Optional annotation uses
`http://localhost:8083/annotated.mjpg` and `http://localhost:8083/snapshot.jpg`.
The preview shows model-result age because sampled boxes can lag moving products.

## Actual checks

- Python compileall/AST, YAML, JSON, Bash syntax, required files and localhost
  network/port checks passed. Compose configuration passed.
- 21 offline unit tests passed, including the six original vision/ML tests.
  Model loading and inference are mocked in the added tests; no weights are downloaded.
- Dedicated CPU image and all Compose service builds passed. `pip check` passed;
  only one OpenCV wheel, `opencv-python-headless`, is installed.
- Actual inference succeeded in a container started with `--network none`.
  Person-zone produced a real person/zone intersection; object-mix produced
  actual cup and bottle detections.
- Prometheus validated all 13 rules and Alertmanager accepted its configuration.
- Full smoke passed: endpoints, secure OPC-UA, MQTT telemetry/ML/CV/detections,
  RTSP frame decoding, raw HLS player/playlist, JPEG and MJPEG decoding, Prometheus targets and Blackbox
  probes, provisioned Grafana panels/data sources, and Alloy-to-Loki logs.
- Full failure/recovery suite passed: normal, overheating and incident resolution,
  person-zone and incident firing/resolution, object-mix, fallen-object,
  crowded-line, deterministic jam plus PLC/ML, camera offline/online, PLC down/up,
  both OT network cuts/restores, dark/blur/dirty camera, MediaMTX outage and MQTT
  outage. CV and bridge container identity/restart counts were unchanged across
  that suite; normal was restored in its finalizer.
- With `ENABLE_YOLO=false`, jam still triggered classical CV, PLC and ML signals,
  and the full smoke test passed, including raw HLS player/playlist checks.
- With enabled YOLO and `/models/missing.pt`, readiness stayed zero while live
  OpenCV, deterministic jam and ML continued. The service health endpoint stayed
  healthy; the unavailable-model alert reached Incident Receiver and resolved
  after the real model was restored.
- A separate live MQTT subscriber received a genuine person-zone safety event
  after model recovery: confidence 0.9046, box `[402,71,562,302]`. Normal was restored.
  This independently checks the safety-subscription block added to the integration runner.

## Performance

The final offline person-zone benchmark measured **60.0 ms mean warm inference**,
50.6–116.1 ms over 20 runs at 640 input size, CPU device and two PyTorch threads.
An earlier run under a different concurrent load measured 84.4 ms over ten runs;
the mixed-scene check measured 76.0 ms over three. These are measured PyTorch wall
times rather than upstream ONNX benchmark numbers.

On the final live RTSP pipeline, a 100-frame observation measured **77.0 ms mean
inference** and **1.91 successful inferences/s**, close to the configured target
of 2/s. The RTSP reader decoded 100 frames in 9.45s; the slightly greater-than-10
reported fps includes initial capture buffering, not a higher publisher rate.
FFmpeg separately decoded **30 actual HLS frames over 3.00s** at about 9.8 fps
and 0.985× realtime. Raw RTSP/HLS remained decodable while YOLO ran; browser
playback smoothness was not manually assessed.

The image inspection reported approximately **1.41 GB** for the shared image
and **2.60 GB** for the CV image (uncompressed decimal bytes). Only the CV image
adds PyTorch/Ultralytics. The default weights are 5,544,453 bytes and are pinned
by SHA-256 in `tools/fetch_yolo.py`.

Two single-sample Docker stats observations of the CV container in normal flow
were 7.58% CPU / 70.42 MiB with YOLO disabled and 60.11% CPU / 313.5 MiB with
YOLO enabled (annotation enabled in both). Docker CPU percentage is approximately
100% per occupied logical CPU. These are host-load-dependent samples, not a
controlled CPU utilization benchmark or a memory upper bound.

## Limits

- This is an educational person-zone demonstration, not a safety system.
  It uses bounding-box intersection, no certified interlock or PPE recognition.
- Results come from actual inference. Recognition can miss moving, occluded,
  rotated or small objects; there is no factory-defect training or general box class.
- `fallen-object` and `crowded-line` are visual scenarios, without invented
  semantic fallen/crowded classes or alerts. Repeated observations are not tracking.
- Boxes are reused between sampled inferences and expire after three seconds.
  Snapshot/video freshness does not certify camera quality or end-to-end safety.
- Real inference was validated on Linux ARM64 Docker Desktop. Native macOS,
  Windows and amd64 runtime performance were not measured. PowerShell wrappers
  were retained; PowerShell is not installed on this host.
- Unit execution emits an upstream Starlette warning about its current httpx
  TestClient compatibility; tests pass with the repository's pinned dependencies.
- Ultralytics and the weights retain AGPL-3.0; combined distribution must respect
  upstream license/source obligations. Original project MIT licensing is retained.
- The initial image build needs Internet access for dependencies and the model;
  runtime rendering/inference is local, including when networking is disabled.

## Reproduce from the repository root

```bash
docker compose up -d --build
make validate
make test
make yolo-test
./scripts/labctl.sh object-mix
./scripts/labctl.sh person-zone
# Open http://localhost:8083/annotated.mjpg and http://localhost:3000
# Observe events with the existing tools/mqtt_tail.py client if desired.
./scripts/labctl.sh jam
./scripts/labctl.sh normal
make smoke
python3 scripts/integration_test.py
```

Optional model validation with networking disabled, after the build:

```bash
docker run --rm --network none computer-vision-cv:local python /tools/yolo_test.py
```
