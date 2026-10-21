"""Real end-to-end checks. Run against a restored normal lab; fail nonzero."""
import asyncio
import json
import os
import socket
import threading
import time
import uuid
import httpx
from asyncua import Client
from common.config import OPCUA_URL, RTSP_URL, nodes_for
from common.mqtt import start_client, close
from services.cv_detector.main import open_capture
from prometheus_client.parser import text_string_to_metric_families
import cv2
import numpy as np
from opcua_secure_read import main as secure_read


def http_check(url):
    response = httpx.get(url, timeout=5)
    response.raise_for_status()
    return response


def retry(label, check, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            check()
            print(f"PASS {label}", flush=True)
            return
        except Exception as exc:
            last = exc
            time.sleep(2)
    raise RuntimeError(f"FAIL {label}: {last}")


async def opcua_read():
    async with Client(OPCUA_URL, timeout=5) as client:
        nodes = await nodes_for(client)
        values = await client.read_values(list(nodes.values()))
        assert len(values) == 7, values
        assert isinstance(values[0], float), values


def mqtt_check():
    yolo_enabled = cv_metrics().get("yolo_enabled") == 1
    event = threading.Event()
    received = set()
    token = uuid.uuid4().hex
    roundtrip_topic = "factory/line1/smoke/" + token
    def on_message(client, userdata, message):
        payload = json.loads(message.payload)
        if message.topic.endswith("/telemetry"):
            assert "MotorTemperature" in payload["values"]
        if message.topic == roundtrip_topic:
            assert payload == {"token": token}, payload
        received.add(message.topic)
        if message.topic == "factory/line1/cv/detections":
            assert isinstance(payload['detections'],list)
            assert payload['model'] and payload['site'] == 'local' and payload['line'] == 'line1'
            for detection in payload['detections']:
                assert len(detection['bbox']) == 4 and 0 <= detection['confidence'] <= 1
        required = {"factory/line1/telemetry", "factory/line1/ml/anomaly", "factory/line1/cv/anomaly", roundtrip_topic}
        if yolo_enabled:
            required.add("factory/line1/cv/detections")
        if required <= received:
            event.set()
    client = start_client("smoke-" + uuid.uuid4().hex[:8], on_message, "factory/line1/#")
    try:
        deadline = time.monotonic() + 10
        while not client.is_connected() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert client.is_connected(), "MQTT connection timeout"
        sent = client.publish(roundtrip_topic, json.dumps({"token": token}), qos=1)
        sent.wait_for_publish(timeout=5)
        assert sent.is_published(), "MQTT publish was not acknowledged"
        assert event.wait(20), f"MQTT topics observed: {received}"
    finally:
        close(client)


def cv_metrics():
    return {sample.name: sample.value
            for family in text_string_to_metric_families(http_check('http://cv-detector:9104/metrics').text)
            for sample in family.samples if not sample.labels}


def yolo_check():
    http_check('http://cv-detector:8083/healthz')
    metrics = cv_metrics()
    assert metrics['yolo_enabled'] in (0,1)
    if metrics['yolo_enabled'] == 1:
        assert metrics['yolo_model_ready'] == 1, metrics
        age = time.time()-metrics['yolo_last_inference_timestamp_seconds']
        assert 0 <= age < 10, age


def annotated_check():
    # Read runtime capability from the CV exporter; tools env may differ from CV.
    if cv_metrics().get('cv_annotated_enabled') == 1:
        response = http_check('http://cv-detector:8083/snapshot.jpg')
        frame = cv2.imdecode(np.frombuffer(response.content,np.uint8),cv2.IMREAD_COLOR)
        assert frame is not None and frame.shape[:2] == (360,640)
        with httpx.stream('GET','http://cv-detector:8083/annotated.mjpg',timeout=10) as stream:
            stream.raise_for_status()
            content = b''
            for chunk in stream.iter_bytes():
                content += chunk
                start, end = content.find(b'\xff\xd8'), content.find(b'\xff\xd9')
                if 0 <= start < end:
                    assert cv2.imdecode(np.frombuffer(content[start:end+2],np.uint8),cv2.IMREAD_COLOR) is not None
                    break
                assert len(content) < 2_000_000, 'No JPEG frame in MJPEG response'


def rtsp_check():
    capture = open_capture()
    try:
        ok, frame = capture.read()
        assert ok and frame is not None and frame.shape[0] > 0, "No RTSP frame decoded"
    finally:
        capture.release()


def hls_check():
    with httpx.Client(follow_redirects=True,timeout=10) as client:
        response = client.get('http://mediamtx:8888/line1/')
        response.raise_for_status()
        response = client.get('http://mediamtx:8888/line1/index.m3u8')
        response.raise_for_status()
        assert '#EXTM3U' in response.text, response.text[:200]


def prometheus_check():
    targets = http_check("http://prometheus:9090/api/v1/targets").json()["data"]["activeTargets"]
    assert len(targets) >= 14, f"Only {len(targets)} scrape targets"
    bad = [(t["labels"], t["lastError"]) for t in targets if t["health"] != "up"]
    assert not bad, bad
    for query, expected in [("bridge_opcua_connected", 1), ("cv_stream_up", 1),
                            ("ml_model_ready", 1), ("cv_anomaly_detected", 0)]:
        result = httpx.get("http://prometheus:9090/api/v1/query", params={"query": query}, timeout=5).json()["data"]["result"]
        assert result and all(float(x["value"][1]) == expected for x in result), (query, result)
    result = httpx.get("http://prometheus:9090/api/v1/query", params={"query": "probe_success"}, timeout=5).json()["data"]["result"]
    assert len(result) == 7 and all(float(x["value"][1]) == 1 for x in result), result


def grafana_check():
    response = httpx.get("http://grafana:3000/api/dashboards/uid/industrial-computer-vision", auth=("admin", "admin"), timeout=5)
    response.raise_for_status()
    assert any(p["title"] == "YOLO / Object Detection" for p in response.json()["dashboard"]["panels"])
    sources = httpx.get("http://grafana:3000/api/datasources", auth=("admin", "admin"), timeout=5).json()
    assert {"prometheus", "loki"} <= {s["uid"] for s in sources}


def logs_check():
    result = httpx.get("http://loki:3100/loki/api/v1/query_range",
        params={"query": '{platform="docker",compose_service="telemetry-bridge"}', "limit": 5}, timeout=10)
    result.raise_for_status()
    assert result.json()["data"]["result"], "No bridge logs collected by Alloy"


def main():
    for host, port, path in [("opcua-sim",8081,"/healthz"),("camera-sim",8082,"/healthz"),
            ("incident-receiver",8090,"/healthz"),("prometheus",9090,"/-/healthy"),
            ("alertmanager",9093,"/-/healthy"),("loki",3100,"/ready"),
            ("grafana",3000,"/api/health"),("alloy",12345,"/-/ready")]:
        retry(f"HTTP {host}", lambda h=host,p=port,u=path: http_check(f"http://{h}:{p}{u}"))
    for host, port in [("opcua-sim",4840),("mqtt",1883),("mediamtx",8554)]:
        def tcp(h=host,p=port):
            with socket.create_connection((h,p),timeout=5):
                pass
        retry(f"TCP {host}:{port}", tcp)
    retry("OPC-UA read", lambda: asyncio.run(opcua_read()))
    retry("OPC-UA SignAndEncrypt read", lambda: asyncio.run(secure_read()))
    retry("MQTT telemetry + ML + CV messages", mqtt_check)
    retry("RTSP frame decoding", rtsp_check)
    retry("Raw HLS player and playlist", hls_check)
    retry("CV health and optional YOLO readiness/freshness", yolo_check)
    retry("Optional annotated HTTP JPEG/MJPEG decoding", annotated_check)
    retry("Prometheus targets, metrics and probes", prometheus_check)
    retry("Grafana dashboard and data sources", grafana_check)
    retry("Alloy → Loki Docker logs", logs_check)
    print("All smoke checks passed", flush=True)


if __name__ == "__main__":
    main()
