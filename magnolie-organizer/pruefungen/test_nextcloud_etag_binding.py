"""#443: an observed version must not turn into If-Match's existence wildcard."""
import pytest

from test_nextcloud import nc


TEXT='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n'
HREF='https://calendar.example.test/cal/item.ics'
WILDCARDS=['*',' * ','* ',' *','\t*\t','   *   ',' \t * \t ','\u00a0*\u00a0']


def client(calls):
    def transport(method,url,headers,body,timeout,limit):
        calls.append((method,headers.get('If-Match'),headers.get('If-None-Match')))
        return 204,{'ETag':'"fixture-v2"'},b''
    return nc.NextcloudDav(nc.DavHttpClient('https://calendar.example.test','fixture','synthetic-only',transport=transport))


@pytest.mark.parametrize('method',['PUT','DELETE'])
@pytest.mark.parametrize('etag',WILDCARDS)
def test_wildcard_observed_etag_is_rejected_before_transport(method,etag):
    calls=[];dav=client(calls)
    with pytest.raises(nc.NextcloudError) as failed:
        if method=='PUT':dav.put(HREF,TEXT,etag=etag)
        else:dav.delete(HREF,etag)
    assert failed.value.code=='missing_etag' and not calls


@pytest.mark.parametrize('method',['PUT','DELETE'])
@pytest.mark.parametrize('etag',['"fixture-v1"','"*"',' "*" ','W/"fixture-v1"','legacy-unquoted',' \t"fixture-v1"\t '])
def test_non_wildcard_etag_keeps_exact_existing_header_semantics(method,etag):
    calls=[];dav=client(calls)
    if method=='PUT':dav.put(HREF,TEXT,etag=etag)
    else:dav.delete(HREF,etag)
    assert calls==[(method,etag,None)]


@pytest.mark.parametrize('etag',[None,'*',' * ','ignored-existing-tag'])
def test_explicit_create_still_uses_if_none_match_wildcard(etag):
    calls=[];client(calls).put(HREF,TEXT,etag=etag,create=True)
    assert calls==[('PUT',None,'*')]


@pytest.mark.parametrize('method',['PUT','DELETE'])
@pytest.mark.parametrize('etag',[1,True,{},[],b'*'])
def test_non_string_version_cannot_bypass_pretransport_validation(method,etag):
    calls=[];dav=client(calls)
    with pytest.raises(nc.NextcloudError) as failed:
        if method=='PUT':dav.put(HREF,TEXT,etag=etag)
        else:dav.delete(HREF,etag)
    assert failed.value.code=='missing_etag' and not calls
