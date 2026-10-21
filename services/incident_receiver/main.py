from collections import OrderedDict
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, start_http_server
import uvicorn
from common.runtime import setup

LOG = logging.getLogger(__name__)
NOTIFICATIONS = Counter("incident_notifications", "Alertmanager webhook deliveries", ["status"])
ACTIVE = Gauge("incident_active_alerts", "Current firing alerts retained in memory")
alerts = OrderedDict()


@asynccontextmanager
async def lifespan(app):
    start_http_server(9106)
    yield


app = FastAPI(title="computer-vision incidents", lifespan=lifespan)


class Alert(BaseModel):
    status: str
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str
    endsAt: str = ""
    fingerprint: str = ""


class Webhook(BaseModel):
    status: str
    alerts: list[Alert]


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/alerts")
def get_alerts():
    return {"alerts": list(reversed(alerts.values())), "storage": "memory; latest 1000 identities"}


@app.post("/webhook")
def webhook(payload: Webhook):
    NOTIFICATIONS.labels(status="resolved" if payload.status == "resolved" else "firing").inc()
    for alert in payload.alerts:
        key = alert.fingerprint or str(sorted(alert.labels.items()))
        alerts[key] = {"alertname": alert.labels.get("alertname", "unknown"),
                      "severity": alert.labels.get("severity", "unknown"), **alert.model_dump()}
        alerts.move_to_end(key)
        LOG.info("Incident name=%s status=%s", alert.labels.get("alertname"), alert.status)
    while len(alerts) > 1000:
        alerts.popitem(last=False)
    ACTIVE.set(sum(a["status"] == "firing" for a in alerts.values()))
    return {"accepted": len(payload.alerts)}


if __name__ == "__main__":
    setup()
    uvicorn.run(app, host="0.0.0.0", port=8090)
