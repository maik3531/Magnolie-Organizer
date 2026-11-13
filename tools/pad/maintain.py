#!/usr/bin/env python3
"""Offline PAD validation/update; never publishes or submits anything."""
import argparse
import datetime as dt
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
FEED = BASE / 'pad/magnolie-organizer-windows.xml'
RELEASE = BASE / 'pad/release.json'
REPO = 'https://github.com/maik3531/Magnolie-Organizer'
SELF = 'https://raw.githubusercontent.com/maik3531/Magnolie-Organizer/main/pad/magnolie-organizer-windows.xml'
LANGS = ('English', 'German', 'Spanish', 'French', 'Russian')
REQUIRED = ['MASTER_PAD_VERSION_INFO/MASTER_PAD_VERSION', 'Company_Info/Company_Name',
    'Company_Info/Company_WebSite_URL', 'Company_Info/Contact_Info/Author_First_Name',
    'Company_Info/Contact_Info/Author_Last_Name', 'Company_Info/Contact_Info/Author_Email',
    'Company_Info/Contact_Info/Contact_First_Name', 'Company_Info/Contact_Info/Contact_Last_Name',
    'Company_Info/Contact_Info/Contact_Email']
REQUIRED += ['Program_Info/'+x for x in ('Program_Name','Program_Version','Program_Release_Month',
    'Program_Release_Day','Program_Release_Year','Program_Type','Program_Release_Status',
    'Program_Install_Support','Program_OS_Support','Program_Language','Program_Category_Class',
    'Program_System_Requirements','File_Info/File_Size_Bytes','File_Info/File_Size_K','File_Info/File_Size_MB')]
REQUIRED += ['Web_Info/Application_URLs/'+x for x in ('Application_Info_URL',
    'Application_Screenshot_URL','Application_Icon_URL','Application_XML_File_URL')]
REQUIRED += ['Web_Info/Download_URLs/Primary_Download_URL']
REQUIRED += [f'Program_Descriptions/{lang}/{field}' for lang in LANGS
    for field in ['Keywords']+[f'Char_Desc_{n}' for n in (45,80,250,450,2000)]]

def facts(release):
    tag=release['tag_name']
    if not re.fullmatch(r'v\d+\.\d+\.\d+',tag) or release['draft'] or release['prerelease']:
        raise ValueError('Requires a published stable Organizer release vN.N.N')
    version=tag[1:]
    if release['html_url'] != REPO+'/releases/tag/'+tag:
        raise ValueError('Wrong repository')
    name=f'Magnolie-Organizer-Windows-{version}-Setup-x64.exe'
    assets=[a for a in release['assets'] if a['name']==name]
    if len(assets)!=1: raise ValueError('Exactly one matching Windows installer required')
    asset=assets[0]
    if asset['state']!='uploaded' or not isinstance(asset['size'],int) or asset['size']<=0:
        raise ValueError('Invalid asset state/size')
    url=REPO+'/releases/download/'+tag+'/'+name
    if asset['browser_download_url']!=url: raise ValueError('Unexpected download URL')
    date=dt.datetime.fromisoformat(release['published_at'].replace('Z','+00:00')).date()
    return version,asset,date

def validate(root,release):
    errors=[]
    if root.tag!='XML_DIZ_INFO': errors.append('Wrong XML root')
    rules={f.findtext('Path').removeprefix('XML_DIZ_INFO/'):f.findtext('RegEx')
           for f in ET.parse(Path(__file__).with_name('pad-4.0-spec.xml')).findall('.//Field')}
    def walk(node,path=''):
        names=[c.tag for c in node]
        if len(names)!=len(set(names)): errors.append('Duplicate child: '+path)
        for child in node:
            p=path+'/'+child.tag if path else child.tag
            if len(child): walk(child,p); continue
            normalized=re.sub(r'^Program_Descriptions/[^/]+/', 'Program_Descriptions/English/',p)
            rule=rules.get(normalized)
            if rule is None: errors.append('Unknown field: '+p)
            elif rule and not re.fullmatch(rule,child.text or ''): errors.append('Field pattern: '+p)
    walk(root)
    for path in REQUIRED:
        if not root.findtext(path): errors.append('Missing required profile field: '+path)
    version,asset,date=facts(release)
    expected={'Program_Info/Program_Version':version,
      'Program_Info/Program_Release_Year':date.strftime('%Y'),
      'Program_Info/Program_Release_Month':date.strftime('%m'),
      'Program_Info/Program_Release_Day':date.strftime('%d'),
      'Program_Info/File_Info/File_Size_Bytes':str(asset['size']),
      'Program_Info/File_Info/File_Size_K':f"{asset['size']/1024:.2f}",
      'Program_Info/File_Info/File_Size_MB':f"{asset['size']/1024**2:.2f}",
      'Web_Info/Download_URLs/Primary_Download_URL':asset['browser_download_url'],
      'Web_Info/Application_URLs/Application_XML_File_URL':SELF,
      'MASTER_PAD_VERSION_INFO/MASTER_PAD_VERSION':'4.0',
      'MASTER_PAD_VERSION_INFO/CERTIFIED':'N',
      'Program_Info/Program_OS_Support':'WinOther'}
    for path,value in expected.items():
        if root.findtext(path)!=value: errors.append('Fact mismatch: '+path)
    for node in root.iter():
        if node.tag.endswith('_URL') and node.text and not node.text.startswith('https://'):
            errors.append('Non-HTTPS URL: '+node.tag)
    if set(c.tag for c in root.find('Program_Descriptions'))!=set(LANGS):
        errors.append('Description language set differs')
    if errors: raise ValueError('\n'.join(errors))
    print('PASS: XML structure, field patterns, required self-hosted profile fields, five description blocks, release date/version/asset URL/byte size and derived sizes.')
    print('LIMIT: This is not AppVisor certification or proof of catalog acceptance. Omitted identity/address/service fields and network checks are documented in docs/PAD.md.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update-release',type=Path,help='saved GitHub release JSON')
    parser.add_argument('--change-info',help='reviewed English Windows change summary, <=300 characters')
    args=parser.parse_args()
    data=FEED.read_bytes()
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data: raise ValueError('DTD/entities forbidden')
    root=ET.fromstring(data)
    release=json.loads((args.update_release or RELEASE).read_text())
    if args.update_release:
        if not args.change_info: raise ValueError('--change-info required for update')
        version,asset,date=facts(release)
        changes={'Program_Version':version,'Program_Release_Year':date.strftime('%Y'),
          'Program_Release_Month':date.strftime('%m'),'Program_Release_Day':date.strftime('%d'),
          'Program_Change_Info':args.change_info,'File_Info/File_Size_Bytes':str(asset['size']),
          'File_Info/File_Size_K':f"{asset['size']/1024:.2f}",
          'File_Info/File_Size_MB':f"{asset['size']/1024**2:.2f}"}
        for path,value in changes.items(): root.find('Program_Info/'+path).text=value
        root.find('Web_Info/Download_URLs/Primary_Download_URL').text=asset['browser_download_url']
    validate(root,release)
    if args.update_release:
        ET.indent(root,space='  ')
        FEED.write_bytes(ET.tostring(root,encoding='utf-8',xml_declaration=True))
        RELEASE.write_text(json.dumps(release,ensure_ascii=False,indent=2)+'\n')
        print('Updated local files only; review diff and verify live URLs before publication.')

if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,ET.ParseError) as error:
        print(str(error),file=sys.stderr); sys.exit(1)
