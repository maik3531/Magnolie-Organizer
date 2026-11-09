#!/usr/bin/env python3
"""Offline adapter: production Kotlin VTIMEZONE through the actual v2.0.30 parser.
This is a test worker, never a runtime timezone provider or finite export table.
"""
import argparse, hashlib, importlib.util, json, os, resource, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('definitions',type=Path)
p.add_argument('--published-module',type=Path)
a=p.parse_args()
repo=Path(__file__).resolve().parents[3]
source=a.published_module or repo/'magnolie-organizer/bin/magnolie_recurrence.py'
assert source.read_bytes()==subprocess.check_output(['git','show','v2.0.30:magnolie-organizer/bin/magnolie_recurrence.py'],cwd=repo)
resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
if hasattr(os,'sched_getaffinity'):os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:2])
spec=importlib.util.spec_from_file_location('actual_published_recurrence',source)
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
definitions={v['identifier']:v['definition'] for v in json.loads(a.definitions.read_text())}
assert len(definitions)==597
EPOCH=datetime(1970,1,1)
def ms(value):return (value-EPOCH)//timedelta(milliseconds=1)
def fields(d):return [d.year,d.month,d.day,d.hour,d.minute,d.second,d.microsecond//1000]
last_name=None;zone=None
for line in sys.stdin:
 rows=json.loads(line);failures=[]
 for row in rows:
  try:
   name=row[1]
   if last_name!=name:zone=module.CalendarZone(definitions[name]);last_name=name
   if row[0]=='o':
    at=EPOCH+timedelta(milliseconds=row[2]);offset=zone._offset_at(at)
    assert int(offset.total_seconds())==row[3],('offset',name,at,offset,row[3])
    assert fields(zone.fromutc(at.replace(tzinfo=zone)))==row[4],('wall',name,at)
   else:
    wall=datetime(*row[2][:6],microsecond=row[2][6]*1000)
    valid=sorted({ms(wall-offset) for offset in zone.offsets if zone._offset_at(wall-offset)==offset})
    assert valid==row[3],('valid',name,wall,valid,row[3])
    if not valid:assert ms(wall-zone.utcoffset(wall))==row[4],('forward',name,wall)
  except Exception as error:failures.append(dict(identifier=row[1],sample=row,error=str(error)))
 print(json.dumps(dict(checked=len(rows),failures=failures),separators=(',',':')),flush=True)
