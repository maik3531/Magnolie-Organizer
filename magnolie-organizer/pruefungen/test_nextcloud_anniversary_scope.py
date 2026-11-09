"""#440: marked calendar anniversaries must never silently disappear on success."""
import copy

import pytest

from test_nextcloud import m,nc,SyncDav,run_sync,empty_data,event_ics,task_ics


def marked(uid='fixture-anniversary', date='2000-02-03'):
    return m.ics_schreiben_jahrestage([dict(uid=uid,name='Fixture Anniversary',datum=date,typ='birthday',geaendert=1)])


def mixed_resource():
    def blocks(text):
        lines=m._entfalte_zeilen(text)
        return '\r\n'.join(lines[lines.index('BEGIN:VEVENT'):] if 'BEGIN:VEVENT' in lines else lines[lines.index('BEGIN:VTODO'):]).rsplit('END:VCALENDAR',1)[0]
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n'+blocks(marked())+blocks(event_ics())+blocks(task_ics('task','Task'))+'END:VCALENDAR\r\n'


@pytest.mark.parametrize('text',[marked(),mixed_resource(),marked(date='2000-02-29'),marked(date='--02-03')],
                         ids=['marked','mixed','leapday','yearless'])
def test_marked_anniversary_is_imported_or_explicitly_blocked_before_any_sync_commit(monkeypatch,text):
    assert len(m.ics_lesen(text)['jahrestage'])==1
    dav=SyncDav({'calendar':[dict(href='https://cloud.example/calendar/marked.ics',etag='"fixture"',data=text)],'addressbook':[]})
    data=empty_data();data['jahrestage']=[dict(uid='local',name='Keep local',datum='1990-01-02',typ='birthday')]
    before=copy.deepcopy(data)
    try:
        result=run_sync(monkeypatch,dav,data).payload
    except nc.NextcloudError as error:
        assert error.code=='calendar_anniversaries_unsupported'
        assert dav.puts==[] and dav.deletes==[] and data==before
    else:
        assert {item['uid'] for item in result['jahrestage']}=={'local','fixture-anniversary'}, 'Sync silently skipped a parsed marked anniversary'


def test_all_selected_calendars_are_preflighted_before_an_earlier_calendar_can_write(monkeypatch):
    class MultipleDav(SyncDav):
        def collections(self,kind):
            if kind!='calendar':return []
            return [dict(uid=nc.source_id(kind,'https://cloud.example/'+name+'/'),name=name,
                         href='https://cloud.example/'+name+'/',art=kind,supportsVtodo=False) for name in ('first','second')]
        def report(self,href,kind):
            if '/first/' in href:return []
            return [dict(href=href+'marked.ics',etag='"fixture"',data=marked())]
    dav=MultipleDav({'calendar':[],'addressbook':[]});calendars=dav.collections('calendar')
    data=empty_data();first=calendars[0]['uid']
    data['termine']=[dict(uid='local-new',titel='Keep pending upload',datum='2026-11-08',zeit='09:00',geaendert=2,syncKalenderUid=first)]
    data['syncMetadaten']['nextcloud']['kalender'][first]=dict(initialisiert=True,letzterSync=1,etags={})
    before=copy.deepcopy(data)
    with pytest.raises(nc.NextcloudError) as failed:
        run_sync(monkeypatch,dav,data,calendar_ids=[item['uid'] for item in calendars])
    assert failed.value.code=='calendar_anniversaries_unsupported'
    assert data==before and not dav.puts and not dav.deletes


def test_normal_yearly_event_is_not_reclassified_and_unbound_local_anniversary_survives(monkeypatch):
    dav=SyncDav({'calendar':[dict(href='https://cloud.example/calendar/yearly.ics',etag='"fixture"',
        data=event_ics(rrule='RRULE:FREQ=YEARLY\r\n'))],'addressbook':[]})
    data=empty_data();data['jahrestage']=[dict(uid='local',name='Keep local',datum='--02-03',typ='birthday')]
    original=copy.deepcopy(data['jahrestage'])
    first=run_sync(monkeypatch,dav,data).payload
    assert len(first['termine'])==1 and first['jahrestage']==original
    second=run_sync(monkeypatch,dav,first).payload
    assert len(second['termine'])==1 and second['jahrestage']==original
    assert not dav.puts and not dav.deletes


def test_native_error_explains_unsupported_scope_without_claiming_success():
    message=m.nextcloud_fehlertext(nc.NextcloudError('synthetic','calendar_anniversaries_unsupported'))
    assert 'marked anniversaries' in message and 'blocked' in message and 'no complete synchronization' in message
