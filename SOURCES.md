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
