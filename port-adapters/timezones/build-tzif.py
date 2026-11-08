#!/usr/bin/env python3
"""Generate/check the common normative TZif/POSIX model; no BP rule metadata.
The input archive is pinned Global-TZ2026egtz-rearguard. zic is a build tool,
not a runtime dependency. CPython ZoneInfo independently checks generated data.
"""
import argparse, hashlib, json, re, struct, subprocess, tarfile, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ARCHIVE_SHA='0f391ed721b54225189a1c5cac469fa24a07c1283e9e460650fd28155e19240d'
SOURCES=['africa','antarctica','asia','australasia','europe','northamerica','southamerica','etcetera','backward','factory']

def seconds(text,limit):
    if not re.fullmatch(r'[+-]?\d{1,3}(?::\d{1,2}(?::\d{1,2})?)?',text):raise ValueError('Unknown POSIX clock/suffix: '+text)
    values=list(map(int,text.lstrip('+-').split(':')))
    if values[0]>limit or any(v>59 for v in values[1:]):raise ValueError('POSIX clock out of range')
    return (-1 if text.startswith('-') else 1)*sum(v*u for v,u in zip(values,[3600,60,1]))

def posix(text):
    if not text:raise ValueError('Missing POSIX future, not an eternal-offset assertion')
    token=r'(?:<[A-Za-z0-9+\-]{3,}>|[A-Za-z]{3,})';number=r'[+-]?\d{1,3}(?::\d{1,2}(?::\d{1,2})?)?'
    m=re.fullmatch('('+token+')('+number+')('+token+')?('+number+')?(?:,([^,]+),([^,]+))?',text)
    if not m:raise ValueError('Unsupported POSIX future: '+text)
    standard=-seconds(m[2],24);daylight=-seconds(m[4],24) if m[4] else standard+3600
    def rule(value):
        date,separator,clock=value.partition('/');clock=seconds(clock,167) if separator else 7200
        if date.startswith('M'):
            match=re.fullmatch(r'M(\d{1,2})\.([1-5])\.([0-6])',date)
            if not match or not 1<=int(match[1])<=12:raise ValueError('Invalid POSIX month rule')
            return ['M',int(match[1]),int(match[2]),int(match[3]),clock]
        if re.fullmatch(r'J\d{1,3}',date) and 1<=int(date[1:])<=365:return ['J',int(date[1:]),0,0,clock]
        if re.fullmatch(r'\d{1,3}',date) and 0<=int(date)<=365:return ['N',int(date),0,0,clock]
        raise ValueError('Unsupported POSIX date selector: '+date)
    if not m[3]:
        if m[4] or m[5] or m[6]:raise ValueError('Future rules without DST')
        return [standard,m[1].strip('<>'),None,None,None,None,text]
    if not m[5] or not m[6]:raise ValueError('Implicit implementation-defined POSIX DST rules are unsupported')
    return [standard,m[1].strip('<>'),daylight,m[3].strip('<>'),rule(m[5]),rule(m[6]),text]

def parse_tzif(data):
    if len(data)>32*1024*1024:raise ValueError('TZif too large')
    def header(at,size):
        if data[at:at+4]!=b'TZif' or len(data)<at+44:raise ValueError('Invalid TZif header')
        gmt,std,leap,count,types,chars=struct.unpack('>6I',data[at+20:at+44])
        if leap or not 1<=types<=256 or count>100000 or chars>1048576 or std not in (0,types) or gmt not in (0,types):raise ValueError('Unsupported TZif bounds/leap-second axis')
        end=at+44+count*(size+1)+types*6+chars+std+gmt
        if end>len(data):raise ValueError('Truncated TZif')
        return (gmt,std,count,types,chars),end
    version=data[4:5] if len(data)>=5 else b''
    counts,end=header(0,4)
    if version not in (b'2',b'3',b'4'):raise ValueError('TZif lacks explicit infinite POSIX future')
    counts,end2=header(end,8);at=end+44;end=end2;gmt,std,count,type_count,char_count=counts
    times=struct.unpack('>'+'q'*count,data[at:at+count*8]);at+=count*8
    if any(abs(v)>9007199254740 for v in times) or any(a>=b for a,b in zip(times,times[1:])):raise ValueError('Invalid TZif transition times')
    indexes=data[at:at+count];at+=count
    if any(i>=type_count for i in indexes):raise ValueError('Invalid TZif type index')
    types=[struct.unpack('>iBB',data[p:p+6]) for p in range(at,at+6*type_count,6)];at+=6*type_count
    names=data[at:at+char_count];at+=char_count
    standard=data[at:at+std] if std else bytes(type_count);at+=std
    universal=data[at:at+gmt] if gmt else bytes(type_count)
    output=[]
    for i,(offset,dst,index) in enumerate(types):
        if not -89999<=offset<=93599 or dst not in (0,1) or index>=len(names) or b'\0' not in names[index:] or standard[i] not in (0,1) or universal[i] not in (0,1) or universal[i] and not standard[i]:raise ValueError('Invalid TZif local type')
        abbreviation=names[index:].split(b'\0',1)[0].decode('ascii')
        if any(ord(c)<32 or ord(c)>126 for c in abbreviation):raise ValueError('Invalid TZif abbreviation')
        output.append([offset,dst,abbreviation,standard[i],universal[i]])
    footer=data[end:]
    if not footer.startswith(b'\n') or not footer.endswith(b'\n') or b'\n' in footer[1:-1]:raise ValueError('Missing/malformed TZif future')
    future=posix(footer[1:-1].decode('ascii'))
    history=[v for pair in zip(times,indexes) for v in pair]
    if future[2] is None and output[indexes[-1] if indexes else 0][0]!=future[0]:raise ValueError('Constant future conflicts with final history')
    return [0,output,history,future]

def build(archive):
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=ARCHIVE_SHA:raise ValueError('Untrusted Global-TZ archive')
    with tempfile.TemporaryDirectory(prefix='magnolie-normative-tz-') as temporary:
        work=Path(temporary);ids=set()
        with tarfile.open(archive) as tar:
            if tar.extractfile('version').read().decode().strip()!='2026egtz-rearguard':raise ValueError('Wrong Global-TZ version')
            for name in SOURCES:
                text=tar.extractfile(name).read();(work/name).write_bytes(text)
                for line in text.decode().splitlines():
                    fields=line.split('#',1)[0].split()
                    if fields and fields[0]=='Zone':ids.add(fields[1])
                    elif fields and fields[0]=='Link':ids.add(fields[2])
        output=work/'tzif';subprocess.run(['zic','-b','fat','-d',str(output),*[str(work/x) for x in SOURCES]],check=True)
        registry={};records=[];dedupe={}
        for name in sorted(ids-{'Factory'}):
            value=parse_tzif((output/name).read_bytes());key=json.dumps(value,separators=(',',':'))
            if key not in dedupe:dedupe[key]=len(records);records.append(value)
            registry[name]=dedupe[key]
        return dict(schema=2,tzdbVersion='2026egtz',sourceArchiveSHA256=ARCHIVE_SHA,zones=registry,rules=records,rejectedZones={'Factory':'unspecified-local-time'})

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('global_tz_archive',type=Path);p.add_argument('--write',action='store_true');a=p.parse_args()
    packet=build(a.global_tz_archive);text=json.dumps(packet,sort_keys=True,separators=(',',':'))+'\n';path=HERE/'tzdb-2026egtz.json'
    if a.write:path.write_text(text)
    else:assert path.read_text()==text,'Normative payload differs'
    print(json.dumps(dict(schema=2,zones=len(packet['zones']),uniqueRules=len(packet['rules']),bytes=len(text.encode()),sha256=hashlib.sha256(text.encode()).hexdigest())))
