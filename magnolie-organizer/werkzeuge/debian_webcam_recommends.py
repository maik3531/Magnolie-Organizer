#!/usr/bin/env python3
"""DEB recommendation follows the actual optional camera payload composition."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_optional_phone import read_composition


def webcam_recommends(data_directory):
    return 'v4l2loopback-dkms' if read_composition(data_directory)['phone_camera'] else ''


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_directory',type=Path)
    print(webcam_recommends(parser.parse_args().data_directory))
