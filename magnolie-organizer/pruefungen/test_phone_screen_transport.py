import socket
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_phone_screen_transport import PhoneScreenViewLane


# Same fixed wire vectors as the Kotlin sender test (not JPEG fixtures).
FIRST = bytes.fromhex("000000150000000000000000ff4cf254a965f55e05d2cde81cd0c87f07d170c8a0")
SECOND = bytes.fromhex("0000001600000000000000012cf1d07d1ce098974a3ae945893a44699c661252d503")


def lane(sock, width=17, guard=lambda: None):
    return PhoneScreenViewLane(sock, bytes(range(16)), bytes(range(32)), width, 16, guard)


def test_original_wire_sequence_and_replay_rejection():
    a, b = socket.socketpair()
    with a, b:
        view = lane(a)
        b.sendall(FIRST + SECOND + FIRST)
        assert view.receive() == b"first"
        assert view.receive() == b"second"
        with pytest.raises(ValueError, match="envelope"):
            view.receive()
        assert a.fileno() == -1


@pytest.mark.parametrize("case", ["wrong_shape", "bad_tag", "oversized", "truncated"])
def test_bad_packet_retires_exact_socket(case):
    a, b = socket.socketpair()
    with a, b:
        view = lane(a, width=18 if case == "wrong_shape" else 17)
        packet = {"wrong_shape": FIRST, "bad_tag": FIRST[:-1] + bytes([FIRST[-1] ^ 1]),
                  "oversized": (1_048_576 + 17).to_bytes(4, "big") + bytes(8), "truncated": FIRST[:-1]}[case]
        b.sendall(packet)
        b.shutdown(socket.SHUT_WR)
        with pytest.raises((InvalidTag, ValueError, EOFError)):
            view.receive()
        assert a.fileno() == -1


def test_guard_loss_after_authentication_prevents_return():
    a, b = socket.socketpair()
    checks = []

    def guard():
        checks.append(None)
        if len(checks) == 6:
            raise PermissionError("original revoked")

    with a, b:
        view = lane(a, guard=guard)
        b.sendall(FIRST)
        with pytest.raises(PermissionError, match="revoked"):
            view.receive()
        assert a.fileno() == -1
