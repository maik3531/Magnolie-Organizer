#!/usr/bin/env python3
"""Vendor the pinned Apache-2.0 jsQR decoder; no installation or runtime download."""
import argparse
import base64
import hashlib
import io
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
INTEGRITY = 'dxLob7q65Xg2DvstYkRpkYtmKm2sPJ9oFhrhmudT1dZvNFFTlroai3AWSpLey/w5vMcLBXRgOJsbXpdN9HzU/A=='


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    data = args.archive.read_bytes()
    if base64.b64encode(hashlib.sha512(data).digest()).decode() != INTEGRITY:
        raise SystemExit('Unexpected jsQR 1.4.0 archive digest')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member, output in (('package/dist/jsQR.js', 'qr-decoder.js'), ('package/LICENSE', 'qr-decoder-LICENSE.txt')):
            content = archive.extractfile(member).read()
            if output.endswith('LICENSE.txt'):
                content = content.rstrip(b'\r\n') + b'\n'
            if len(content) > 1024 * 1024:
                raise SystemExit('Unexpected decoder resource size')
            (ROOT / 'magnolie-organizer/web' / output).write_bytes(content)
    print('Vendored jsQR 1.4.0, Apache-2.0; verified npm SHA512 integrity')


if __name__ == '__main__':
    main()
