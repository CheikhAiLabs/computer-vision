"""Paho's background network loop retries initial and subsequent connections."""
import json
import logging
import os
import paho.mqtt.client as mqtt

LOG = logging.getLogger(__name__)


def start_client(name, on_message=None, topic=None):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=name)
    client.reconnect_delay_set(min_delay=1, max_delay=15)
    client.max_queued_messages_set(100)

    def connected(c, userdata, flags, reason, properties):
        if reason.is_failure:
            LOG.error("MQTT connection rejected: %s", reason)
        else:
            LOG.info("MQTT connected client=%s", name)
            if topic:
                c.subscribe(topic, qos=1)

    def disconnected(c, userdata, flags, reason, properties):
        if reason.is_failure:
            LOG.warning("MQTT disconnected client=%s reason=%s; will retry", name, reason)
        else:
            LOG.info("MQTT client=%s disconnected cleanly", name)

    client.on_connect = connected
    client.on_disconnect = disconnected
    if on_message:
        client.on_message = on_message
    client.enable_logger(LOG)
    client.connect_async(os.getenv("MQTT_HOST", "mqtt"), int(os.getenv("MQTT_PORT", "1883")), 15)
    client.loop_start()
    return client


def publish(client, topic, payload):
    result = client.publish(topic, json.dumps(payload, allow_nan=False), qos=1)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        LOG.warning("MQTT publish unavailable topic=%s rc=%s", topic, result.rc)
        return False
    return True


def close(client):
    client.disconnect()
    client.loop_stop()
