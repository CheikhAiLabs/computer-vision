"""Verify pinned server identity, Sign and SignAndEncrypt, and reject a wrong key."""
import asyncio
from asyncua import Client, ua
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
from common.certs import ensure_certificate
from common.config import OPCUA_URL, nodes_for


async def connect(server_cert, mode):
    cert, key, uri = ensure_certificate('client','/tmp/security-test')
    client = Client(OPCUA_URL, timeout=3)
    client.application_uri = uri
    await client.set_security(SecurityPolicyBasic256Sha256, certificate=str(cert),
        private_key=str(key), server_certificate=str(server_cert), mode=mode)
    async with client:
        nodes = await nodes_for(client)
        value = await nodes['MotorTemperature'].read_value()
        assert isinstance(value,float)
        print(f'PASS pinned {mode.name}: MotorTemperature={value}')


async def main():
    for mode in [ua.MessageSecurityMode.Sign, ua.MessageSecurityMode.SignAndEncrypt]:
        await connect('/trust/server.der',mode)
    wrong, _, _ = ensure_certificate('wrong-server','/tmp/security-test')
    try:
        await asyncio.wait_for(connect(wrong,ua.MessageSecurityMode.SignAndEncrypt),15)
    except Exception as exc:
        print(f'PASS wrong server certificate rejected: {type(exc).__name__}: {exc}')
    else:
        raise AssertionError('Wrong server certificate unexpectedly accepted')


if __name__ == '__main__':
    asyncio.run(main())
