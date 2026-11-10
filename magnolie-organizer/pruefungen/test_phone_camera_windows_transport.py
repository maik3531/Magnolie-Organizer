"""Actual Python sender → actual .NET decoder. No signed parent or native device."""
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'magnolie-organizer/bin'))
from magnolie_phone_camera_transport import WebcamMediaSocket


def test_actual_python_sender_reaches_dotnet_original_receiver_with_shared_vectors():
    dotnet = os.environ.get('MAGNOLIE_DOTNET')
    if not dotnet:
        pytest.skip('Explicit existing MAGNOLIE_DOTNET test SDK required; never install one')
    dll = ROOT / 'magnolie-organizer-windows/tests/bin/Release/net8.0/CoreTests.dll'
    assert dll.is_file(), 'Build the existing CoreTests lane first'
    fixture = json.loads((ROOT / 'contracts/phone-webcam-media-v1-vectors.json').read_text())
    process = subprocess.Popen([dotnet, str(dll), '--phone-webcam-media-host'],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 8)
        assert ready, 'Bounded .NET media host did not announce its port'
        first = process.stdout.readline()
        port = json.loads(first)['port']
        with socket.create_connection(('127.0.0.1', port), timeout=2) as original:
            sender = WebcamMediaSocket(original, fixture['session'], bytes.fromhex(fixture['secret']), lambda: None, sending=True)
            try:
                for packet in fixture['packets']:
                    sender.send('video' if packet['track'] == 1 else 'audio', packet['track_sequence'],
                        packet['pts_us'], bytes([packet['fill']]) * packet['bytes'])
                output, error = process.communicate(timeout=8)
                assert process.returncode == 0, error
                frames = [json.loads(line) for line in output.splitlines()]
                assert len(frames) == 3
                for packet, frame in zip(fixture['packets'], frames):
                    assert frame == dict(video=packet['track'] == 1, sequence=packet['track_sequence'],
                        pts_us=packet['pts_us'], bytes=packet['bytes'],
                        sha256=hashlib.sha256(bytes([packet['fill']]) * packet['bytes']).hexdigest())
            finally:
                sender.close()
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
        for stream in (process.stdout, process.stderr):
            if stream: stream.close()
