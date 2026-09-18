"""ASR-05: real WebKit/XTest context commands, captured fixture clipboard only.

Reuses only the setup helpers of text_editor_webkit.py, never its broad suite.
--baseline records the old native history without asserting the repaired result.
DOM selection setup/program-flow/negative composition events are explicitly
synthetic; typing, undo/redo, right clicks and menu activation use native XTest.
"""
import sys
from pathlib import Path

baseline = "--baseline" in sys.argv
if baseline:
    sys.argv.remove("--baseline")
probe = '--probe-multiline' in sys.argv
if probe:
    sys.argv.remove('--probe-multiline')
cross_probe = '--probe-cross-target' in sys.argv
if cross_probe:
    sys.argv.remove('--probe-cross-target')
contiguous_probe = '--probe-contiguous-history' in sys.argv
if contiguous_probe:
    sys.argv.remove('--probe-contiguous-history')
program_probe = '--probe-program-flow' in sys.argv
if program_probe:
    sys.argv.remove('--probe-program-flow')
helpers = Path("/home/source/harness.py").read_text().split("completed = False\n")[0]
assert "def setup(" in helpers and "for kind in" not in helpers
helpers = helpers.replace("bindeSchreibTab, htmlZuText,", "zeigeBearbeitenMenue, markierterText, ausAblage, bindeSchreibTab, htmlZuText,")
exec(compile(helpers, "text_editor_webkit-helpers", "exec"))
peak_rss_kib = 0


def memory_sample():
    global peak_rss_kib
    rss = 0
    for status in Path('/proc').glob('[0-9]*/status'):
        try:
            rss += next((int(line.split()[1]) for line in status.read_text().splitlines() if line.startswith('VmRSS:')), 0)
        except (FileNotFoundError, ProcessLookupError):
            pass
    peak_rss_kib = max(peak_rss_kib, rss)
    if rss > 6 * 1024 * 1024:
        raise SystemExit('Isolated process RSS exceeded 6 GiB')
    return True


GLib.timeout_add(500, memory_sample)


class Results(list):
    def append(self, result):
        super().append(result)
        print('PASS', result['kind'], result['case'], flush=True)


results = Results()


def fixture_dialog(_, dialog):
    # Navigation of disposable test pages can raise beforeunload after typing.
    assert dialog.get_dialog_type() == WebKit2.ScriptDialogType.BEFORE_UNLOAD_CONFIRM
    dialog.ref()
    dialog.confirm_set_confirmed(True)
    def close():
        dialog.close()
        dialog.unref()
        return False
    GLib.idle_add(close)
    return True


view.connect('script-dialog', fixture_dialog)
manager = view.get_user_content_manager()
manager.remove_all_scripts()
manager.add_script(WebKit2.UserScript.new("""
window.__MAGNOLIE_SPRACHE__='de'; window.__MAGNOLIE_BRUECKE__='editorTest';
window.saves=[]; window.commands=[]; window.events=[];
window.fixtureClipboard='XY'; window.failCopy=false; window.reads=[];
window.webkit={messageHandlers:{editorTest:{postMessage(raw) {
 const m=JSON.parse(raw); commands.push(m);
 if(m.cmd==='ablage_kopieren' && !failCopy) fixtureClipboard=m.text;
 if(m.cmd==='ablage_holen') reads.push(fixtureClipboard);
 if(m.cmd==='speichern') { saves.push(JSON.parse(m.text)); setTimeout(()=>App.gespeichert({id:m.id,ok:true}),0); }
}}}};
window.replyClipboard=()=>{if(!reads.length) return false; App.ablage({text:reads.shift()}); return true;};
for(const kind of ['keydown','beforeinput','input','compositionstart','compositionend','contextmenu','mousedown','focusin'])
 document.addEventListener(kind,e=>events.push({kind,key:e.key,code:e.code,trusted:e.isTrusted,
  inputType:e.inputType,data:e.data,target:e.target.id||e.target.className}),true);
""", WebKit2.UserContentInjectedFrames.TOP_FRAME, WebKit2.UserScriptInjectionTime.START, None, None))


def select(start, end):
    js(f"""
field.focus();
if(field.tagName==='TEXTAREA' || field.tagName==='INPUT') field.setSelectionRange({start},{end});
else {{
 const w=document.createTreeWalker(field,NodeFilter.SHOW_TEXT),ns=[]; while(w.nextNode()) ns.push(w.currentNode);
 const p=o=>{{for(const n of ns){{if(o<=n.length)return[n,o];o-=n.length;}}return[field,0];}};
 const r=document.createRange(); r.setStart(...p({start}));r.setEnd(...p({end}));
 getSelection().removeAllRanges();getSelection().addRange(r);
}} return true;
""")
    wait(100)


def menu(action, native=True):
    js("OrganizerTest.daten().einstellungen.schrift.rechtschreibung=false; return true;")
    if native:
        point = js("""const r=field.getBoundingClientRect();
if(field.tagName==='TEXTAREA' || field.tagName==='INPUT') {
 // Right-click INSIDE the selected text. A fixed x offset moves the native
 // caret when the selection is further along the line (notably IME text).
 const style=getComputedStyle(field), mirror=document.createElement('div');
 for(const p of ['fontFamily','fontSize','fontWeight','fontStyle','letterSpacing','lineHeight',
  'paddingTop','paddingLeft','paddingRight','paddingBottom','borderTopWidth','borderLeftWidth',
  'borderRightWidth','borderBottomWidth','borderStyle','boxSizing','direction','tabSize']) mirror.style[p]=style[p];
 Object.assign(mirror.style,{position:'fixed',left:r.x+'px',top:r.y+'px',width:r.width+'px',
  visibility:'hidden',pointerEvents:'none',whiteSpace:field.tagName==='INPUT'?'pre':'pre-wrap',overflowWrap:'break-word'});
 const start=field.selectionStart||0, marker=document.createElement('span');
 mirror.append(document.createTextNode(field.value.slice(0,start)));
 marker.textContent=field.value.slice(start,start+1)||'\\u200b';mirror.append(marker,document.createTextNode(field.value.slice(start+1)));
 document.body.append(mirror);const q=marker.getBoundingClientRect();mirror.remove();
 return [q.x+Math.min(2,q.width/2)-field.scrollLeft,field.tagName==='INPUT'?r.y+r.height/2:q.y+q.height/2-field.scrollTop];
}
const s=getSelection(); const q=s.rangeCount && field.contains(s.getRangeAt(0).commonAncestorContainer)?s.getRangeAt(0).getBoundingClientRect():r;
return [q.width?q.x+2:r.x+15,q.height?q.y+q.height/2:r.y+12];""")
        subprocess.run(["xdotool", "mousemove", str(round(point[0])), str(round(point[1])), "click", "3"], check=True, timeout=10)
    else:
        js("OrganizerTest.zeigeBearbeitenMenue(80,80,field,OrganizerTest.markierterText(field)); return true;")
    wait(180)
    button = js("""const b=[...document.querySelectorAll('.bearbeiten-menue button')].find(b=>b.textContent===ACTION);
if(!b)return null;const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,disabled:b.disabled};""".replace("ACTION", json.dumps(action)))
    assert button, ("missing context menu", action, state())
    subprocess.run(["xdotool", "mousemove", str(round(button["x"])), str(round(button["y"])), "click", "1"], check=True, timeout=10)
    wait(180)
    return button


def reply():
    assert js("return replyClipboard();"), ('missing fixture read', summary(),
        js("return {events:events.slice(-20),commands:commands.slice(-8)};"))
    wait(150)


def summary():
    return js("""return {text:field.value ?? OrganizerTest.htmlZuText(field),html:field.innerHTML,
focus:document.activeElement===field,selection:field.selectionStart===undefined?String(getSelection()):field.value.slice(field.selectionStart,field.selectionEnd),
inputs:events.filter(e=>e.kind==='input'),saves:saves.length,reads:reads.length,
clipboard:fixtureClipboard,undo:document.queryCommandEnabled('undo'),redo:document.queryCommandEnabled('redo')};""")


def saved_text(kind):
    data = js("return saves.at(-1);")
    assert data, (kind, "missing saved draft")
    return data['notizen'][0]['text'] if kind == 'note' else data['customOrganizer']['modules'][0]['items'][0]['text'] if kind == 'custom' else data['termine'][0]['notiz']


def save_diary(kind):
    if kind == 'diary':
        js("document.querySelector('.termin-blatt .tb-fuss .hauptknopf, .termin-blatt .hauptknopf, .termin-blatt .haupt').click(); return true;")
    wait(650)


if probe:
    for kind in ('note','custom','diary'):
        setup(kind,'abcd')
        for command in ('insertText','insertHTML'):
            reset('abcd',start=1,end=3)
            js("const text='X\\tY\\nZ';document.execCommand("+json.dumps(command)+",false,"+("OrganizerTest.textZuHtml(text)" if command=='insertHTML' else 'text')+");return true;")
            after=summary()
            key('ctrl+z')
            result={'kind':kind,'case':command,'after':after,'undo':summary()}
            results.append(result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
    (output/'multiline-probe.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    window.destroy()
    sys.exit(0)


if contiguous_probe:
    for kind in ('note','custom','diary'):
        setup(kind,'abcd')
        key('e','Tab')
        assert summary()['text']=='abcde\t', summary()
        select(1,3)
        menu('Einfügen')
        reply()
        assert summary()['text']=='aXYde\t', summary()
        select(1,3)
        menu('Ausschneiden')
        reply()
        assert summary()['text']=='ade\t', summary()
        history=[]
        for stroke in ['ctrl+z']*4+['ctrl+y']*4:
            key(stroke)
            history.append({'key':stroke,**summary()})
        assert history[0]['text']=='aXYde\t' and history[1]['text']=='abcde\t' and history[3]['text']=='abcd' and history[-1]['text']=='ade\t', history
        results.append({'kind':kind,'case':'contiguous-typing-tab-context-history','history':history})
    report={'completed':True,'web':args.web,'sourceSha256':hashlib.sha256((web/'anwendung.js').read_bytes()).hexdigest(),
        'peakIsolatedRssKiB':peak_rss_kib,'results':results}
    (output/'contiguous-history-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for result in results:
        print(result['kind'],[step['text'] for step in result['history']],flush=True)
    window.destroy()
    sys.exit(0)


if cross_probe:
    setup('note','abcd')
    select(1,3)
    js("window.original=field;field=document.querySelector('#notiz-titel');field.value='OTHER';fixtureClipboard='XY';events=[];return true;")
    menu('Einfügen')
    selected=js("return {value:field.value,start:field.selectionStart,end:field.selectionEnd};")
    reply()
    after=summary()
    assert after['text']==selected['value'][:selected['start']]+'XY'+selected['value'][selected['end']:] and js("return original.textContent==='abcd';"), after
    assert len(after['inputs'])==1 and after['inputs'][0]['trusted'] and after['focus'], after
    results.append({'kind':'title-input','case':'native-rightclick-other-target-with-prior-selection','state':after})
    select(0,2)
    before=summary()['text']
    js("window.title=field;field=original;events=[];return true;")
    menu('Einfügen')
    selected=summary()
    assert selected['reads']==1, selected
    reply()
    after=summary()
    assert after['text']!='abcd' and after['text'].count('XY')==1 and js("return title.value;")==before, after
    assert len(after['inputs'])==1 and after['inputs'][0]['trusted'] and after['focus'], after
    key('ctrl+z')
    assert summary()['text']=='abcd', summary()
    results.append({'kind':'note','case':'native-rightclick-back-to-rich-editor','state':after,'undo':summary()})
    # Preserve an unfocused textarea's own selection; never borrow the rich range.
    setup('diary','abcd')
    select(1,3)
    js("field.blur();OrganizerTest.ausAblage(field);return true;")
    reply()
    assert summary()['text']=='aXYd' and summary()['focus'], summary()
    results.append({'kind':'diary','case':'unfocused-program-flow-own-selection','state':summary()})
    reset('IME ')
    view.get_input_method_context().emit('committed','日本語 العربية')
    wait(200)
    select(4,7)
    menu('Einfügen')
    reply()
    assert summary()['text']=='IME XY العربية', summary()
    key('ctrl+z')
    assert summary()['text']=='IME 日本語 العربية', summary()
    results.append({'kind':'diary','case':'native-selected-ime-text-mouse-paste-undo','state':summary()})
    report={'completed':True,'web':args.web,'engine':f'WebKitGTK {WebKit2.MAJOR_VERSION}.{WebKit2.MINOR_VERSION}.{WebKit2.MICRO_VERSION}',
        'sourceSha256':hashlib.sha256((web/'anwendung.js').read_bytes()).hexdigest(),
        'peakIsolatedRssKiB':peak_rss_kib,'results':results}
    (output/'cross-target-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    window.destroy()
    sys.exit(0)


completed = False
try:
    for kind in (() if program_probe else ("note", "custom", "diary")):
        setup(kind, "abcd")
        key("e")
        key("Left", "Right", "Tab")
        typed = summary()
        select(1, 3)
        js("events=[]; saves=[]; return true;")
        menu("Einfügen")
        requested = summary()
        reply()
        pasted = summary()
        if not baseline:
            assert requested["focus"] and requested["text"] == "abcde\t", requested
            assert pasted["text"] == "aXYde\t", pasted
            assert len(pasted["inputs"]) == 1 and pasted["inputs"][0]["trusted"], pasted
        select(1, 3)
        js("events=[]; return true;")
        menu("Ausschneiden")
        before_cut_reply = summary()
        if not baseline:
            assert before_cut_reply["text"] == "aXYde\t" and not before_cut_reply["inputs"], before_cut_reply
            reply()
        cut = summary()
        if not baseline:
            assert cut["text"] == "ade\t" and cut["clipboard"] == "XY", cut
            assert len(cut["inputs"]) == 1 and cut["inputs"][0]["trusted"], cut
        history = []
        for stroke in ["ctrl+z"] * 4 + ["ctrl+y"] * 4:
            key(stroke)
            history.append({"key":stroke, **summary()})
        results.append({"case":"native-typing-tab-context-replace-cut-history", "kind":kind,
            "typed":typed,"requested":requested,"paste":pasted,"beforeCutReply":before_cut_reply,
            "cut":cut,"history":history})
        if not baseline:
            assert [s["text"] for s in history] == ["aXYde\t", "abcde\t", "abcde", "abcd", "abcde", "abcde\t", "aXYde\t", "ade\t"], history
        if baseline:
            continue
        # One real input feeds the real production draft/save pipeline.
        setup(kind, 'abcd', None if kind == 'diary' else '<b>ab</b><i>cd</i>')
        select(1, 3)
        wait(650)
        js("events=[]; saves=[]; fixtureClipboard='X\\tY\\nZ'; return true;")
        menu('Einfügen')
        reply()
        edited = summary()
        assert edited['text'] == 'aX\tY\nZd', edited
        assert len(edited['inputs']) == 1 and edited['inputs'][0]['trusted'], edited
        if kind != 'diary':
            assert '<b>' in edited['html'] and '<i>' in edited['html'], edited
        save_diary(kind)
        assert js('return saves.length;') == 1 and saved_text(kind) == 'aX\tY\nZd', summary()
        results.append({'kind':kind,'case':'plaintext-rich-surroundings-exact-one-input-save','state':summary()})
        if kind != 'diary':
            key('ctrl+z')
            assert summary()['text']=='abcd', summary()
            key('ctrl+y')
            assert summary()['text']=='aX\tY\nZd', summary()
            for plain in ('<b>&</b>\r\nZ\t','\n','X\n','\nY','X\n\nY'):
                reset('abcd',start=1,end=3)
                js('fixtureClipboard='+json.dumps(plain)+';return true;')
                menu('Einfügen',native=False)
                reply()
                after=summary()
                assert after['text']=='a'+plain.replace('\r\n','\n')+'d' and len(after['inputs'])==1 and after['inputs'][0]['trusted'], after
                key('ctrl+z')
                assert summary()['text']=='abcd', summary()
                results.append({'kind':kind,'case':'multiline-literal-native-one-transaction','plain':plain,'state':after})
        # Copy failure preserves the exact selection and does not save/delete.
        setup(kind, 'abcd')
        select(1, 3)
        wait(650)
        js("events=[];saves=[];fixtureClipboard='KEEP';failCopy=true;return true;")
        menu('Ausschneiden')
        reply()
        wait(650)
        failed = summary()
        assert failed['text']=='abcd' and failed['selection']=='bc' and not failed['inputs'] and not failed['saves'], failed
        js("failCopy=false;return true;")
        results.append({'kind':kind,'case':'copy-failure-no-delete-no-save','state':failed})
        # Native beforeinput cancellation must never fall back to DOM writes.
        select(1,3)
        menu('Einfügen')
        js("field.addEventListener('beforeinput',e=>e.preventDefault(),{once:true});events=[];return true;")
        reply()
        assert summary()['text']=='abcd' and not summary()['inputs'], summary()
        results.append({'kind':kind,'case':'beforeinput-cancelled','state':summary()})
        # Guard both pending paste and pending cut against user/program changes.
        for action in ('Einfügen','Ausschneiden'):
            for change in ('typing','typing-undo','caret','other-editor','program-write','readonly','composition'):
                reset('abcd', start=1, end=3)
                js("fixtureClipboard='XY';return true;")
                menu(action)
                if change in ('typing','typing-undo'):
                    key('q')
                    if change=='typing-undo':
                        key('ctrl+z')
                elif change=='caret':
                    select(0,0)
                elif change=='other-editor':
                    js("window.other=document.createElement('div');other.contentEditable='true';other.textContent='OTHER';document.body.append(other);other.focus();return true;")
                    key('q')
                elif change=='program-write':
                    js("if(field.tagName==='TEXTAREA')field.value='PROGRAM';else field.textContent='PROGRAM';return true;")
                elif change=='readonly':
                    js("field.setAttribute('aria-readonly','true');return true;")
                else:
                    js("field.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:'あ'}));return true;")
                before = summary()
                focus = js("return document.activeElement===field;")
                reply()
                after = summary()
                assert after['text']==before['text'] and len(after['inputs'])==len(before['inputs']) and after['focus']==focus, (kind,action,change,before,after)
                js("field.removeAttribute('aria-readonly');field.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));window.other?.remove();return true;")
                results.append({'kind':kind,'case':'pending-'+action+'-'+change,'state':after})
        # A request issued while a previous untagged reply is outstanding must
        # not cause that old reply to write into the newer target/selection.
        reset('abcd', start=1, end=3)
        js("fixtureClipboard='XY';return true;")
        menu('Einfügen')
        select(0,0)
        menu('Einfügen', native=False)
        assert summary()['reads']==1, summary()
        reply()
        assert summary()['text']=='abcd', summary()
        menu('Einfügen', native=False)
        reply()
        assert summary()['text']=='XYabcd', summary()
        results.append({'kind':kind,'case':'one-untagged-read-slot-retry','state':summary()})
        # Empty reply also releases the slot, and unsolicited replies do nothing.
        reset('abcd', start=1, end=3)
        js("fixtureClipboard='';return true;")
        menu('Einfügen', native=False)
        reply()
        js("App.ablage({text:'UNSOLICITED'});fixtureClipboard='XY';return true;")
        assert summary()['text']=='abcd' and not summary()['inputs'], summary()
        menu('Einfügen', native=False)
        reply()
        assert summary()['text']=='aXYd', summary()
        results.append({'kind':kind,'case':'empty-unsolicited-reply-retry','state':summary()})
        # Negative guards at menu creation; no bridge reads even by program flow.
        for guard in ('readonly','inert','composition'):
            reset('abcd', start=1, end=3)
            js("""if(GUARD==='readonly') {if(field.tagName==='TEXTAREA')field.readOnly=true;else field.contentEditable='false';}
else if(GUARD==='inert')field.setAttribute('inert','');
else field.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));return true;""".replace('GUARD',json.dumps(guard)))
            button = menu('Einfügen', native=False)
            assert button['disabled'] and not summary()['reads'] and summary()['text']=='abcd', (guard,summary())
            js("field.readOnly=false;field.removeAttribute('inert');if(field.tagName!=='TEXTAREA')field.contentEditable='true';field.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));return true;")
            results.append({'kind':kind,'case':'initial-'+guard,'state':summary()})
        # Keyboard activation of a focused menu item restores the captured caret.
        # The diary's existing modal focus trap excludes body-level popup buttons;
        # its mouse menu and native undo keys are covered above.
        if kind != 'diary':
            reset('abcd',start=1,end=3)
            js("OrganizerTest.zeigeBearbeitenMenue(80,80,field,OrganizerTest.markierterText(field));[...document.querySelectorAll('.bearbeiten-menue button')].find(b=>b.textContent==='Einfügen').focus();return true;")
            key('Return')
            reply()
            assert summary()['text']=='aXYd' and summary()['focus'], summary()
            results.append({'kind':kind,'case':'native-keyboard-menu-activation','state':summary()})
        # Native IM context commit, followed by mouse context paste and undo.
        reset('IME ')
        view.get_input_method_context().emit('committed','日本語 العربية')
        wait(200)
        assert summary()['text']=='IME 日本語 العربية', summary()
        select(4,7)
        menu('Einfügen')
        reply()
        assert summary()['text']=='IME XY العربية', summary()
        key('ctrl+z')
        assert summary()['text']=='IME 日本語 العربية', summary()
        results.append({'kind':kind,'case':'native-ime-commit-context-paste-undo','state':summary()})
        # Saving while the reply is pending must retain a newer typed draft.
        setup(kind,'abcd')
        select(1,3)
        menu('Einfügen')
        key('q')
        save_diary(kind)
        assert saved_text(kind)=='aqd', summary()
        count = js('return saves.length;')
        reply()
        wait(650)
        assert saved_text(kind)=='aqd' and js('return saves.length;')==count, summary()
        results.append({'kind':kind,'case':'pending-reply-keeps-newer-saved-draft','state':summary()})
    if not baseline:
        # Unfocused program flow and global selections spanning two editables.
        setup('note','abcd')
        select(1,3)
        expected=js("""field.blur();const a=getSelection(),r=a.rangeCount===1?a.getRangeAt(0):null;
let expected=null;
if(r && field.contains(r.commonAncestorContainer)) {
 const before=r.cloneRange();before.selectNodeContents(field);before.setEnd(r.startContainer,r.startOffset);
 const after=r.cloneRange();after.selectNodeContents(field);after.setStart(r.endContainer,r.endOffset);
 expected=String(before)+'XY'+String(after);
}
OrganizerTest.ausAblage(field);return expected;""")
        if expected is None:
            # WebKit may discard a rich selection on blur. Never substitute a
            # stale range from another editor or an invented insertion point.
            assert summary()['text']=='abcd' and not summary()['reads'] and not summary()['inputs'], summary()
        else:
            reply()
            assert summary()['text']==expected and summary()['focus'], summary()
        results.append({'kind':'note','case':'unfocused-program-flow-current-selection','expected':expected,'state':summary()})
        reset('abcd',start=1,end=3)
        js("window.other=document.createElement('div');other.contentEditable='true';other.textContent='OTHER';document.body.append(other);const r=document.createRange();r.setStart(field.firstChild,1);r.setEnd(other.firstChild,3);getSelection().removeAllRanges();getSelection().addRange(r);return true;")
        button=menu('Einfügen',native=False)
        assert button['disabled'] and not summary()['reads'], summary()
        js("getSelection().selectAllChildren(other);return true;")
        button=menu('Ausschneiden',native=False)
        assert button['disabled'] and summary()['text']=='abcd' and not summary()['reads'], summary()
        results.append({'kind':'note','case':'cross-editable-and-other-selection-rejected','state':summary()})
        js("other.remove();return true;")
        reset('abcd',start=1,end=3)
        menu('Einfügen')
        js("field.replaceWith(field.cloneNode(true));return true;")
        reply()
        assert summary()['text']=='abcd' and not summary()['inputs'], summary()
        results.append({'kind':'note','case':'detached-target-rejected','state':summary()})
        setup('note','abcd')
        js("field=document.querySelector('#notiz-titel');field.value='abcd';field.focus();field.setSelectionRange(1,3,'backward');events=[];saves=[];return true;")
        menu('Einfügen')
        reply()
        after=summary()
        wait(650)
        assert after['text']=='aXYd' and len(after['inputs'])==1 and after['inputs'][0]['trusted'], after
        assert js("return saves.length===1 && saves[0].notizen[0].titel==='aXYd';"), summary()
        # Ordinary inputs have no bindeSchreibTab shortcut adapter. Exercise
        # WebKit's native editing commands directly without changing shortcuts.
        view.execute_editing_command('Undo')
        wait(150)
        assert summary()['text']=='abcd', summary()
        view.execute_editing_command('Redo')
        wait(150)
        assert summary()['text']=='aXYd', summary()
        select(1,3)
        menu('Ausschneiden')
        assert summary()['text']=='aXYd', summary()
        reply()
        assert summary()['text']=='ad' and summary()['clipboard']=='XY', summary()
        view.execute_editing_command('Undo')
        wait(150)
        assert summary()['text']=='aXYd', summary()
        for attribute in ('readOnly','disabled'):
            js('field.'+attribute+'=true;events=[];return true;')
            assert menu('Einfügen',native=False)['disabled'] and not summary()['reads'], summary()
            js('field.'+attribute+'=false;return true;')
        results.append({'kind':'title-input','case':'native-backward-selection-paste-cut-history-save-guards','state':summary()})
    completed = True
finally:
    report = {"completed":completed,"baseline":baseline,"web":args.web,
        "engine":f"WebKitGTK {WebKit2.MAJOR_VERSION}.{WebKit2.MINOR_VERSION}.{WebKit2.MICRO_VERSION}",
        "seconds":round(time.monotonic()-started,2),"cpuAffinity":sorted(os.sched_getaffinity(0)),
        "peakIsolatedRssKiB":peak_rss_kib,
        "sourceSha256":hashlib.sha256((web/'anwendung.js').read_bytes()).hexdigest(),"results":results}
    (output / ("program-flow-probe.json" if program_probe else "context-report.json")).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
    for r in results:
        print(r['kind'],r['case'],[s['text'] for s in r.get('history',[])])
    window.destroy()
