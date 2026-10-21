"""Build-time download of the official AGPL-3.0 model, with pinned SHA-256."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

URL = 'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt'
# Filled from the upstream release artifact, never inferred at runtime.
SHA256 = '9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='/models/yolo26n.pt')
    args = parser.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(URL,timeout=120) as response:
        content = response.read()
    digest = hashlib.sha256(content).hexdigest()
    if digest != SHA256:
        raise ValueError(f'YOLO weight SHA-256 mismatch: {digest}')
    target.write_bytes(content)
    print(f'Downloaded {target.name} bytes={len(content)} sha256={digest}')


if __name__ == '__main__':
    main()
