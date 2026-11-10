"""Execute the actual Advanced-functions UI and GUI bridge without GTK/capture."""
import ast
import gettext
import io
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
from magnolie_telefon import PhoneService


def test_actual_advanced_ui_uses_ephemeral_choices_defaults_off_and_never_requires_kde():
    source = (ROOT / 'web/anwendung.js').read_text()
    start = source.index('  function baueTelefonWebcam(')
    end = source.index('\n  const kdeDateisystemAnsichten', start)
    actual = source[start:end]
    assert source.count('baueTelefonWebcam(erweitert)') == 1
    assert source.index('erweitert.id = "kde-erweiterte-funktionen"') < source.index('baueTelefonWebcam(erweitert)')
    assert 'telefonStand' not in actual and 'localStorage' not in actual
    harness = r'''
const assert = (condition) => { if (!condition) throw new Error('UI assertion failed'); };
class Element {
  constructor(tag, text) {this.tag=tag; this.textContent=text || ''; this.children=[]; this.events={}; this.value=''; this.checked=false; this.isConnected=true; this.open=false;}
  append(...children) {this.children.push(...children); if (this.tag==='select' && !this.value) this.value=children[0]?.value || '';}
  replaceChildren() {this.children=[];this.value='';}
  setAttribute() {}
  addEventListener(event, callback) {this.events[event]=callback;}
}
const el=(tag,cls,text)=>new Element(tag,text), _=text=>text;
const document={createTextNode:text=>text};
const knopf=(text,cls,callback)=>{const button=el('button',cls,text);button.click=callback;return button;};
let gesperrt=false, timeout;
const setTimeout=callback=>{timeout=callback;return 1;},clearTimeout=()=>{};
const calls=[],cancels=[];
const Bruecke={sende:value=>{cancels.push(value);return true;}};
let phase='off';
const kdeMedienAnfordern=async(cmd,args)=>{
 calls.push({cmd,...args});
 if(cmd==='telefon_webcam_stand') return {ok:true,webcam:{included:true,enabled:phase!=='off',active:phase==='active',phase,lease:phase==='off'?'':'c'.repeat(64)}};
 if(args.request.action==='prepare') return {ok:true,webcam:{enabled:false,phase:'off',action:'a'.repeat(64),choices:[{token:'b'.repeat(64),phone:'Notes only',device:'Virtual output'}]}};
 if(args.request.action==='start') phase='starting';
 if(args.request.action==='stop') phase='off';
 return {ok:true,webcam:{enabled:phase!=='off',phase,lease:phase==='off'?'':'c'.repeat(64)}};
};
ACTUAL
await (async()=>{
 const root=new Element('details');baueTelefonWebcam(root);
 assert(calls.length===0); // Not even status/inventory while Advanced is closed.
 const block=root.children[0], buttons=block.children.filter(value=>value.tag==='button');
 const [prepare,start,stop]=buttons;
 const labels=block.children.filter(value=>value.tag==='label');
 assert(labels.every(label=>!label.children[0].checked));
 assert(start.disabled&&stop.disabled&&!prepare.disabled);
 root.open=true;root.events.toggle();await Promise.resolve();await Promise.resolve();await Promise.resolve();
 assert(calls[0].cmd==='telefon_webcam_stand');
 await prepare.click();
 assert(calls.at(-1).request.provider==='auto'&&!start.disabled);
 await start.click();
 const request=calls.at(-1).request;
 assert(request.action==='start'&&request.action_token==='a'.repeat(64)&&request.choice_token==='b'.repeat(64));
 assert(request.muted===false&&request.front===false&&!('device' in request));
 const status=block.children.find(value=>value.tag==='p'&&value.textContent.includes('Waiting'));
 assert(status&&stop.disabled===false&&prepare.disabled===true);
 phase='active';await timeout();assert(status.textContent==='Active');
 await stop.click();assert(status.textContent==='Off');
 await prepare.click();root.open=false;root.events.toggle();
 assert(cancels.at(-1).request.action==='cancel'&&start.disabled);
})();
'''.replace('ACTUAL', actual)
    runtime = shutil.which('node') or shutil.which('bun')
    assert runtime, 'Existing JS runtime required'
    result = subprocess.run([runtime, '-e', harness], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_actual_gui_bridge_preserves_requests_and_checks_lock_and_trust():
    tree = ast.parse((ROOT / 'bin/magnolie-organizer').read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_telefon_webcam')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual webcam bridge>', 'exec'), namespace)
    answers = []; requests = []
    backend = SimpleNamespace(webcam_status=lambda: {'phase': 'off'}, webcam_action=lambda payload: requests.append(payload) or {'phase': 'starting'})
    gui = SimpleNamespace(_gesperrt=False, _organizer_vertraut=lambda: True, _telefon=backend,
        antwort=lambda name, result: answers.append((name, result)))
    call = namespace['_telefon_webcam']
    call(gui, dict(cmd='telefon_webcam_stand', requestId='controlled'))
    assert answers[-1] == ('App.telefonWebcam', dict(requestId='controlled', ok=True, webcam={'phase': 'off'}))
    payload = dict(action='start', action_token='a' * 64, choice_token='b' * 64, muted=False, front=True)
    PhoneService.validate_webcam_action(payload)
    call(gui, dict(cmd='telefon_webcam_aktion', request=payload))
    assert requests == [payload]
    gui._gesperrt = True
    call(gui, dict(cmd='telefon_webcam_aktion', request=payload))
    assert not answers[-1][1]['ok'] and len(requests) == 1
    gui._gesperrt = False; gui._organizer_vertraut = lambda: False
    call(gui, dict(cmd='telefon_webcam_aktion', request=payload))
    assert not answers[-1][1]['ok'] and len(requests) == 1


def test_webcam_strings_are_translated_in_all_19_catalogs_and_compile(tmp_path):
    source = (ROOT / 'web/anwendung.js').read_text()
    source = source[source.index('  function baueTelefonWebcam('):source.index('\n  const kdeDateisystemAnsichten')]
    ids = set(re.findall(r'_\("([^"]+)"\)', source))
    catalogs = sorted((ROOT / 'po').glob('*.po'))
    assert len(catalogs) == 19
    # Reuse the actual system compiler: catches duplicates and invalid formats too.
    assert shutil.which('msgfmt')
    for po in catalogs:
        output = tmp_path / (po.stem + '.mo')
        result = subprocess.run(['msgfmt', '--check', '-o', str(output), str(po)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, po.name + ': ' + result.stderr
        catalog = gettext.GNUTranslations(io.BytesIO(output.read_bytes()))
        assert all(value in catalog._catalog and catalog.gettext(value) for value in ids), po.name
