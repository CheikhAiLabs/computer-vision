"""Actual signed/encrypted channel with optional out-of-band server certificate pin."""
import asyncio
import os
from asyncua import Client, ua
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
from common.certs import ensure_certificate
from common.config import OPCUA_URL, nodes_for


async def main():
    cert, key, uri = ensure_certificate("client", "/tmp/client-certs")
    client = Client(OPCUA_URL, timeout=5)
    client.application_uri = uri
    trusted_cert = os.getenv("OPCUA_SERVER_CERT")
    await client.set_security(SecurityPolicyBasic256Sha256, certificate=str(cert),
        private_key=str(key), server_certificate=trusted_cert,
        mode=ua.MessageSecurityMode.SignAndEncrypt)
    async with client:
        print("REAL OPC-UA Basic256Sha256 / SignAndEncrypt connection established")
        print("Server trust:", trusted_cert or "DEMO discovery; identity not independently verified")
        for name, node in (await nodes_for(client)).items():
            print(f"{name} = {await node.read_value()}")


if __name__ == "__main__":
    asyncio.run(main())
