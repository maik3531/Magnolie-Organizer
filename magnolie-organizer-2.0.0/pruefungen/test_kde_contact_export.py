import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_kdeconnect as kde


class Stream:
    def __init__(self, data):
        self.input = io.BytesIO(data)
        self.calls = 0
    def recv(self, length):
        self.calls += 1
        return self.input.read(length)


def test_buffered_contacts_do_not_consume_or_delay_following_sms_packet():
    contacts = kde.network_packet(kde.CONTACT_VCARDS_RESPONSE, {'uids': ['one'], 'one': 'BEGIN:VCARD\nEND:VCARD'})
    sms = kde.network_packet(kde.SMS_MESSAGES_TYPE, {'messages': []})
    stream = Stream(kde.encode_packet(contacts) + kde.encode_packet(sms))
    buffer = bytearray()
    assert kde.read_packet(stream, buffer=buffer) == contacts
    assert kde.read_packet(stream, buffer=buffer) == sms
    assert stream.calls == 1


def test_large_contact_card_is_bounded_and_ordinary_packet_limit_stays_intact():
    body = {'uids': ['one'], 'one': 'x' * (kde.MAX_PACKET + 100)}
    contact = kde.network_packet(kde.CONTACT_VCARDS_RESPONSE, body)
    raw = json.dumps(contact).encode() + b'\n'
    stream = Stream(raw)
    assert kde.read_packet(stream, kde.MAX_CONTACT_PACKET, bytearray()) == contact
    assert stream.calls < 100
    contact['type'] = kde.SMS_MESSAGES_TYPE
    with pytest.raises(kde.ProtocolError):
        kde.read_packet(Stream(json.dumps(contact).encode() + b'\n'), kde.MAX_CONTACT_PACKET, bytearray())


def test_contact_response_cannot_smuggle_unrequested_records():
    backend = kde.KDEConnectSMSBackend.__new__(kde.KDEConnectSMSBackend)
    backend._contact_query = lambda *args: ('paired-device', 'fingerprint', {'uids': ['other'], 'other': 'BEGIN:VCARD\nEND:VCARD'})
    with pytest.raises(kde.ProtocolError):
        backend.contact_vcards(['requested'])


@pytest.mark.parametrize('uids', [None, ['duplicate', 'duplicate'], ['bad\nuid'], [str(i) for i in range(6)]])
def test_contact_request_is_a_small_validated_batch(uids):
    backend = kde.KDEConnectSMSBackend.__new__(kde.KDEConnectSMSBackend)
    backend._contact_query = lambda *args: pytest.fail('Invalid request reached the phone')
    with pytest.raises(kde.ProtocolError):
        backend.contact_vcards(uids)
