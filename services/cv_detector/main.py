import logging
import os
import time
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
import cv2
from prometheus_client import Gauge, start_http_server
from common.config import RTSP_URL
from common.mqtt import start_client, publish, close
from common.runtime import STOP, setup
from services.cv_detector.vision import analyze

LOG = logging.getLogger(__name__)
UP = Gauge("cv_stream_up", "Recent frame successfully decoded")
ANOMALY = Gauge("cv_anomaly_detected", "One or more CV or stream anomalies")
UPDATED = Gauge("cv_last_frame_timestamp_seconds", "Last decoded frame time")
METRICS = {name: Gauge("cv_" + name, name.replace("_", " ")) for name in (
    "red_pixel_ratio", "frame_brightness", "laplacian_variance", "center_to_border_brightness_ratio")}


def open_capture():
    return cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG,
        [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4000])


def main():
    start_http_server(9104)
    mqtt = start_client("cv-detector")
    previous = None
    last_publish = 0.0
    try:
        while not STOP.is_set():
            capture = open_capture()
            try:
                while not STOP.is_set():
                    ok, frame = capture.read()
                    if not ok:
                        UP.set(0)
                        ANOMALY.set(1)
                        LOG.warning("RTSP unavailable; retrying target=%s", RTSP_URL)
                        publish(mqtt, "factory/line1/cv/anomaly", {"timestamp": time.time(),
                            "anomaly": True, "reasons": ["stream-unavailable"]})
                        break
                    UP.set(1)
                    UPDATED.set(time.time())
                    values, reasons = analyze(frame)
                    for name, value in values.items():
                        METRICS[name].set(value)
                    ANOMALY.set(bool(reasons))
                    if reasons != previous:
                        LOG.info("CV state reasons=%s metrics=%s", reasons, values)
                    if reasons != previous or time.monotonic() - last_publish >= 5:
                        publish(mqtt, "factory/line1/cv/anomaly", {"timestamp": time.time(),
                            "anomaly": bool(reasons), "reasons": reasons, "metrics": values})
                        last_publish = time.monotonic()
                    previous = reasons
            except Exception:
                UP.set(0)
                ANOMALY.set(1)
                LOG.exception("CV processing failed; reconnecting")
            finally:
                capture.release()
            STOP.wait(2)
    finally:
        close(mqtt)


if __name__ == "__main__":
    setup()
    main()
