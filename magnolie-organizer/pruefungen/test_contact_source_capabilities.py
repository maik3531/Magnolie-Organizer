"""Actual DAV collection discovery, no live accounts or provider mutations."""
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_nextcloud as nc


@pytest.mark.parametrize('grants,expected', [
    (None, None), ('', False), ('<d:privilege><d:read/></d:privilege>', False),
    ('<d:privilege><d:write-properties/></d:privilege>', False),
    ('<d:privilege><d:bind/></d:privilege>', False),
    ('<d:privilege><d:write-content/></d:privilege>', True),
    ('<d:privilege><d:write/></d:privilege>', True),
    ('<d:privilege><d:all/></d:privilege>', True),
    ('<d:privilege><x:write xmlns:x="urn:foreign"/></d:privilege>', False),
    ('<d:other><d:privilege><d:write/></d:privilege></d:other>', False),
])
def test_address_book_update_capability_requires_actual_current_user_grant(monkeypatch, grants, expected):
    client = SimpleNamespace(account_type='generic-dav', same_origin_url=lambda href, base: urljoin(base, href))
    dav = nc.NextcloudDav(client)
    monkeypatch.setattr(dav, '_home', lambda _: 'https://fixture.invalid/books/')
    props = {nc.DAV + 'resourcetype': ET.fromstring('<d:resourcetype xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><c:addressbook/></d:resourcetype>')}
    if grants is not None:
        props[nc.DAV + 'current-user-privilege-set'] = ET.fromstring('<d:current-user-privilege-set xmlns:d="DAV:">' + grants + '</d:current-user-privilege-set>')
    calls = []
    def discover(home, properties, depth):
        calls.append((home, properties, depth))
        return [('/books/original/', props)]
    monkeypatch.setattr(dav, 'propfind', discover)
    source, = dav.collections('addressbook')
    assert source['canUpdate'] is expected
    assert calls[0][1].count(nc.DAV + 'current-user-privilege-set') == 1
    assert source['href'] == 'https://fixture.invalid/books/original/'
    assert source['uid'] == nc.source_id('addressbook', source['href'], 'generic-dav')


def test_privilege_withdrawal_is_reobserved_without_cached_write_authority(monkeypatch):
    client = SimpleNamespace(same_origin_url=lambda href, base: urljoin(base, href))
    dav = nc.NextcloudDav(client)
    monkeypatch.setattr(dav, '_home', lambda _: 'https://fixture.invalid/books/')
    props = {nc.DAV + 'resourcetype': ET.fromstring('<d:resourcetype xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><c:addressbook/></d:resourcetype>')}
    monkeypatch.setattr(dav, 'propfind', lambda *_: [('/books/original/', props)])
    props[nc.DAV + 'current-user-privilege-set'] = ET.fromstring('<d:current-user-privilege-set xmlns:d="DAV:"><d:privilege><d:write/></d:privilege></d:current-user-privilege-set>')
    first, = dav.collections('addressbook')
    props.pop(nc.DAV + 'current-user-privilege-set')
    second, = dav.collections('addressbook')
    assert first['canUpdate'] is True and second['canUpdate'] is None
    assert first['uid'] == second['uid']
