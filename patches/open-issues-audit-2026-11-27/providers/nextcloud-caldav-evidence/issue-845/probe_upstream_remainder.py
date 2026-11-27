import sys,json,hashlib
from pathlib import Path
root=Path(sys.argv[1]).resolve();output=Path(sys.argv[2]).resolve()
sys.path.insert(0,str(root/'magnolie-organizer/bin'));sys.path.insert(0,str(root/'magnolie-organizer/pruefungen'))
import test_nextcloud as test
import pytest
m=test.m
assert Path(m.__file__).resolve()==root/'magnolie-organizer/bin/magnolie-organizer'
fixtures=json.loads((Path(__file__).parent/'upstream-fixtures.json').read_text())
results=[]
for case in fixtures:
 item=m.ics_lesen(case['ics'])['jahrestage'][0]
 if case['id']=='known':
  dav=test.SyncDav({'calendar':[dict(href='https://cloud.example/calendar/birthday.ics',etag='"fixture"',data=case['ics'])],'addressbook':[]})
  data=test.empty_data();before=json.dumps(data,sort_keys=True);mp=pytest.MonkeyPatch()
  try:
   try:
    outcome=test.run_sync(mp,dav,data).payload
    results.append(dict(case='linux-dav-scope',ok=any(i.get('uid')==item['uid'] for i in outcome.get('jahrestage',[])),outcome='success',birthday_count=len(outcome.get('jahrestage',[])),appointment_count=len(outcome.get('termine',[])),puts=len(dav.puts),deletes=len(dav.deletes)))
   except test.nc.NextcloudError as err:
    results.append(dict(case='linux-dav-scope',ok=err.code=='calendar_anniversaries_unsupported' and not dav.puts and not dav.deletes and before==json.dumps(data,sort_keys=True),outcome='blocked',code=err.code,puts=len(dav.puts),deletes=len(dav.deletes)))
  finally:mp.undo()
 else:
  item['typ']='wedding-anniversary'
  exported=m.ics_schreiben_jahrestage([item]);parsed=m.ics_lesen(exported)
  again=parsed['jahrestage'][0] if parsed['jahrestage'] else None
  rules=[line for line in m._entfalte_zeilen(exported) if line.startswith('RRULE:')]
  results.append(dict(case='type-edit-last-february',ok=rules==['RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1'] and again is not None and again['datum']==item['datum'] and again['typ']=='wedding-anniversary',rules=rules,nextcloud_markers_remain='X-NEXTCLOUD-BC-' in exported,birthday_count=len(parsed['jahrestage']),date=again['datum'] if again else None,type=again['typ'] if again else None,exported=exported))
output.write_text(json.dumps(dict(root=str(root),input_sha256=hashlib.sha256((root/'magnolie-organizer/bin/magnolie-organizer').read_bytes()).hexdigest(),results=results),ensure_ascii=False,indent=2)+'\n')
print(json.dumps([dict(case=x['case'],ok=x['ok'],outcome=x.get('outcome'),rules=x.get('rules')) for x in results]))
