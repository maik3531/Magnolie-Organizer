#!/usr/bin/env python3
"""Copy the canonical QR interaction resources to both desktop and handbook web roots."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'magnolie-organizer/web'
    for target in (source, ROOT / 'magnolie-organizer-windows/app/web', ROOT / 'magnolie-handbuch/web'):
        if target != source:
            for name in ('qr-dialog.js', 'qr-dialog.css', 'qr-decoder.js', 'qr-decoder-LICENSE.txt'):
                (target / name).write_bytes((source / name).read_bytes())


if __name__ == '__main__':
    main()
