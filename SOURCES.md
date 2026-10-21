# Official upstream sources

This independent educational implementation uses the following open-source projects.
Dependencies retain their upstream licenses; the repository's MIT license covers its original code.
No proprietary Cerrion code, models or architecture are included.

| Project | Official documentation / source |
|---|---|
| Python | https://docs.python.org/3/ |
| asyncua | https://github.com/FreeOpcUa/opcua-asyncio |
| FastAPI | https://fastapi.tiangolo.com/ |
| Uvicorn | https://www.uvicorn.org/ |
| OpenCV | https://docs.opencv.org/4.x/ |
| NumPy | https://numpy.org/doc/ |
| FFmpeg | https://ffmpeg.org/ffmpeg.html |
| MediaMTX | https://mediamtx.org/docs/usage/publish |
| Eclipse Mosquitto | https://mosquitto.org/documentation/ |
| Eclipse Paho MQTT | https://eclipse.dev/paho/files/paho.mqtt.python/html/ |
| scikit-learn IsolationForest | https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html |
| Prometheus | https://prometheus.io/docs/introduction/overview/ |
| prometheus-client | https://prometheus.github.io/client_python/ |
| Alertmanager | https://prometheus.io/docs/alerting/latest/configuration/ |
| Blackbox Exporter | https://github.com/prometheus/blackbox_exporter |
| Grafana OSS | https://grafana.com/docs/grafana/latest/administration/provisioning/ |
| Grafana Loki | https://grafana.com/docs/loki/latest/configure/examples/ |
| Grafana Alloy | https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/ |
| Docker Compose | https://docs.docker.com/compose/ |
| cryptography | https://cryptography.io/en/latest/x509/tutorial/ |

Container versions were selected from official release metadata on 2026-10-21;
see `docker-compose.yml`. Direct Python dependencies are pinned in `requirements.txt`.
First build requires Internet access to public package/image repositories. Once built,
all lab processing and inference run locally without API keys or cloud services.

## YOLO model, runtime and local visual assets

| Repository file / component | Author / project | Source | License and modifications |
|---|---|---|---|
| `assets/objects/bottle.png` | Ranch9613 | [Cold drinking water bottle transparent.png](https://commons.wikimedia.org/wiki/File:Cold_drinking_water_bottle_transparent.png), [original](https://upload.wikimedia.org/wikipedia/commons/3/3c/Cold_drinking_water_bottle_transparent.png) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/); resized to 100×320, transparency retained |
| `assets/objects/person.png` | NASA; distributed by scikit-image | [Astronaut image and public-domain statement](https://scikit-image.org/docs/stable/api/skimage.data.html#skimage.data.astronaut), [original in scikit-image v0.25.2](https://github.com/scikit-image/scikit-image/blob/v0.25.2/skimage/data/astronaut.png) | Public domain, no known copyright restrictions; polygon background removal, resized to 256×256, suit recolored blue to preserve independent red-jam calibration. Photograph depicts Eileen Collins, used as an illustrative person sprite; no endorsement or industrial PPE claim |
| `assets/objects/cup.png` | Rachel Michetti; courtesy of Pikolo Espresso Bar, distributed by scikit-image | [Coffee image and CC0 statement](https://scikit-image.org/docs/stable/api/skimage.data.html#skimage.data.coffee), [original in scikit-image v0.25.2](https://github.com/scikit-image/scikit-image/blob/v0.25.2/skimage/data/coffee.png) | CC0; cup polygon cutout and resize; original ceramic colors retained |
| `/models/yolo26n.pt` (built image, not committed) | Ultralytics | [Official v8.4.0 release artifact](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt), [model documentation](https://docs.ultralytics.com/models/yolo26/) | AGPL-3.0; unmodified pretrained COCO weights, SHA-256 `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef` |
| `ultralytics-opencv-headless==8.4.183` | Ultralytics | [PyPI](https://pypi.org/project/ultralytics-opencv-headless/8.4.183/), [source and license](https://github.com/ultralytics/ultralytics) | AGPL-3.0, official headless distribution avoids conflicting OpenCV wheels |
| CPU PyTorch / Torchvision | PyTorch | [CPU installation](https://pytorch.org/get-started/locally/), [source](https://github.com/pytorch/pytorch) | BSD-style upstream licenses; no GPU dependency |

The assets above ship in this repository; camera rendering never downloads them.
Model download occurs only during the CV image build and checks a pinned digest.
Runtime model loading requires an existing local file and disables Ultralytics
network integrations and automatic dependency installation. `tools/yolo_test.py`
uses a locally rendered scene containing these same licensed assets.

The existing MIT license continues to cover original project code. Ultralytics
code and model weights retain AGPL-3.0. A combined YOLO-enabled distribution must
comply with its upstream license, including corresponding-source obligations;
it must not be represented as MIT-only. See the [upstream licensing explanation](https://www.ultralytics.com/license).

`scripts/prepare_assets.py` records the offline cutout/recolor/resize recipe; it takes the three original downloaded images as explicit local arguments.
