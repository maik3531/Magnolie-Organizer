#!/usr/bin/env python3
"""All named zones: independent Global-TZ/zic/ZoneInfo vs shared JS point rules.
The full year cycle is an offline TEST, never a production transition table.
"""
import argparse, calendar, hashlib, json, re, struct, subprocess, tarfile, tempfile, platform
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
HERE=Path(__file__).resolve().parent
ARCHIVE_SHA='0f391ed721b54225189a1c5cac469fa24a07c1283e9e460650fd28155e19240d'
p=argparse.ArgumentParser(description=__doc__);p.add_argument('global_tz_archive',type=Path);p.add_argument('--payload',type=Path,default=HERE/'tzdb-2026egtz.json');p.add_argument('--bp-worker-jar',type=Path);p.add_argument('--bp-classpath');p.add_argument('--worker-command',help='JSON argv array, executed directly without a shell');p.add_argument('--engine-label');p.add_argument('--worker-input',type=Path,action='append',default=[]);a=p.parse_args()
assert hashlib.sha256(a.global_tz_archive.read_bytes()).hexdigest()==ARCHIVE_SHA
packet=json.loads(a.payload.read_text());assert len(packet['zones'])==(597 if packet.get('schema')==2 else 592)
inputs=[a.payload.resolve(),a.global_tz_archive.resolve(),Path(__file__).resolve(),HERE/'resolver.js',HERE/'oracle-worker.cjs']
inputs+=a.worker_input
input_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
EPOCH=datetime(1970,1,1);UTC=timezone.utc

def ms(d):return (d-EPOCH)//timedelta(milliseconds=1)
def from_ms(v):return EPOCH+timedelta(milliseconds=v)
def fields(d):return [d.year,d.month,d.day,d.hour,d.minute,d.second,d.microsecond//1000]
def clock(s):
 sign=-1 if s.startswith('-') else 1
 return sign*sum(int(v)*u for v,u in zip(s.lstrip('+-').split(':'),[3600,60,1]))
def tzif(data):
 def block(at,size):
  gmt,std,leap,count,types,chars=struct.unpack('>6I',data[at+20:at+44]);end=at+44+count*(size+1)+types*6+chars+leap*(size+4)+std+gmt
  return count,end
 count,end=block(0,4);at=44;size=4
 if data[4:5] in [b'2',b'3',b'4']:
  count,end2=block(end,8);at=end+44;size=8;end=end2
 times=struct.unpack('>'+('q' if size==8 else 'i')*count,data[at:at+count*size])
 return times,data[end:].strip(b'\n').decode('ascii') if size==8 else ''
def future_rules(tail,year):
 token=r'(?:<[^>]+>|[A-Za-z]{3,})';num=r'[+-]?\d{1,3}(?::\d{1,2}(?::\d{1,2})?)?'
 m=re.fullmatch('('+token+')('+num+')('+token+')?('+num+')?(?:,([^,]+),([^,]+))?',tail)
 assert m,tail
 if not m[3]:return []
 assert m[5] and m[6],tail
 standard=-clock(m[2]);daylight=-clock(m[4]) if m[4] else standard+3600
 result=[]
 for text,before in [(m[5],standard),(m[6],daylight)]:
  date,_,time=text.partition('/');seconds=clock(time or '2')
  if date.startswith('M'):
   month,week,weekday=map(int,date[1:].split('.'));first=datetime(year,month,1)
   day=1+(weekday-(first.weekday()+1)%7)%7+7*(week-1)
   if day>calendar.monthrange(year,month)[1]:day-=7
   wall=first.replace(day=day)
  else:
   julian=date.startswith('J');day=int(date[1:] if julian else date)
   wall=datetime(year,1,1)+timedelta(days=day-1+(calendar.isleap(year) and day>=60) if julian else day)
  result.append(ms(wall+timedelta(seconds=seconds-before)))
 return result

with tempfile.TemporaryDirectory(prefix='magnolie-complete-tz-oracle-') as temporary:
 work=Path(temporary);source_ids=set();sources=['africa','antarctica','asia','australasia','europe','northamerica','southamerica','etcetera','backward','factory']
 with tarfile.open(a.global_tz_archive) as archive:
  assert archive.extractfile('version').read().decode().strip()=='2026egtz-rearguard'
  for name in sources:
   text=archive.extractfile(name).read();(work/name).write_bytes(text)
   for line in text.decode().splitlines():
    tokens=line.split('#',1)[0].split()
    if tokens and tokens[0]=='Zone':source_ids.add(tokens[1])
    elif tokens and tokens[0]=='Link':source_ids.add(tokens[2])
 if packet.get('schema')==2:assert set(packet['zones'])==source_ids-{'Factory'},'Normative registry incomplete'
 output=work/'tzif';subprocess.run(['zic','-b','fat','-d',str(output),*[str(work/x) for x in sources]],check=True)
 import os
 command=['java','-Xmx512m','-XX:ActiveProcessorCount=2','-cp',str(a.bp_worker_jar)+':'+a.bp_classpath,'BPReferenceWorkerKt'] if a.bp_worker_jar else ['node',str(HERE/'oracle-worker.cjs')]
 if a.worker_command:
  assert not a.bp_worker_jar and a.engine_label,'Custom worker requires its own truthful engine label'
  command=json.loads(a.worker_command);assert isinstance(command,list) and command and all(isinstance(x,str) and x for x in command),'Invalid worker argv'
 worker=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=dict(os.environ,TIMEZONE_PAYLOAD=str(a.payload.resolve())))
 batch=[];total=0;future_models=set();historical=0;future=0;mismatch_count=0;mismatch_samples=[];mismatch_zones={}
 def flush():
  global total,mismatch_count
  if not batch:return
  worker.stdin.write(json.dumps(batch,separators=(',',':'))+'\n');worker.stdin.flush()
  reply=json.loads(worker.stdout.readline());assert 'error' not in reply,reply.get('error');assert reply['checked']==len(batch)
  for failure in reply.get('failures',[]):
   mismatch_count+=1;name=failure['identifier'];mismatch_zones[name]=mismatch_zones.get(name,0)+1
   if len(mismatch_samples)<20:mismatch_samples.append(failure)
  total+=len(batch);batch.clear()
 def add(row):
  batch.append(row)
  if len(batch)>=1000:flush()
 def offset_case(name,zone,at):
  instant=from_ms(at).replace(tzinfo=UTC);wall=instant.astimezone(zone)
  add(['o',name,at,int(wall.utcoffset().total_seconds()),fields(wall)])
 def wall_case(name,zone,wall):
  valid=sorted({ms(v.astimezone(UTC).replace(tzinfo=None)) for fold in [0,1] for v in [wall.replace(tzinfo=zone,fold=fold)] if v.astimezone(UTC).astimezone(zone).replace(tzinfo=None)==wall})
  forward=ms(wall-zone.utcoffset(wall.replace(fold=0))) if not valid else None
  add(['w',name,fields(wall),valid,forward])
 for name,index in sorted(packet['zones'].items()):
  data=(output/name).read_bytes()
  with (output/name).open('rb') as stream:zone=ZoneInfo.from_file(stream,key=name)
  times,tail=tzif(data)
  for year in [1,99,400,2400,9999]:
   for month in [1,7]:
    stamp=datetime(year,month,15,12,30);offset_case(name,zone,ms(stamp));wall_case(name,zone,stamp)
  # TZif timestamps, including standard-only and zic sentinel transitions,
  # originate independently of the Java/BP history representation.
  for t in times:
   if t < -62134387200 or t > 253401868799:continue
   at=t*1000;historical+=1
   for delta in [-1,0,1]:offset_case(name,zone,at+delta)
   before=from_ms(at-1000).replace(tzinfo=UTC).astimezone(zone).utcoffset();after=from_ms(at).replace(tzinfo=UTC).astimezone(zone).utcoffset()
   if before!=after:
    wall=from_ms(at)+min(before,after)+abs(after-before)/2
    wall_case(name,zone,wall)
  # Every independent POSIX model, 400 Gregorian years, exact edges + gap/fold.
  if tail and tail not in future_models:
   future_models.add(tail)
   for year in [*range(2400,2800),*([9999] if packet.get('schema')==2 else [])]:
    for at in future_rules(tail,year):
     future+=1
     for delta in [-1,0,1]:offset_case(name,zone,at+delta)
     before=from_ms(at-1000).replace(tzinfo=UTC).astimezone(zone).utcoffset();after=from_ms(at).replace(tzinfo=UTC).astimezone(zone).utcoffset()
     if before!=after:wall_case(name,zone,from_ms(at)+min(before,after)+abs(after-before)/2)
 flush();worker.stdin.close();assert worker.wait(timeout=20)==0
 assert input_hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},'Reference inputs changed during execution'
 print(json.dumps(dict(inputSHA256=input_hashes,pythonVersion=platform.python_version(),zicVersion=subprocess.check_output(['zic','--version'],text=True).strip(),zones=len(packet['zones']),checks=total,historicalTransitions=historical,futureTransitions=future,independentPOSIXModels=len(future_models),provider='Global-TZ2026egtz-rearguard/zic/CPythonZoneInfo',comparedEngine=a.engine_label or ('actual BP1.7.5' if a.bp_worker_jar else 'JS normative TZif/POSIX schema2' if packet.get('schema')==2 else 'JS prototype with BP-derived rules'),archiveSHA256=ARCHIVE_SHA,mismatches=mismatch_count,mismatchZones=mismatch_zones,samples=mismatch_samples)))
 assert mismatch_count==0,'Independent complete timezone reference disagrees; see counted samples'
