import json
import logging
import time
from prometheus_client import Counter, Gauge, start_http_server
from common.config import TELEMETRY_TOPIC
from common.mqtt import start_client, publish, close
from common.runtime import STOP, setup
from services.ml_anomaly.model import train, infer

LOG = logging.getLogger(__name__)
READY = Gauge("ml_model_ready", "IsolationForest training complete")
ANOMALY = Gauge("ml_anomaly_detected", "Last inference is anomalous; inspect input age")
SCORE = Gauge("ml_anomaly_score", "Negative decision_function; positive is anomalous")
TOTAL = Counter("ml_anomalies", "Anomalous telemetry samples")
UPDATED = Gauge("ml_last_input_timestamp_seconds", "Last successfully inferred input receipt time")
ERRORS = Counter("ml_invalid_messages", "Rejected telemetry payloads")


def main():
    start_http_server(9103)
    model = train()
    READY.set(1)
    LOG.info("IsolationForest trained seed=42 samples=4000")
    previous = None

    def received(client, userdata, message):
        nonlocal previous
        try:
            payload = json.loads(message.payload)
            score, anomaly = infer(model, payload["values"])
            SCORE.set(score)
            ANOMALY.set(anomaly)
            UPDATED.set(time.time())
            if anomaly:
                TOTAL.inc()
            if previous != anomaly:
                LOG.info("ML anomaly=%s score=%.4f values=%s", anomaly, score, payload["values"])
            previous = anomaly
            publish(client, "factory/line1/ml/anomaly", {"timestamp": time.time(),
                    "input_timestamp": payload.get("timestamp"), "anomaly": anomaly, "score": score})
        except (ValueError, TypeError, KeyError):
            ERRORS.inc()
            LOG.exception("Invalid telemetry message")

    client = start_client("ml-anomaly", received, TELEMETRY_TOPIC)
    try:
        STOP.wait()
    finally:
        close(client)


if __name__ == "__main__":
    setup()
    main()
