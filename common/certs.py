"""Local demo certificates only; private keys never leave their own container volume."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import socket
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


def ensure_certificate(role: str, directory="/certs"):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = root / f"{role}.der", root / f"{role}-key.pem"
    uri = f"urn:computer-vision:{role}"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path, uri
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"computer-vision {role}")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(uri),
                x509.DNSName("opcua-sim" if role == "server" else "tools"), x509.DNSName("localhost"), x509.DNSName(socket.gethostname())]), False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.KeyUsage(True, True, True, True, False, False, False, False, False), True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH,
                                                ExtendedKeyUsageOID.CLIENT_AUTH]), False)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.DER))
    return cert_path, key_path, uri
