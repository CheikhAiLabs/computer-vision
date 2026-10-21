import asyncio
from asyncua import Client
from common.config import OPCUA_URL, NAMESPACE, nodes_for


async def main():
    async with Client(OPCUA_URL, timeout=5) as client:
        print(f"Connected: {OPCUA_URL}; namespace={NAMESPACE}")
        print("Objects:", [str(n.nodeid) for n in await client.nodes.objects.get_children()])
        for name, node in (await nodes_for(client)).items():
            print(f"{name:22s} {node.nodeid.to_string():45s} = {await node.read_value()}")


if __name__ == "__main__":
    asyncio.run(main())
