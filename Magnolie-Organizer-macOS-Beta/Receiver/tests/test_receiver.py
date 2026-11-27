#!/usr/bin/env python3
"""Portable tests of the actual C++ IPC/store code, no AirPlay/device claim."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReceiverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="magnolie-receiver-test-")
        cls.executable = Path(cls.build.name) / "protocol-test"
        subprocess.run([
            os.environ.get("CXX", "c++"), "-std=c++11", "-pthread", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT), str(ROOT / "receiver_protocol.cpp"),
            str(ROOT / "receiver_registration.cpp"), str(ROOT / "tests/protocol_harness.cpp"),
            "-o", str(cls.executable),
        ], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def run_protocol(self, *args):
        child = subprocess.Popen([str(self.executable), *args], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Keep stdin open until normal completion: closing it is the stop command.
        code = child.wait(timeout=5)
        child.stdin.close()
        output = child.stdout.read()
        logs = child.stderr.read()
        child.stdout.close()
        child.stderr.close()
        return code, [json.loads(line) for line in output.splitlines()], logs

    def test_actual_protocol_and_media_lifecycle(self):
        code, frames, logs = self.run_protocol()
        self.assertEqual(code, 0)
        self.assertEqual(frames, [
            {"protocol": 1, "event": "ready"},
            {"protocol": 1, "event": "pin", "code": "0042"},
            {"protocol": 1, "event": "video"},
            {"protocol": 1, "event": "audio"},
            {"protocol": 1, "event": "disconnected"},
            {"protocol": 1, "event": "audio"},
            {"protocol": 1, "event": "disconnected"},
            {"protocol": 1, "event": "audio"},
            {"protocol": 1, "event": "disconnected"},
        ])
        self.assertIn(b"upstream raw log", logs)
        self.assertNotIn(b"0042", logs)

    def test_one_of_two_video_streams_ending_preserves_remaining_stream(self):
        code, frames, _ = self.run_protocol("overlapping")
        self.assertEqual(code, 0)
        self.assertEqual([frame["event"] for frame in frames],
                         ["ready", "video", "audio", "disconnected", "video", "disconnected"])

    def test_abandoned_pin_clears_only_after_last_control_connection(self):
        code, frames, _ = self.run_protocol("pair_cancel")
        self.assertEqual(code, 0)
        self.assertEqual(frames, [{"protocol": 1, "event": "ready"},
                                 {"protocol": 1, "event": "pin", "code": "0042"},
                                 {"protocol": 1, "event": "disconnected"}])

    def test_invalid_pin_is_never_serialized(self):
        code, frames, _ = self.run_protocol("invalid_pin")
        self.assertEqual(code, 70)
        self.assertEqual(frames, [{"protocol": 1, "event": "error", "code": "receiver_internal"}])

    def test_remote_error_text_cannot_enter_protocol(self):
        _, frames, _ = self.run_protocol("bad_error")
        self.assertEqual(frames, [{"protocol": 1, "event": "error", "code": "receiver_internal"}])

    def test_parent_eof_bounds_lifetime_even_with_ignored_sigterm(self):
        child = subprocess.Popen([str(self.executable), "eof"], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.assertEqual(json.loads(child.stdout.readline()), {"protocol": 1, "event": "ready"})
        child.stdin.close()
        self.assertEqual(child.wait(timeout=5), 0)
        child.stdout.close()

    def check_registration(self, payload, *, mode=0o600):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registered"
            path.write_bytes(payload)
            path.chmod(mode)
            result = subprocess.run([str(self.executable), "registry", str(path)], capture_output=True)
            return result.returncode, result.stdout

    def test_registration_accepts_current_and_bounded_legacy_formats(self):
        key = base64.b64encode(bytes(range(32)))
        self.assertEqual(self.check_registration(key + b"\n" + key + b",id,phone\n"), (0, b"1\n"))
        self.assertEqual(self.check_registration(b""), (0, b"0\n"))

    def test_registration_rejects_truncation_bad_padding_and_oversize(self):
        key = base64.b64encode(bytes(range(32)))
        invalid = [b"a\n", key, b"A" * 44 + b"\n", key + b"garbage\n",
                   b"A" * (1024 * 1024 + 1), key + b"," + b"x" * 4096 + b"\n"]
        for payload in invalid:
            with self.subTest(size=len(payload)):
                self.assertEqual(self.check_registration(payload)[0], 9)

    def test_registration_rejects_excess_distinct_keys_and_open_permissions(self):
        payload = b"".join(base64.b64encode(i.to_bytes(32, "big")) + b"\n" for i in range(1025))
        self.assertEqual(self.check_registration(payload)[0], 9)
        self.assertEqual(self.check_registration(b"", mode=0o644)[0], 9)

    def test_registration_rejects_symlinks_and_multiple_hardlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            actual = Path(directory) / "actual"
            actual.write_bytes(b"")
            actual.chmod(0o600)
            linked = Path(directory) / "linked"
            linked.symlink_to(actual)
            self.assertEqual(subprocess.run([str(self.executable), "registry", str(linked)],
                                           capture_output=True).returncode, 9)
            linked.unlink()
            os.link(actual, linked)
            self.assertEqual(subprocess.run([str(self.executable), "registry", str(actual)],
                                           capture_output=True).returncode, 9)

    def test_registration_writes_only_public_key_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registered"
            key = base64.b64encode(bytes(range(32))).decode("ascii")
            result = subprocess.run([str(self.executable), "save", str(path), key], capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(path.read_text(), key + "\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
