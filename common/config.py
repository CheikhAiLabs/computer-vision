"""Shared wire contract; namespace indexes are always resolved at runtime."""
import os

NAMESPACE = "urn:computer-vision:factory"
OPCUA_URL = os.getenv("OPCUA_URL", "opc.tcp://opcua-sim:4840/computer-vision/server/")
RTSP_URL = os.getenv("RTSP_URL", "rtsp://mediamtx:8554/line1")
VARIABLES = ("ConveyorSpeed", "MotorTemperature", "Vibration", "BottleCount",
             "BlockedSensor", "QualityScore", "LineStatus")
FEATURES = ("ConveyorSpeed", "MotorTemperature", "Vibration", "QualityScore", "BlockedSensor")
TELEMETRY_TOPIC = "factory/line1/telemetry"


async def nodes_for(client):
    from asyncua import ua
    index = await client.get_namespace_index(NAMESPACE)
    return {name: client.get_node(ua.NodeId(f"Line1.{name}", index)) for name in VARIABLES}
