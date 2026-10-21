import json
from common.mqtt import start_client, close
from common.runtime import STOP, setup


def message(client, userdata, msg):
    try:
        payload = json.dumps(json.loads(msg.payload), indent=2)
    except (ValueError, UnicodeDecodeError):
        payload = repr(msg.payload)
    print(msg.topic, payload, flush=True)


if __name__ == "__main__":
    setup()
    client = start_client("tools-tail", message, "factory/line1/#")
    try:
        STOP.wait()
    finally:
        close(client)
