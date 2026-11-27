#!/usr/bin/env python3
import hashlib,importlib.machinery,importlib.util,json,sys
from pathlib import Path
root=Path(sys.argv[1]);output=Path(sys.argv[2]);here=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'magnolie-organizer/bin'))
loader=importlib.machinery.SourceFileLoader('actual_nextcloud_marker_audit',str(root/'magnolie-organizer/bin/magnolie-organizer'))
spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
results=[]
for case in json.loads((here/'fixtures/cases.json').read_text()):
 path=here/'fixtures'/case['filename'];text=path.read_text();result=m.ics_lesen(text)
 items=[*result['termine'],*result['jahrestage']];assert len(items)==1
 item=items[0];bucket='jahrestage' if result['jahrestage'] else 'termine'
 markers=[line for line in text.splitlines() if line.startswith('X-NEXTCLOUD-BC-')]
 results.append({**case,'actual_bucket':bucket,'actual_date':item.get('datum'),'actual_type':item.get('typ'),'ics_complex':item.get('icsKomplex'), 'markers_preserved':all(line in item.get('icsRoundtrip',[]) for line in markers),'fixture_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'matches_expected':bucket==case['expected_bucket'] and (case['expected_date'] is None or item.get('datum')==case['expected_date']) and (case['expected_type'] is None or item.get('typ')==case['expected_type'])})
report={'root':str(root),'product_file':'magnolie-organizer/bin/magnolie-organizer','product_sha256':hashlib.sha256((root/'magnolie-organizer/bin/magnolie-organizer').read_bytes()).hexdigest(),'results':results,'boundary':'Actual current Linux ICS reader; synthetic explicit Nextcloud birthday markers, no live server or contact-derived birthday/dedup path.'}
output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
