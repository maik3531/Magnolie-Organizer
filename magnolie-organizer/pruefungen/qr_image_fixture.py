"""Test-only RGBA input and digest; never emit decoded personal QR text."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'magnolie-organizer/bin'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--image', type=Path)
    source.add_argument('--text')
    args = parser.parse_args()
    if args.image:
        from magnolie_asset import read_asset
        import cv2
        import numpy
        data = read_asset(str(args.image), 1, 1)
        image = Image.open(io.BytesIO(data)).convert('RGBA')
        value, points, _ = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(numpy.frombuffer(data, dtype=numpy.uint8), cv2.IMREAD_COLOR))
        if points is None or not value:
            raise SystemExit('Test QR image could not be decoded')
    else:
        import qrcode
        value = args.text
        image = qrcode.make(value).convert('RGBA')
    print(json.dumps({'width': image.width, 'height': image.height,
        'pixels': base64.b64encode(image.tobytes()).decode('ascii'),
        'content_sha256': hashlib.sha256(value.encode('utf-8')).hexdigest()}))


if __name__ == '__main__':
    main()
