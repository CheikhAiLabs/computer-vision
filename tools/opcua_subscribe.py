import asyncio
from asyncua import Client
from common.config import OPCUA_URL, nodes_for


class Handler:
    def datachange_notification(self, node, value, data):
        print(f"{node.nodeid.to_string()} = {value}", flush=True)


async def main():
    async with Client(OPCUA_URL, timeout=5) as client:
        subscription = await client.create_subscription(500, Handler())
        try:
            await subscription.subscribe_data_change(list((await nodes_for(client)).values()))
            print("Subscription active; Ctrl+C to stop", flush=True)
            await asyncio.Event().wait()
        finally:
            await subscription.delete()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Subscription closed")
