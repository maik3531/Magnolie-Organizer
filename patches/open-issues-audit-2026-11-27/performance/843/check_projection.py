#!/usr/bin/env python3
import hashlib,importlib.util,json,subprocess,sys
from pathlib import Path
r=Path(sys.argv[1]);snapshot={"port-adapters/timezones/"+name:(r/"port-adapters/timezones"/name).read_bytes() for name in ["projection-patches.json","app-hooks.snippets"]}
p=r/"Magnolie-Organizer-macOS-Beta/tools/project_ui.py";spec=importlib.util.spec_from_file_location("projection",p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
results=[]
for source in [r/"magnolie-organizer/web/anwendung.js",r/"magnolie-organizer-windows/app/web/anwendung.js"]:
 text=source.read_text();assert m.apply_timezone_patches(text,snapshot)==text
 js="const fs=require('node:fs'),path=require('node:path');const r=process.argv[1],f=process.argv[2];const patch=require(path.join(r,'port-adapters/timezones/projection-patches.cjs'));const src=fs.readFileSync(f,'utf8');const result=patch(src,name=>fs.readFileSync(path.join(r,'port-adapters/timezones',name)));if(result!==src)throw Error('Projection changed canonical source');new Function(result);console.log('PASS');"
 subprocess.run(['node','-e',js,str(r),str(source)],check=True)
 results.append({'source':str(source.relative_to(r)),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'macOS_timezone_adapter':'PASS','tablet_timezone_adapter':'PASS','native_claim':False})
print(json.dumps(results,ensure_ascii=False))
