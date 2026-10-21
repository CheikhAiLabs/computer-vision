"""Optional local inference; latest-frame worker never blocks OpenCV acquisition."""
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
import os
from pathlib import Path
import threading
import time
from prometheus_client import Counter, Gauge, Histogram, REGISTRY

LOG = logging.getLogger(__name__)
CLASSES = ("person", "bottle", "backpack", "suitcase", "handbag", "cup")
DETECTIONS_TOPIC = "factory/line1/cv/detections"
SAFETY_TOPIC = "factory/line1/cv/safety"


def flag(name, default="true"):
    return os.getenv(name, default).lower() in {"true", "1", "yes"}


@dataclass(frozen=True)
class Settings:
    model: str = "/models/yolo26n.pt"
    confidence: float = 0.45
    every: int = 5
    zone: tuple = (0.60, 0.16, 0.98, 0.86)
    ttl: float = 3.0
    threads: int = 2

    def __post_init__(self):
        if not 0 < self.confidence <= 1 or self.every < 1 or self.threads < 1:
            raise ValueError("Invalid YOLO confidence, frame interval or thread count")
        if not math.isfinite(self.ttl) or self.ttl <= 0:
            raise ValueError("YOLO_RESULT_TTL_SECONDS must be positive and finite")
        if len(self.zone) != 4 or not (0 <= self.zone[0] < self.zone[2] <= 1
                                     and 0 <= self.zone[1] < self.zone[3] <= 1):
            raise ValueError("YOLO_RESTRICTED_ZONE requires normalized x1,y1,x2,y2")

    @classmethod
    def from_env(cls):
        return cls(model=os.getenv("YOLO_MODEL", cls.model),
                   confidence=float(os.getenv("YOLO_CONFIDENCE", "0.45")),
                   every=int(os.getenv("YOLO_EVERY_N_FRAMES", "5")),
                   zone=tuple(float(v) for v in os.getenv("YOLO_RESTRICTED_ZONE", "0.60,0.16,0.98,0.86").split(',')),
                   ttl=float(os.getenv("YOLO_RESULT_TTL_SECONDS", "3")),
                   threads=int(os.getenv("YOLO_THREADS", "2")))


def overlaps(bbox, zone, width, height):
    """Any positive-area rectangle intersection; touching edges do not count."""
    x1, y1, x2, y2 = bbox
    a, b, c, d = zone
    return min(x2, c*width) > max(x1, a*width) and min(y2, d*height) > max(y1, b*height)


def parse_results(results, width, height, confidence):
    detections = []
    for result in results:
        if result.boxes is None:
            continue
        for box, score, class_id in zip(result.boxes.xyxy.cpu().tolist(),
                                        result.boxes.conf.cpu().tolist(),
                                        result.boxes.cls.cpu().tolist()):
            if len(box) != 4 or not all(math.isfinite(v) for v in [*box, score, class_id]):
                continue
            name = result.names.get(int(class_id))
            if name not in CLASSES or class_id != int(class_id) or not confidence <= score <= 1:
                continue
            x1, y1, x2, y2 = box
            bbox = [round(max(0, min(width, x1))), round(max(0, min(height, y1))),
                    round(max(0, min(width, x2))), round(max(0, min(height, y2)))]
            if bbox[2] > bbox[0] and bbox[3] > bbox[1]:
                detections.append({"class": name, "confidence": float(score), "bbox": bbox})
    return detections


def messages(detections, settings, width, height, timestamp, source_timestamp):
    stamp = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    payload = {"timestamp": stamp, "source_timestamp": source_timestamp, "site": "local",
               "line": "line1", "model": Path(settings.model).name, "detections": detections}
    safety = [{"event": "person_in_restricted_zone", "timestamp": stamp,
               "source_timestamp": source_timestamp, "site": "local", "line": "line1",
               "model": Path(settings.model).name, **d}
              for d in detections if d['class'] == 'person'
              and overlaps(d['bbox'], settings.zone, width, height)]
    return payload, safety


class Metrics:
    def __init__(self, enabled, registry=REGISTRY):
        self.enabled = Gauge('yolo_enabled', 'YOLO configured on', registry=registry)
        self.ready = Gauge('yolo_model_ready', 'Local model loaded and usable', registry=registry)
        self.duration = Histogram('yolo_inference_duration_seconds', 'CPU predict and parse wall time',
                                  buckets=(.025,.05,.1,.2,.5,1,2,5), registry=registry)
        self.objects = Gauge('yolo_objects_detected', 'Objects in latest fresh inference', registry=registry)
        self.total = Counter('yolo_detections', 'Object observations; repeats are not unique objects', registry=registry)
        self.updated = Gauge('yolo_last_inference_timestamp_seconds', 'Last successful inference completion', registry=registry)
        self.violation = Gauge('yolo_restricted_zone_violation', 'Fresh person box overlaps demo zone', registry=registry)
        self.classes = Gauge('yolo_class_detections', 'Current objects by fixed supported class', ['class'], registry=registry)
        self.enabled.set(enabled)
        self.clear()

    def clear(self):
        self.objects.set(0)
        self.violation.set(0)
        for name in CLASSES:
            self.classes.labels(name).set(0)

    def record(self, detections, safety, timestamp, duration):
        self.duration.observe(duration)
        self.updated.set(timestamp)
        self.objects.set(len(detections))
        self.total.inc(len(detections))
        self.violation.set(bool(safety))
        for name in CLASSES:
            self.classes.labels(name).set(sum(d['class'] == name for d in detections))


def load_model(settings):
    # An explicit local-file check prevents Ultralytics' automatic weight download.
    if not Path(settings.model).is_file():
        raise FileNotFoundError(f"Local YOLO weights missing: {settings.model}; build the CV image or mount weights")
    os.environ.setdefault('YOLO_OFFLINE', 'true')
    os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
    os.environ.setdefault('YOLO_CONFIG_DIR', '/tmp/ultralytics')
    import torch
    from ultralytics import YOLO, settings as ultralytics_settings
    ultralytics_settings.update({key: False for key in (
        'sync', 'clearml', 'comet', 'dvc', 'mlflow', 'raytune', 'tensorboard', 'wandb')})
    torch.set_num_threads(settings.threads)
    model = YOLO(settings.model, task='detect')
    LOG.info('YOLO loaded model=%s supported classes=%s', settings.model, model.names)
    if 'person' not in model.names.values():
        raise ValueError('Model does not support the person class')
    return model


class Worker:
    def __init__(self, publish, enabled=None, settings=None, registry=REGISTRY, loader=load_model):
        self.enabled = flag('ENABLE_YOLO') if enabled is None else enabled
        self.settings = settings
        self.metrics = Metrics(self.enabled, registry)
        self.publish = publish
        self.loader = loader
        self.lock = threading.Condition()
        self.stop = threading.Event()
        self.pending = None
        self.latest = None
        self.generation = 0
        self.frames = 0
        self.thread = None

    def start(self):
        if self.enabled:
            self.thread = threading.Thread(target=self.run, name='yolo-inference', daemon=True)
            self.thread.start()

    def submit(self, frame, timestamp):
        with self.lock:
            self.frames += 1
            if self.enabled and self.settings and self.frames % self.settings.every == 0:
                # Capacity one: replace queued work instead of accumulating lag.
                self.pending = (frame.copy(), timestamp, self.generation)
                self.lock.notify()

    def invalidate(self):
        with self.lock:
            self.generation += 1
            self.pending = self.latest = None
            self.metrics.clear()

    def snapshot(self):
        with self.lock:
            if self.latest and time.time() - self.latest['source_timestamp'] <= self.settings.ttl:
                return self.latest
            self.latest = None
            self.metrics.clear()
            return None

    def run(self):
        try:
            self.settings = self.settings or Settings.from_env()
        except Exception:
            LOG.exception('Invalid YOLO configuration; OpenCV continues')
            return
        model = None
        while not self.stop.is_set():
            try:
                if model is None:
                    model = self.loader(self.settings)
                    self.metrics.ready.set(1)
                with self.lock:
                    self.lock.wait_for(lambda: self.pending is not None or self.stop.is_set(), timeout=1)
                    work, self.pending = self.pending, None
                if self.stop.is_set():
                    break
                if work is None:
                    self.snapshot()
                    continue
                frame, source_timestamp, generation = work
                if time.time() - source_timestamp > self.settings.ttl:
                    continue
                started = time.perf_counter()
                results = model.predict(frame, device='cpu', conf=self.settings.confidence,
                                        imgsz=640, verbose=False, save=False,
                                        classes=[i for i,n in model.names.items() if n in CLASSES])
                height, width = frame.shape[:2]
                detections = parse_results(results, width, height, self.settings.confidence)
                duration, now = time.perf_counter() - started, time.time()
                payload, safety = messages(detections, self.settings, width, height, now, source_timestamp)
                with self.lock:
                    if generation != self.generation or now - source_timestamp > self.settings.ttl:
                        continue
                    self.latest = payload
                    self.metrics.record(detections, safety, now, duration)
                    self.publish(DETECTIONS_TOPIC, payload)
                    for event in safety:
                        self.publish(SAFETY_TOPIC, event)
            except Exception:
                self.metrics.ready.set(0)
                self.invalidate()
                model = None
                LOG.exception('YOLO unavailable; OpenCV continues; retry in 5 seconds')
                self.stop.wait(5)

    def close(self):
        self.stop.set()
        with self.lock:
            self.lock.notify_all()
        if self.thread:
            self.thread.join(timeout=3)
        self.metrics.ready.set(0)
        self.invalidate()
