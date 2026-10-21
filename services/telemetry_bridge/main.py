import asyncio
import logging
import time
from asyncua import Client
from prometheus_client import Counter, Gauge, start_http_server
from common.config import OPCUA_URL, TELEMETRY_TOPIC, nodes_for
from common.mqtt import start_client, publish, close
from common.runtime import STOP, setup

LOG = logging.getLogger(__name__)
CONNECTED = Gauge("bridge_opcua_connected", "OPC-UA read session healthy")
PUBLISHED = Counter("bridge_messages_published", "Telemetry accepted by MQTT client")
RECONNECTS = Counter("bridge_opcua_reconnects", "OPC-UA connection attempts")
UPDATED = Gauge("bridge_last_update_timestamp_seconds", "Last successful OPC-UA read")


async def main():
    start_http_server(9102)
    mqtt = start_client("telemetry-bridge")
    try:
        while not STOP.is_set():
            try:
                RECONNECTS.inc()
                async with Client(OPCUA_URL, timeout=4) as client:
                    nodes = await nodes_for(client)
                    LOG.info("OPC-UA connected endpoint=%s", OPCUA_URL)
                    while not STOP.is_set():
                        values = await client.read_values(list(nodes.values()))
                        now = time.time()
                        CONNECTED.set(1)
                        UPDATED.set(now)
                        if publish(mqtt, TELEMETRY_TOPIC, {"timestamp": now, "site": "local",
                                   "line": "line1", "values": dict(zip(nodes, values))}):
                            PUBLISHED.inc()
                        await asyncio.sleep(1)
            except Exception:
                LOG.exception("OPC-UA unavailable; retrying in 2 seconds")
                CONNECTED.set(0)
                await asyncio.sleep(2)
    finally:
        CONNECTED.set(0)
        close(mqtt)


if __name__ == "__main__":
    setup()
    asyncio.run(main())
