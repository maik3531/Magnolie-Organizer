import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

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


def test_timeout_quarantines_late_reply_without_closing_sms_transport():
    worker = kde._ConnectionWorker(SimpleNamespace(_is_confirmed=lambda _: True),
        SimpleNamespace(close=lambda: pytest.fail('Contact timeout must not close SMS')), {
            'deviceId': 'paired', 'incomingCapabilities': [kde.CONTACT_UIDS_REQUEST],
            'outgoingCapabilities': [kde.CONTACT_UIDS_RESPONSE]})
    sent = []
    worker.send = sent.append
    with pytest.raises(kde.ProtocolError):
        worker.contact_request(kde.CONTACT_UIDS_REQUEST, {}, kde.CONTACT_UIDS_RESPONSE, timeout=0.005)
    assert worker.contacts_blocked and not worker.stopped.is_set()
    with pytest.raises(kde.ProtocolError):
        worker.contact_request(kde.CONTACT_UIDS_REQUEST, {}, kde.CONTACT_UIDS_RESPONSE)
    assert len(sent) == 1
    worker._contact_response(kde.network_packet(kde.CONTACT_VCARDS_RESPONSE, {'uids': []}))
    assert worker.contacts_blocked
    worker._contact_response(kde.network_packet(kde.CONTACT_UIDS_RESPONSE, {'uids': ['old'], 'old': 1}))
    assert not worker.contacts_blocked and worker.contacts_pending is None
    worker.send = lambda _: worker._contact_response(kde.network_packet(kde.CONTACT_UIDS_RESPONSE,
        {'uids': ['fresh'], 'fresh': 2}))
    assert worker.contact_request(kde.CONTACT_UIDS_REQUEST, {}, kde.CONTACT_UIDS_RESPONSE)['uids'] == ['fresh']


@pytest.mark.parametrize('uids', [None, ['duplicate', 'duplicate'], ['bad\nuid'], [str(i) for i in range(6)]])
def test_contact_request_is_a_small_validated_batch(uids):
    backend = kde.KDEConnectSMSBackend.__new__(kde.KDEConnectSMSBackend)
    backend._contact_query = lambda *args: pytest.fail('Invalid request reached the phone')
    with pytest.raises(kde.ProtocolError):
        backend.contact_vcards(uids)
