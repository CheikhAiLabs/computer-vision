# Computer Vision — Industrial AI & OT Monitoring Platform

> A fully local industrial AI simulation combining computer vision, OPC-UA, MQTT, machine learning, observability and incident management.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer_Vision-5C3EE8?logo=opencv&logoColor=white)
![OPC-UA](https://img.shields.io/badge/OPC--UA-Industrial_Telemetry-455A64)
![Prometheus](https://img.shields.io/badge/Prometheus-Metrics-E6522C?logo=prometheus&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-Observability-F46800?logo=grafana&logoColor=white)
[![License: MIT](https://img.shields.io/badge/License-MIT-22A559)](LICENSE)

**[Overview](#overview) · [Architecture](#architecture) · [Quick start](#quick-start) · [Services / URLs](#services-and-interfaces) · [Demo](#demo) · [Scenarios](#failure-scenarios) · [Tests](#validation)**

## Overview

This project connects a simulated production line to an operational monitoring stack. A Python PLC exposes machine data through OPC-UA, a synthetic camera publishes real RTSP video, and edge services turn telemetry and images into MQTT events. Local machine learning detects unusual process data, while Prometheus, Grafana, Loki and Alertmanager bring together metrics, logs, alerts and incident notifications.

The environment runs in Docker Compose with separate OT and application networks. It is designed to demonstrate the engineering work between a sensor reading and an actionable incident: protocol integration, video processing, service recovery, data freshness and fault diagnosis.

The original idea was inspired by modern industrial AI and computer vision platforms, including systems developed by companies such as Cerrion. This repository is an independent personal project built from scratch for learning, experimentation and portfolio purposes. It has no affiliation with that company and contains none of its proprietary code, architecture, models, datasets or internal information.

**No cloud account, paid API, external model service or API key is required.** The first build downloads open-source dependencies; runtime processing and inference stay local.

## 💡 Why I Built This

I built this project to explore the intersection of cloud engineering, DevOps, SRE, machine learning and industrial systems. I wanted an end-to-end environment where industrial telemetry, computer vision, networking, observability and incident response work together.

It helps me deepen hands-on knowledge of industrial AI, computer vision, OPC-UA and OT networks, local ML inference, observability and infrastructure troubleshooting.

## 🎥 What the platform simulates

Products move along a synthetic conveyor while two complementary views of the line are monitored:

- **Machine telemetry:** conveyor speed, motor temperature, vibration, production count, blocked sensor, quality score and line status.
- **Camera observations:** bottles, cups, parcels and a person-zone demonstration, plus red jam obstruction, reduced brightness, blur, lens obstruction and stream loss.

OpenCV analyzes decoded video frames while a local YOLO26n model detects semantic objects. An IsolationForest model evaluates incoming process telemetry. Prometheus evaluates alert rules, Alertmanager delivers firing and resolved notifications, and a local FastAPI receiver records their latest state. Grafana provides a provisioned view of the process, network health, anomalies, incidents and container logs.

### Architecture

```mermaid
flowchart LR
    subgraph OT["Factory / OT sources"]
        PLC["Simulated PLC"]
        Camera["Synthetic camera · OpenCV + FFmpeg"]
        Media["MediaMTX"]
        Camera -->|RTSP publish| Media
    end

    subgraph Edge["Edge processing"]
        Bridge["OPC-UA telemetry bridge"]
        CV["OpenCV frame acquisition"]
        Classical["Classical CV · jam / image health"]
        YOLO["YOLO26n · classes / boxes / confidence"]
        Preview["Annotated HTTP MJPEG"]
    end

    subgraph App["Application services"]
        MQTT["Mosquitto MQTT"]
        ML["IsolationForest"]
        Incident["Incident receiver"]
    end

    subgraph Observability["Observability"]
        Prom["Prometheus"]
        AM["Alertmanager"]
        Grafana["Grafana"]
        Alloy["Grafana Alloy"]
        Loki["Loki"]
    end

    PLC -->|OPC-UA reads| Bridge
    Media -->|RTSP frames| CV
    Bridge -->|Telemetry| MQTT
    CV --> Classical
    CV -->|Every 5th frame · separate worker| YOLO
    Classical -->|Existing anomaly events| MQTT
    YOLO -->|Detections / restricted-zone demo events| MQTT
    CV --> Preview
    YOLO --> Preview
    MQTT -->|Telemetry| ML
    ML -->|Anomaly events| MQTT
    PLC -. Metrics .-> Prom
    Camera -. Metrics .-> Prom
    Bridge -. Metrics .-> Prom
    CV -. Metrics .-> Prom
    ML -. Metrics .-> Prom
    Incident -. Metrics .-> Prom
    Prom -->|Alerts| AM
    AM -->|Webhook| Incident
    Prom -->|Metrics| Grafana
    Logs["Docker container logs"] --> Alloy --> Loki --> Grafana
```

`opcua-sim`, `camera-sim` and `mediamtx` live on **`ot_net`**. The bridge and CV detector join both **`ot_net`** and **`cloud_net`**; backend services primarily use `cloud_net`. Prometheus, Blackbox Exporter and the optional tools container also join both networks to observe OT endpoints.

This makes it possible to disconnect an edge service from OT while preserving its application connection and leaving the PLC running. Docker networks demonstrate logical segmentation; they do not replace industrial firewalls, VLANs or a plant DMZ.

## Engineering focus

| Area | Demonstrated capabilities |
|---|---|
| Industrial IoT / OT | OPC-UA address spaces, dynamic namespace resolution, subscriptions, secure channels and network-path isolation |
| Computer vision / ML | RTSP decoding, interpretable image statistics, reproducible model training and per-message inference |
| DevOps / platform engineering | Containerized Python services, Compose networks, persistent volumes, automatic provisioning and CI checks |
| SRE / incident response | Dependency retries, freshness metrics, HTTP/TCP probes, alert routing, log correlation and recovery testing |

## Quick start

### Requirements

- Docker Engine with Compose **v2.17 or later** and BuildKit, or current Docker Desktop (the CV build uses an additional service build context).
- Plan for approximately **6–8 GB of memory** available to Docker and several GB of disk space.
- Git to clone the repository. **Python 3 on the host is needed only for the scenario scripts and integration runner**, not for the main stack.
- Internet access for the initial image and package downloads.

Replace `<repository-url>` with this repository's actual clone URL:

```bash
git clone <repository-url>
cd computer-vision
docker compose up -d --build
docker compose ps
docker compose --profile tools run --rm tools python /tools/smoke_test.py
```

Allow services to initialize before exploring the dashboard. The smoke test retries checks and expects the platform to be in its normal state.

Open **[Grafana](http://localhost:3000)** and sign in with **`admin` / `admin`**. The **Industrial Computer Vision & OT Lab** dashboard and its Prometheus/Loki data sources are provisioned automatically. The dashboard UID is `industrial-computer-vision`.

No `.env` file is required. [.env.example](.env.example) documents optional project, logging, YOLO and preview settings. YOLO is enabled by default; weights download only during the image build. All published ports bind to **127.0.0.1**; the credentials are for local use only.

<a id="demo"></a>

## 📸 Demo

Prepare a live production jam for screenshots:

```bash
./scripts/demo_screenshots.sh jam
```

The helper starts the stack, records a normal baseline, invokes the existing scenario controller, and waits for jam metrics and firing alerts before printing the camera, Grafana, Alertmanager and incident URLs. It prepares the demo; screenshots are captured manually. Python 3 and Docker are required.

**Screenshot captures are not included yet.** The intended gallery follows the incident from the camera to operational impact and alert propagation:

| View | What to capture | Save as |
|---|---|---|
| Synthetic camera | A red obstruction on the conveyor during a production jam | `docs/images/camera-jam.png` |
| Grafana | Blocked line, conveyor speed drop, increased vibration, reduced quality and CV/ML anomalies | `docs/images/grafana-jam.png` |
| Alertmanager | Firing production, vision and ML alerts | `docs/images/alertmanager-jam.png` |

<!-- SCREENSHOT GALLERY: Enable only after all three real PNG files exist.
Replace the pending-images note and checklist above with this gallery.

### Production jam detected by the synthetic camera

![Synthetic conveyor with a red obstruction during a production jam](docs/images/camera-jam.png)

A visible obstruction connects the camera scene to the simulated blocked-line condition.

### Operational impact in Grafana

![Grafana dashboard showing process degradation and CV and ML anomalies](docs/images/grafana-jam.png)

Process metrics, vision signals and ML inference show the operational impact of the same incident.

### Alert propagation

![Alertmanager showing firing production jam, computer vision and ML alerts](docs/images/alertmanager-jam.png)

Firing alerts make the detected conditions visible to the incident-response workflow.
-->

See the [capture guide](docs/images/README.md) for exact views, Grafana settings and gallery activation. On macOS, `./scripts/demo_screenshots.sh jam --open` optionally opens the URLs. Windows users can run `./scripts/demo_screenshots.ps1 jam`.

When finished, run `./scripts/demo_screenshots.sh normal` (or the PowerShell equivalent). The helper leaves the jam active until you restore normal operation.

## ▶️ Demo Flow

Open the [camera view](http://localhost:8888/line1/), Grafana and the [incident feed](http://localhost:8090/alerts), then run from the started stack:

```bash
./scripts/labctl.sh normal
./scripts/labctl.sh jam
```

The conveyor slows, the blocked sensor activates and a red object appears in the video. CV detects the object; ML can flag the changed process telemetry. Allow roughly 40 seconds for the relevant alerts to reach the incident receiver.

Restore normal operation:

```bash
./scripts/labctl.sh normal
```

On Windows, use `./scripts/labctl.ps1 jam` and `./scripts/labctl.ps1 normal` in PowerShell. Both wrappers call the same Python controller.

## Services and interfaces

The default stack contains **14 running services**, plus an on-demand `tools` service.

| Service | Role | Local interface / published ports |
|---|---|---|
| `opcua-sim` | PLC simulation and control | OPC-UA `4840` · [API docs](http://localhost:8081/docs) · [metrics](http://localhost:9101/metrics) |
| `camera-sim` | Synthetic conveyor video | [API docs](http://localhost:8082/docs) · [metrics](http://localhost:9105/metrics) |
| `mediamtx` | RTSP and HLS distribution | RTSP `8554` · [HLS video](http://localhost:8888/line1/) |
| `telemetry-bridge` | OPC-UA reads → MQTT | [Metrics](http://localhost:9102/metrics) |
| `cv-detector` | OpenCV + local YOLO → MQTT and metrics | [Annotated MJPEG](http://localhost:8083/annotated.mjpg) · [JPEG snapshot](http://localhost:8083/snapshot.jpg) · [health](http://localhost:8083/healthz) · [metrics](http://localhost:9104/metrics) |
| `ml-anomaly` | Telemetry inference → MQTT and metrics | [Metrics](http://localhost:9103/metrics) |
| `mqtt` | Eclipse Mosquitto broker | MQTT `1883` |
| `prometheus` | Metrics and alert evaluation | [localhost:9090](http://localhost:9090) |
| `blackbox-exporter` | HTTP and TCP probes | [localhost:9115](http://localhost:9115) |
| `alertmanager` | Alert grouping and webhook delivery | [localhost:9093](http://localhost:9093) |
| `incident-receiver` | Latest firing/resolved incident states | [Alerts](http://localhost:8090/alerts) · [API docs](http://localhost:8090/docs) · [metrics](http://localhost:9106/metrics) |
| `loki` | Local log storage | [Readiness](http://localhost:3100/ready) |
| `alloy` | Docker log discovery and collection | [localhost:12345](http://localhost:12345) |
| `grafana` | Provisioned operations dashboard | [localhost:3000](http://localhost:3000) |
| `tools` | Protocol clients and smoke tests | Compose profile `tools`; no published ports |

Open the HTTP links in a browser. Grafana uses **`admin` / `admin`**. Loki exposes a readiness endpoint; browse its logs through Grafana Explore using the provisioned Loki data source. The bridge and ML service expose metrics rather than a separate web interface.

Application metrics are available at `/metrics` on ports `9101`–`9106`. MQTT and OPC-UA require compatible protocol clients; RTSP can be opened in VLC or another RTSP player:

```text
OPC-UA  opc.tcp://localhost:4840/computer-vision/server/
MQTT    mqtt://localhost:1883
RTSP    rtsp://localhost:8554/line1
HLS     http://localhost:8888/line1/
MJPEG   http://localhost:8083/annotated.mjpg
JPEG    http://localhost:8083/snapshot.jpg
```

HLS playback has more latency than RTSP and depends on browser support.

## Failure scenarios

Run any command below with `./scripts/labctl.sh <command>` or `./scripts/labctl.ps1 <command>`.

| Command | Behavior |
|---|---|
| `normal` | Start PLC, camera and edges as needed; restore both OT connections; clear overrides and reset both scenarios |
| `object-mix` | Moving photographic bottles and cups plus rendered parcels; actual bottle/cup inference verified |
| `person-zone` | A photographic person sprite overlaps the configured restricted zone; actual person inference triggers demo events |
| `fallen-object` | A bottle lies rotated on the walkway; visual scenario only, no pretrained “fallen” class or alert |
| `crowded-line` | Denser product spacing and more visible objects; counts are semantic observations, no tracking or crowd alert |
| `jam` | Block the line, slow the conveyor, increase vibration, reduce quality and display a red obstruction |
| `overheat` | Set motor temperature to 95 °C; keep the camera normal |
| `vibration` | Set motor vibration to 1.2 g |
| `quality-drop` | Reduce quality score to 0.65 |
| `stopped` | Stop the conveyor and set line status to `STOPPED` |
| `dirty-camera`, `dark-camera`, `blur-camera` | Change the camera image without modifying PLC telemetry |
| `camera-offline`, `camera-online` | Stop/start the camera simulator while MediaMTX stays available |
| `opcua-down`, `opcua-up` | Stop/start the PLC simulator; exercise bridge reconnection |
| `edge-ot-cut`, `edge-ot-restore` | Remove/restore only the bridge's OT network connection |
| `cv-ot-cut`, `cv-ot-restore` | Remove/restore only the CV detector's OT network connection |
| `state` | Show Compose service status and PLC/camera API state |

PLC scenarios reset the camera to normal except for `jam`, which changes both sources. Network operations discover resources through Compose labels rather than fixed container names.

For a network diagnosis example, inject `edge-ot-cut` and compare `bridge_opcua_connected` with `probe_success{instance="opcua-sim:4840"}`. The bridge loses access even though Blackbox can still reach the PLC. **Endpoint availability and end-to-end connectivity are different signals.**

<details>
<summary>Manual PLC overrides and dependency recovery</summary>

```bash
curl -X POST http://localhost:8081/override/MotorTemperature \
  -H 'Content-Type: application/json' \
  -d '{"value":105}'

curl -X DELETE http://localhost:8081/overrides
```

The PLC and camera APIs also expose `GET /healthz`, `GET /state` and `POST /scenario/{name}`. The camera health endpoint describes its control plane; `camera_publisher_up` and `cv_stream_up` describe video-path health.

To restore after manually stopping MQTT or MediaMTX, start those dependencies before resetting the scenarios:

```bash
docker compose start mediamtx mqtt
./scripts/labctl.sh normal
```

</details>

## 🧠 Multi-layer Detection

The platform combines three complementary detection layers:

1. **Classical Computer Vision:** deterministic OpenCV statistics detect the synthetic red jam, darkness, blur, dirty/obstructed view and stream loss. These checks still run on every acquired frame, independently of YOLO.
2. **Deep Learning vision:** CPU-only YOLO26n produces real object classes, bounding boxes and confidence scores from decoded RTSP frames. A configurable rectangle demonstrates person/zone intersection. It does not detect jams, blocked products or factory defects.
3. **Telemetry anomaly detection:** IsolationForest evaluates PLC measurements from OPC-UA via MQTT. It detects unusual combinations of process values independently of camera recognition.

The original raw camera path stays available. `ENABLE_YOLO=false`, missing weights, initialization errors and inference exceptions leave the OpenCV and telemetry pipelines operating. No detection is generated from the scenario name or a hard-coded object location.

## Computer vision and machine learning

### Frame analysis

The camera generates **640 × 360 frames at 10 fps**. FFmpeg encodes H.264 and publishes to MediaMTX over RTSP/TCP; the CV service analyzes actual decoded frames with OpenCV.

| Condition | Detection method | Metric |
|---|---|---|
| Red obstruction | HSV red-pixel ratio > 0.025 | `cv_red_pixel_ratio` |
| Dark image | Mean brightness < 25 | `cv_frame_brightness` |
| Blurred image | Laplacian variance < 30, when not dark | `cv_laplacian_variance` |
| Dirty/obstructed view | Center-to-border brightness ratio < 0.25, when not dark | `cv_center_to_border_brightness_ratio` |
| Stream unavailable | Frame acquisition fails | `cv_stream_up` |

These CPU-friendly heuristics are interpretable and calibrated to the synthetic scene. They are not a trained object-detection model or a claim of accuracy on real factory cameras.

### Local YOLO object detection

The [Ultralytics YOLO26n](https://docs.ultralytics.com/models/yolo26/) nano detector is pretrained on COCO. Its inspected class list has 80 classes, including `person`, `bottle`, `cup`, `backpack`, `handbag` and `suitcase`; these six form the fixed application allowlist. COCO has no general `box`, `jam` or factory-defect class. Bottles, cups and the person sprite have been verified with actual local model inference; parcels are rendered scene content, without a promised YOLO label.

The camera composites small transparent photographic cutouts over a steel conveyor, animated belt seams, product shadows, rails, fasteners and a striped service walkway. It retains the 640×360 / 10 fps format and every existing scenario. Assets ship locally; provenance, public-domain/CC0 status and modification details are in [SOURCES.md](SOURCES.md).

| Environment variable | Default | Meaning |
|---|---|---|
| `ENABLE_YOLO` | `true` | Enable optional semantic inference |
| `YOLO_MODEL` | `/models/yolo26n.pt` | Existing local weights; no runtime auto-download |
| `YOLO_CONFIDENCE` | `0.45` | Minimum model confidence |
| `YOLO_EVERY_N_FRAMES` | `5` | Submit every fifth acquired frame, about 2 inferences/s at 10 fps |
| `YOLO_THREADS` | `2` | PyTorch CPU thread limit |
| `YOLO_RESTRICTED_ZONE` | `0.60,0.16,0.98,0.86` | Normalized rectangle `x1,y1,x2,y2` |
| `YOLO_RESULT_TTL_SECONDS` | `3` | Maximum source-frame age for displayed detections and current gauges |
| `ENABLE_ANNOTATED_STREAM` | `true` | Optional HTTP JPEG/MJPEG annotation; liveness remains available when off |

A separate worker consumes a capacity-one latest-frame slot. Slow inference replaces queued work rather than building a backlog. OpenCV acquisition, heuristics and anomaly publishing continue at the original rate. Model/inference failures log an error, set readiness to zero, clear current detections and retry after five seconds. Invalid configuration leaves YOLO unavailable while OpenCV continues. Stream loss invalidates both queued and in-flight results.

A person's inferred bounding box intersecting the restricted rectangle with positive area publishes `person_in_restricted_zone`. This uses bounding-box overlap, not segmentation or a person's precise foot position. **This is an educational demonstration, not a real safety system.** It has no certified safety function, interlock or accuracy guarantee.

The annotated view is [HTTP MJPEG](http://localhost:8083/annotated.mjpg), with a [JPEG snapshot](http://localhost:8083/snapshot.jpg). It shows boxes, class/confidence, the zone and current OpenCV reasons. Box positions come from the latest sampled inference and can lag moving objects; their age is displayed. Frames expire after three seconds, and stale snapshots return HTTP 503. The original [raw HLS stream](http://localhost:8888/line1/) and `rtsp://localhost:8554/line1` remain available. A second RTSP publisher is unnecessary for this preview.

Run the demo from this repository root. Execute scenario changes one at a time and observe the video/dashboard between them; allow about 20–30 seconds for alerts to propagate. The [complete test sequence](#validation) also covers repository checks and automated failure recovery.

```bash
docker compose up -d --build
make normal
make yolo-test
make object-mix
make person-zone
# Open http://localhost:8083/annotated.mjpg and Grafana's YOLO section.
# Allow ~20 seconds for the person alert to reach the incident feed.
make crowded-line
make fallen-object
make jam
make normal
make smoke
```

The PowerShell wrapper accepts the same commands. `tools/yolo_test.py` uses the actual local model and licensed person-zone scene, requires a genuine person/zone result, prints all model classes and reports warm inference latency. It is optional and excluded from normal unit tests/CI; `--image /path/to/local/image` supports another licensed local test image.

To switch YOLO off without editing files:

```bash
ENABLE_YOLO=false docker compose up -d --no-deps --no-build cv-detector
./scripts/labctl.sh jam
# Observe the raw/annotated video or CV metrics before restoring normal.
./scripts/labctl.sh normal
docker compose --profile tools run --rm tools python /tools/smoke_test.py
# Restore the default (unless your .env overrides it):
ENABLE_YOLO=true docker compose up -d --no-deps --no-build cv-detector
docker compose --profile tools run --rm tools python /tools/smoke_test.py
```

In PowerShell use `$env:ENABLE_YOLO='false'` before `docker compose up -d --no-deps --no-build cv-detector`, then set it to `'true'` to restore.

The two Dockerfiles and dependency files form a shared base and a CV extension:

| File | Purpose |
|---|---|
| `requirements.txt` | Shared Python dependencies used by the existing services |
| `Dockerfile` | Builds the shared non-root Python image using `requirements.txt` |
| `requirements-cv.txt` | Additional Ultralytics, PyTorch and Torchvision dependencies; their versions are defined here |
| `Dockerfile.cv` | Extends the shared image through Compose's `lab-base` build context, installs CPU wheels and downloads the checksummed model at build time |

Other services keep using the shared image; only the CV image adds headless Ultralytics, CPU PyTorch and the ~5.3 MiB model. Python remains 3.12; no CUDA image or GPU is required. Build-time weights have a pinned SHA-256. `YOLO_OFFLINE=true`, disabled integrations, local-file loading and array inputs keep runtime inference offline. To use other trusted weights, mount them into the CV container and set `YOLO_MODEL` to that path.

On the validated Docker ARM64 host, live inference averaged about **77 ms at 1.9 inferences/s** while raw video remained near its 10 fps target. An isolated 20-run CPU benchmark averaged 60 ms; CPU and memory cost vary with host load. See the [measurement record](docs/YOLO_VALIDATION.md) for methods, image sizes and limits.

### Process anomaly detection

The ML service trains **scikit-learn IsolationForest** at startup on 4,000 synthetic normal observations with seed `42`, 160 trees and contamination `0.12`. It evaluates each telemetry message using `ConveyorSpeed`, `MotorTemperature`, `Vibration`, `QualityScore` and `BlockedSensor`.

`ml_anomaly_score` is the negative of `decision_function`: **positive values indicate an anomaly**. It is not a probability. The contamination setting selects a sensitive boundary within the training distribution; it does not represent a measured factory failure rate.

False positives and false negatives are possible, including intermittent misses during overheating. Deterministic process alerts remain independent of ML. The model demonstrates local inference integrated into an OT pipeline, not production-grade anomaly detection.

## OPC-UA and MQTT

The PLC address space is `Objects → Factory → Line1`, under namespace **`urn:computer-vision:factory`**. Each variable has a stable String NodeId such as `ns=<resolved-index>;s=Line1.MotorTemperature`; clients resolve the namespace index dynamically.

| Variable | Typical normal value |
|---|---|
| `ConveyorSpeed` | ~1.20 m/s |
| `MotorTemperature` | ~45 °C |
| `Vibration` | ~0.12 g |
| `BottleCount` | Increases during production; resets on PLC restart |
| `BlockedSensor` | `false` |
| `QualityScore` | ~0.985 |
| `LineStatus` | `RUNNING` |

The bridge performs grouped reads every second. A separate diagnostic client demonstrates OPC-UA subscriptions and monitored-item notifications.

| MQTT topic | Publisher | Payload purpose |
|---|---|---|
| `factory/line1/telemetry` | `telemetry-bridge` | Timestamp, site, line and process values |
| `factory/line1/cv/anomaly` | `cv-detector` | Anomaly status, reasons and frame metrics when available |
| `factory/line1/cv/detections` | `cv-detector` | UTC timestamp, source-frame time, site, line, model and inferred class/confidence/pixel `xyxy` boxes; empty lists are valid |
| `factory/line1/cv/safety` | `cv-detector` | Actual inferred person/zone overlap event; repeated each positive sampled inference, not a tracked unique person |
| `factory/line1/ml/anomaly` | `ml-anomaly` | Anomaly status, score and input timestamp |

Use the tools container for protocol inspection:

```bash
docker compose --profile tools run --rm tools python /tools/opcua_browse.py
docker compose --profile tools run --rm tools python /tools/opcua_secure_read.py
```

For continuous output, run `opcua_subscribe.py` or `mqtt_tail.py` with the same command prefix; stop with Ctrl+C.

<details>
<summary>Secure OPC-UA and certificate pinning</summary>

The server supports `NoSecurity`, `Basic256Sha256 Sign` and `Basic256Sha256 SignAndEncrypt`. Server certificates are generated automatically in a persistent volume; tools generate their own client certificates. Server private keys are not shared with clients.

The secure-read tool establishes a real SignAndEncrypt channel. By default, it discovers the server certificate rather than independently verifying its identity. The server also uses permissive demo certificate handling, not a production trust list.

To supply a server certificate explicitly:

```bash
mkdir -p certs
docker compose cp opcua-sim:/certs/server.der certs/server.der
docker compose --profile tools run --rm \
  -v "$PWD/certs/server.der:/trust/server.der:ro" \
  -e OPCUA_SERVER_CERT=/trust/server.der \
  tools python /tools/opcua_secure_read.py
```

To exercise pinned Sign/SignAndEncrypt reads and a mismatched-certificate failure:

```bash
docker compose --profile tools run --rm \
  -v "$PWD/certs/server.der:/trust/server.der:ro" \
  tools python /tools/opcua_security_test.py
```

The self-signed certificates last one year; automatic renewal and production PKI lifecycle management are not implemented. A successful TCP probe does not prove that an OPC-UA session or certificate check will succeed.

</details>

## 📊 Observability and incident flow

The provisioned dashboard groups **Factory Process**, **OT / OPC-UA**, **Computer Vision**, **Machine Learning**, **Network / Connectivity**, **Alerts / Incidents**, a Docker logs panel and a compact **YOLO / Object Detection** section.

Prometheus scrapes every five seconds. Its 13 rules cover connection loss, overheating, vibration, blocked production, quality degradation, camera loss, CV/ML anomalies, stale telemetry, failed probes and unavailable exporters. The original rules wait 10–20 seconds before firing; `YOLOModelUnavailable` waits 60 seconds with YOLO enabled and readiness zero, and `PersonInRestrictedZone` waits five seconds with fresh inference and a live stream. No alert fires just because a bottle is detected; Alertmanager groups notifications and sends both firing and resolved webhooks to `/webhook` on the incident receiver.

Blackbox probes the PLC, camera and incident HTTP APIs, Loki readiness, and TCP listeners for OPC-UA, RTSP and MQTT. Alloy discovers labeled Docker containers and sends their logs to Loki with `compose_service`, `project`, `container` and `platform` labels.

YOLO exports `yolo_enabled`, `yolo_model_ready`, `yolo_inference_duration_seconds` (histogram), `yolo_objects_detected`, `yolo_detections_total`, `yolo_last_inference_timestamp_seconds`, `yolo_restricted_zone_violation` and `yolo_class_detections{class="..."}`. Only the six fixed class names are labels; boxes, scores and object IDs never become labels. `yolo_detections_total` counts repeated observations across inference frames, **not unique products**. Current counts and zone state clear on stale results, errors and stream loss; readiness indicates a loaded model, so inspect inference age as well.

Grafana adds readiness, current/total detections, mean latency, person count, zone violation, inference age and effective inference frequency. Inference age is empty until the first successful result. The original panels remain intact.

### Useful queries

| Question | PromQL |
|---|---|
| What is the motor temperature? | `factory_motor_temperature_c` |
| Can the bridge read the PLC? | `bridge_opcua_connected` |
| Is video being decoded? | `cv_stream_up` |
| Is ML flagging the latest sample? | `ml_anomaly_detected` |
| Is ML input fresh? | `time() - ml_last_input_timestamp_seconds` |
| How fast is telemetry being published? | `rate(bridge_messages_published_total[1m])` |
| Which endpoint probes fail? | `probe_success == 0` |
| How many incidents are firing? | `incident_active_alerts` |

In Grafana Explore, select Loki and filter by service:

```logql
{platform="docker", compose_service="telemetry-bridge"}
```

ML and image statistics retain their last values during input loss. Check `ml_last_input_timestamp_seconds`, `cv_stream_up` and `cv_last_frame_timestamp_seconds` before interpreting them. The ML alert excludes stale input; a separate rule covers missing telemetry.

Prometheus and Loki use local volumes with seven-day retention. The incident receiver keeps the latest state of up to 1,000 alert identities **in memory**, so its records are lost on restart. `factory_bottle_count_total` is a gauge of the simulated PLC counter, despite its suffix; `factory_line_status` encodes stopped/running/blocked as `0`/`1`/`2`.

## Repository structure

```text
.
├── docker-compose.yml        # Services, localhost ports, volumes and networks
├── Dockerfile                # Shared non-root Python image
├── Dockerfile.cv             # Dedicated CPU YOLO image and build-time weights
├── requirements-cv.txt       # Headless Ultralytics and CPU Torch versions
├── assets/objects/           # Redistributable local bottle, cup and person PNGs
├── requirements.txt          # Pinned shared Python dependencies
├── common/                   # Wire contracts, MQTT, certificates and logging
├── services/
│   ├── opcua_sim/            # PLC and FastAPI controls
│   ├── camera_sim/           # Animated conveyor and FFmpeg publisher
│   ├── telemetry_bridge/     # OPC-UA → MQTT
│   ├── cv_detector/          # RTSP decoding and image analysis
│   ├── ml_anomaly/           # IsolationForest training and inference
│   └── incident_receiver/    # Alertmanager webhook intake
├── tools/                    # Protocol clients and smoke tests
├── scripts/                  # Scenario control, demo preparation and validation
├── tests/                    # Vision and ML unit tests
├── grafana/                  # Dashboard and data-source provisioning
├── prometheus/               # Scrapes, alerts and Blackbox configuration
├── alertmanager/             # Notification routing
├── alloy/                    # Docker log collection
├── loki/                     # Local log storage configuration
├── mediamtx/                 # RTSP/HLS configuration
├── mosquitto/                # MQTT broker configuration
├── docs/
│   ├── VALIDATION.md         # Recorded runtime results and test limitations
│   └── images/              # Screenshot capture guide and intended PNG location
├── .github/workflows/ci.yml   # Static, unit and configuration checks
├── .env.example              # Optional Compose project name and log level
├── Makefile                  # Build, lifecycle and scenario shortcuts
├── SOURCES.md                # Official upstream references
└── LICENSE                   # MIT license for original project code
```

## Validation

The [original validation record](docs/VALIDATION.md) preserves the baseline results. The [YOLO upgrade record](docs/YOLO_VALIDATION.md) documents the changed files, 21 unit tests, actual offline inference, measured latency and extended failure/recovery checks on macOS arm64 with Docker Desktop. It also records untested areas, including Windows execution and browser visual rendering. These are recorded results, not a live CI status badge.

### Complete automated test sequence

Run from the repository root with Docker running. These Make targets require `make`, a POSIX shell and Python 3 for scenario control/integration:

```bash
docker compose up -d --build
docker compose ps

# Offline structure/syntax checks and unit tests; no model download in unit tests.
make validate
make test

# Actual local CPU model inference on the licensed demo scene.
make yolo-test

# End-to-end checks expect a normal, running stack.
make normal
make smoke

# Inject local faults, verify alerts/recovery, then restore normal.
make integration
```

`make validate` checks Compose configuration, Python syntax, YAML/JSON, dashboard structure, shell syntax, networks and localhost port bindings. `make test` runs the offline unit suite. `make yolo-test` requires the CV image's actual local weights and reports model classes, detections and inference latency.

`make smoke` checks HTTP/TCP endpoints, real OPC-UA reads and encryption, MQTT telemetry/anomaly/detection messages, RTSP decoding, raw HLS player/playlist, optional annotated JPEG/MJPEG decoding, YOLO readiness/freshness when enabled, Prometheus targets/probes, Grafana provisioning and Alloy-to-Loki logs. Failures return a nonzero exit code.

`make integration` temporarily disrupts the local stack and restores normal in a `finally` block. It covers process faults, actual MQTT safety messages and person-zone incident firing/resolution when YOLO is enabled, camera degradation, PLC/camera outages, OT network cuts, MediaMTX loss and MQTT loss. Mocked unit tests cover disabled/failed YOLO, parsing, zones, payloads, metrics, stale/in-flight invalidation and preview expiry without loading Ultralytics or weights.

Without Make, run the same checks directly (these commands also work in PowerShell when Python 3 is available):

```bash
docker compose config --quiet
docker compose --profile tools run --rm -v "${PWD}:/workspace:ro" tools python /workspace/scripts/validate.py
docker compose --profile tools run --rm -v "${PWD}/tests:/tests:ro" tools python -m unittest discover -s /tests -v
docker compose exec cv-detector python /tools/yolo_test.py
python3 scripts/labctl.py normal
docker compose --profile tools run --rm tools python /tools/smoke_test.py
python3 scripts/integration_test.py
```

Use `python` instead of `python3` if that is your Windows Python 3 executable. The static validator runs inside the Linux tools container, which supplies Bash. Scenario commands are also available through `./scripts/labctl.ps1 <command>`.

### Manual scenarios and live inspection

Open the [annotated camera](http://localhost:8083/annotated.mjpg), [raw HLS camera](http://localhost:8888/line1/) and [Grafana](http://localhost:3000). Execute the following commands individually, allowing about 20–30 seconds between scenario changes:

```bash
make object-mix
make person-zone
make crowded-line
make fallen-object
make jam
make dark-camera
make blur-camera
make dirty-camera
make camera-offline
make camera-online
make normal
```

`person-zone` should produce real person detections and, after the alert delay, a restricted-zone incident. `jam` should trigger the existing OpenCV red-obstruction detector even if YOLO detects nothing. `fallen-object` and `crowded-line` change the scene without promising dedicated semantic alerts. Use the [YOLO toggle commands](#local-yolo-object-detection) to repeat the jam and smoke checks with YOLO disabled.

In a separate terminal, watch actual MQTT messages; `cv/detections` and `cv/safety` appear under `factory/line1/` when applicable:

```bash
docker compose --profile tools run --rm tools python /tools/mqtt_tail.py
```

Follow camera and detector logs in another terminal:

```bash
docker compose logs -f --tail=100 cv-detector camera-sim
```

Stop either live observer with **Ctrl+C**. To inspect CV/YOLO metrics and validate monitoring configuration directly:

```bash
curl -fsS http://localhost:9104/metrics | grep -E '^(yolo_|cv_stream_up)'
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
```

The curl/grep example uses a POSIX shell. On PowerShell, open the [CV metrics endpoint](http://localhost:9104/metrics) in a browser instead. Restore the baseline with `make normal` or `./scripts/labctl.ps1 normal` before rerunning smoke checks.

The [GitHub Actions workflow](.github/workflows/ci.yml) defines Python, YAML, JSON, shell/PowerShell, Compose, unit-test and monitoring configuration checks. Full runtime integration is a local test; the workflow itself has not yet been verified on GitHub.

## Operations and security

The bridge, CV detector and camera publisher retry temporary dependency failures. MQTT clients reconnect with bounded queues and a 1–15 second retry delay. This demonstrates service resilience, but does not guarantee lossless buffering or exactly-once delivery.

**This configuration is intended for local development and demonstration.** It includes anonymous MQTT, `admin/admin` Grafana credentials, self-signed OPC-UA certificates and unauthenticated internal APIs. Python services run without root; Alloy accesses the Docker socket. A `:ro` socket mount does **not** make Docker API operations read-only.

Production deployment would require managed secrets, authentication and RBAC, MQTT TLS/mTLS, certificate trust and rotation, OT firewall/ACL policies, restricted Docker access, image hardening and scanning, backups and audit logging. The shared Python image retains the existing CV/ML dependencies; PyTorch and Ultralytics are isolated in a dedicated CV image.

Useful lifecycle commands:

```bash
docker compose logs -f --tail=100 telemetry-bridge cv-detector
docker compose down
```

`docker compose down` retains named volumes. **`docker compose down -v` or `make clean` deletes stored data and demo server certificates.** Other shortcuts include `make build`, `make up`, `make ps`, `make logs`, `make smoke` and scenario targets such as `make jam`.

## 🗺️ Roadmap

These are **future improvements**, not features currently implemented:

- Build a custom industrial YOLO dataset and fine-tune factory-specific defects.
- Add multi-object tracking and unique product counting.
- Support a real webcam or IP camera.
- Optimize inference with ONNX / TensorRT and a model registry.
- Add multi-camera correlation.
- Integrate a real OPC-UA device or PLC.
- Extend the simulation to multiple production lines and sites.
- Add GPU-accelerated inference.
- Build richer Grafana incident views and persistent incident history.
- Add historical ML/anomaly analysis and a more complete MLOps/model lifecycle workflow.
- Introduce more advanced OT network failure scenarios.

## License and references

Original project code is released under the [MIT License](LICENSE). Ultralytics code and weights are AGPL-3.0, so the combined YOLO-enabled distribution has upstream corresponding-source obligations and must not be described as MIT-only. The photographic assets are public domain/CC0. Other third-party components retain their upstream licenses. See [SOURCES.md](SOURCES.md) for official documentation and project references.
