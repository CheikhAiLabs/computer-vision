import asyncio
from contextlib import asynccontextmanager
import logging
import math
import os
import time
from asyncua import Server, ua
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from prometheus_client import Gauge, start_http_server
import uvicorn
from common.certs import ensure_certificate
from common.config import NAMESPACE
from common.runtime import setup
from services.opcua_sim.process import sample, SCENARIOS
from common.line import sensor_index

LOG = logging.getLogger(__name__)
scenario = "normal"
overrides = {}
state = sample(0, "normal", 0)
ready = False
update_task = None
METRICS = {key: Gauge(metric, help_text) for key, metric, help_text in [
    ("ConveyorSpeed", "factory_conveyor_speed_mps", "Conveyor speed in metres per second"),
    ("MotorTemperature", "factory_motor_temperature_c", "Motor temperature in Celsius"),
    ("Vibration", "factory_motor_vibration_g", "Motor vibration in g"),
    ("BottleCount", "factory_bottle_count_total", "Simulated lifetime count; resets at PLC restart"),
    ("BlockedSensor", "factory_blocked_sensor", "Blocked sensor boolean"),
    ("QualityScore", "factory_quality_score", "Quality fraction"),
    ("LineStatus", "factory_line_status", "RUNNING=1 STOPPED=0 BLOCKED=2")
]}


async def update(nodes):
    global state
    tick, count = 0, 0
    previous_sensor = sensor_index(time.time())
    while True:
        current_sensor = sensor_index(time.time())
        pulses = max(0, current_sensor - previous_sensor)
        previous_sensor = current_sensor
        if scenario not in {'jam', 'stopped'}:
            # Independent simulated photoeye; count-mismatch models a bouncing sensor.
            count += pulses * (3 if scenario == 'count-mismatch' else 1)
        state = sample(tick, scenario, count)
        state.update(overrides)
        for name, node in nodes.items():
            await node.write_value(state[name])
            value = {"STOPPED": 0, "RUNNING": 1, "BLOCKED": 2}[state[name]] if name == "LineStatus" else state[name]
            METRICS[name].set(value)
        count = int(state['BottleCount'])
        tick += 1
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app):
    global ready, update_task
    start_http_server(int(os.getenv("METRICS_PORT", "9101")))
    server = Server()
    await server.init()
    server.set_endpoint("opc.tcp://0.0.0.0:4840/computer-vision/server/")
    cert, key, uri = ensure_certificate("server")
    await server.set_application_uri(uri)
    await server.load_certificate(str(cert))
    await server.load_private_key(str(key))
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity,
        ua.SecurityPolicyType.Basic256Sha256_Sign, ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
    idx = await server.register_namespace(NAMESPACE)
    factory = await server.nodes.objects.add_object(ua.NodeId("Factory", idx), "Factory")
    line = await factory.add_object(ua.NodeId("Line1", idx), "Line1")
    nodes = {name: await line.add_variable(ua.NodeId(f"Line1.{name}", idx), name, value)
             for name, value in state.items()}
    async with server:
        task = asyncio.create_task(update(nodes))
        update_task = task
        ready = True
        LOG.info("PLC ready namespace=%s security=NoSecurity,Sign,SignAndEncrypt", idx)
        try:
            yield
        finally:
            ready = False
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="computer-vision PLC", lifespan=lifespan)


@app.get("/healthz")
def health():
    if not ready or update_task is None or update_task.done():
        raise HTTPException(503, "PLC initializing")
    return {"status": "ok"}


@app.get("/state")
def get_state():
    return {"scenario": scenario, "values": state, "overrides": overrides}


@app.post("/scenario/{name}")
def set_scenario(name: str):
    global scenario
    if name not in SCENARIOS:
        raise HTTPException(400, "Unknown scenario")
    scenario = name
    overrides.clear()
    LOG.info("PLC scenario=%s", name)
    return {"scenario": scenario}


class Override(BaseModel):
    value: float | int | bool | str


@app.post("/override/{variable}")
def override(variable: str, body: Override):
    if variable not in state:
        raise HTTPException(404, "Unknown variable")
    value = body.value
    if variable == "LineStatus":
        valid = value in ("RUNNING", "STOPPED", "BLOCKED")
    elif variable == "BlockedSensor":
        valid = isinstance(value, bool)
    else:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        if valid:
            valid = value >= 0 and (variable != "QualityScore" or value <= 1)
            if variable == "BottleCount":
                valid = valid and float(value).is_integer()
                value = int(value)
            else:
                value = float(value)
    if not valid:
        raise HTTPException(422, "Invalid type, range or non-finite value")
    overrides[variable] = value
    LOG.info("PLC override variable=%s value=%s", variable, value)
    return {"variable": variable, "value": value}


@app.delete("/overrides")
def clear():
    overrides.clear()
    return {"overrides": {}}


if __name__ == "__main__":
    setup()
    uvicorn.run(app, host="0.0.0.0", port=8081)
