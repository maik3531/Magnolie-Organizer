#!/usr/bin/env python3
import importlib.util, struct, unittest, tempfile, subprocess, json
from datetime import datetime, timedelta
from pathlib import Path
spec=importlib.util.spec_from_file_location('tzif_builder',Path(__file__).with_name('build-tzif.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def fixture(times=(-1,1),indexes=(1,2),footer='STD0',offset=1234):
    names=b'LMT\0DST\0STD\0'
    types=struct.pack('>iBB',offset,0,0)+struct.pack('>iBB',3600,1,4)+struct.pack('>iBB',0,0,8)
    header=b'TZif2'+b'\0'*15+struct.pack('>6I',0,0,0,len(times),3,len(names))
    def block(size):return struct.pack('>'+('i' if size==4 else 'q')*len(times),*times)+bytes(indexes)+types+names
    return header+block(4)+header+block(8)+b'\n'+footer.encode()+b'\n'

class ParseTests(unittest.TestCase):
    def test_history_types_names_predecessor_and_terminal_type_are_preserved(self):
        value=m.parse_tzif(fixture());self.assertEqual(value[0],0);self.assertEqual(value[2],[-1,1,1,2]);self.assertEqual(value[1][0],[1234,0,'LMT',0,0]);self.assertEqual(value[1][1][:3],[3600,1,'DST']);self.assertEqual(value[3][:4],[0,'STD',None,None])
    def test_month_and_quoted_names_and_default_daylight_offset(self):
        value=m.posix('<+03>-3<+04>,M3.5.0,M10.5.0/3');self.assertEqual(value[:4],[10800,'+03',14400,'+04']);self.assertEqual(value[4],['M',3,5,0,7200])
    def test_julian_and_ordinal_rules_keep_different_leap_semantics(self):
        value=m.posix('STD0DST,J60/-167:59:59,365/167:59:59');self.assertEqual(value[4],['J',60,0,0,-604799]);self.assertEqual(value[5],['N',365,0,0,604799])
    def test_negative_daylight_saving_and_end_of_day(self):
        value=m.posix('STD-1DST0,J60/24,J300');self.assertEqual(value[:4],[3600,'STD',0,'DST']);self.assertEqual(value[4][-1],86400)
    def test_zic_normalizes_actual_utc_standard_and_wall_rule_definitions(self):
        for suffix,entryHour,exitHour in [('u',2,2),('s',0,0),('w',0,-1)]:
            with tempfile.TemporaryDirectory(prefix='magnolie-definition-test-') as directory:
                work=Path(directory);source=work/'source'
                source.write_text('Rule Norm 2000 max - Mar Sun>=8 2:00'+suffix+' 1:00 D\nRule Norm 2000 max - Oct Sun>=25 2:00'+suffix+' 0 S\nZone Synthetic/Norm 2:00 Norm N%sT\n')
                subprocess.run(['zic','-b','fat','-d',str(work/'tzif'),str(source)],check=True)
                model=m.parse_tzif((work/'tzif/Synthetic/Norm').read_bytes())
                # Compare the normalized JS result to the actual source definitions,
                # not an assumed preferred POSIX spelling (zic can use /77 etc).
                checks=[]
                for month,day,hour,before,after in [(3,8,entryHour,7200,10800),(10,25,exitHour,10800,7200)]:
                    date=datetime(2400,month,day);date+=timedelta(days=(6-date.weekday())%7,hours=hour)
                    at=(date-datetime(1970,1,1))//timedelta(milliseconds=1)
                    checks.extend([[at-1,before],[at,after]])
                packet=dict(schema=2,tzdbVersion='2026egtz',zones={'Synthetic/Norm':0},rules=[model])
                js="const p=require(process.argv[1]);let text='';process.stdin.on('data',b=>text+=b).on('end',()=>{const v=JSON.parse(text),r=p(v.packet);for(const [at,offset] of v.checks)require('node:assert/strict').equal(r.offsetAt('Synthetic/Norm',at),offset)});"
                subprocess.run(['node','-e',js,str(Path(__file__).with_name('resolver.js').resolve())],input=json.dumps(dict(packet=packet,checks=checks)),text=True,check=True)

    def test_missing_footer_never_fabricates_eternal_offset(self):
        for data in [fixture(footer=''),fixture()[:-6],fixture()[:4]+b'\0'+fixture()[5:]]:
            with self.assertRaises(ValueError):m.parse_tzif(data)
    def test_unknown_suffix_and_implicit_dst_are_rejected(self):
        for tail in ['STD0DST','STD0DST,J60/2u,J300','STD0DST,J60/2s,J300','STD0DST,J60/2w,J300','STD0DST,J60/168,J300','STD0DST,J0,J300','STD0DST,366,J300','STD0DST,M13.5.0,J300']:
            with self.assertRaises(ValueError,msg=tail):m.posix(tail)
    def test_counts_leap_axis_and_truncation_are_bounded(self):
        good=fixture()
        for cut in [0,4,20,43,44,50,len(good)-1]:
            with self.assertRaises((ValueError,struct.error)):m.parse_tzif(good[:cut])
        for at,value in [(28,1),(36,257),(32,100001),(40,1048577)]:
            bad=bytearray(good);bad[at:at+4]=struct.pack('>I',value)
            with self.assertRaises(ValueError):m.parse_tzif(bytes(bad))
    def test_index_order_and_offset_are_validated(self):
        for data in [fixture(indexes=(1,3)),fixture(times=(1,1)),fixture(offset=93600),fixture(indexes=(1,1))]:
            with self.assertRaises(ValueError):m.parse_tzif(data)

if __name__=='__main__':unittest.main()
