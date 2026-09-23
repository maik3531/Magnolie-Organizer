"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");

async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true
  });
  const w=dom.window, d=w.document, messages=[];
  Object.defineProperty(w,"crypto",{value:webcrypto});
  w.TextEncoder=TextEncoder; w.TextDecoder=TextDecoder;
  w.__MAGNOLIE_BRUECKE__="test";
  w.webkit={messageHandlers:{test:{postMessage:raw=>messages.push(JSON.parse(raw))}}};
  w.eval(fs.readFileSync(path.join(web,"i18n.js"),"utf8"));
  w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web,"anwendung.js"),"utf8"));
  d.dispatchEvent(new w.Event("DOMContentLoaded"));
  const click=id=>d.querySelector(id).click();
  const tick=async()=>{await Promise.resolve(); await Promise.resolve();};
  const selected=()=>[...d.querySelectorAll(".journal-auswahl:checked")];
  const deletes=()=>messages.filter(m=>m.cmd==="journal_loeschen");
  const points=[1,2,3].map(n=>({snapshotId:`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`,
    createdAt:`2026-09-${n===3?"24":"23"}T10:00:00Z`,reason:"manual",integrity:"ok",summary:{notizen:n},payload:{size:1024}}));
  try {
    w.App.init({daten:{},neu:false,regional:{language:"en"}});
    click("#knopf-einstellungen"); click("#einst-tab-sicherheit");
    w.App.journalStand({snapshots:points,intervall:"off",status:"off"});
    assert.equal(d.querySelectorAll(".journal-auswahl").length,3);
    const restoreChecked=d.querySelectorAll(".journal-bereiche input:checked").length;
    click("#journal-alle"); assert.equal(selected().length,3);
    click("#journal-keine"); assert.equal(selected().length,0);
    assert.equal(d.querySelectorAll(".journal-bereiche input:checked").length,restoreChecked,"Selection modified restore scopes.");
    const fields=d.querySelectorAll(".journal-auswahl"); fields[0].click(); fields[1].click();
    click("#journal-auswahl-loeschen"); click("#dialog-nein"); await tick();
    assert.equal(deletes().length,0,"Cancelling still deleted snapshots.");
    click("#journal-auswahl-loeschen"); click("#dialog-ja"); await tick();
    assert.equal(deletes().length,1,"One selection must produce one native request.");
    assert.deepEqual(deletes()[0].snapshotIds,[points[0].snapshotId,points[1].snapshotId]);
    assert.ok(d.querySelector("#journal-auswahl-loeschen").disabled);
    assert.ok([...d.querySelectorAll(".journal-auswahl")].every(field=>field.disabled));
    w.App.journalErgebnis({ok:false,bulk:true,fehler:"synthetic deletion failure"});
    assert.equal(selected().length,2,"Failed operation lost the selection.");
    assert.ok(!d.querySelector("#journal-auswahl-loeschen").disabled,"Failed operation left controls stuck.");
    const filter=d.querySelector("#journal-datum-filter");
    const day=new Date(points[2].createdAt);
    filter.value=[day.getFullYear(),String(day.getMonth()+1).padStart(2,"0"),String(day.getDate()).padStart(2,"0")].join("-");
    filter.dispatchEvent(new w.Event("change",{bubbles:true}));
    assert.equal(d.querySelectorAll(".journal-auswahl").length,1);
    assert.equal(selected().length,0,"Hidden points remained selected.");
    click("#journal-alle"); click("#journal-auswahl-loeschen"); click("#dialog-ja"); await tick();
    assert.deepEqual(deletes()[1].snapshotIds,[points[2].snapshotId],"Select all escaped the visible date filter.");
    w.App.journalErgebnis({ok:true,deleted:true,bulk:true,anzahl:1});
    w.App.journalStand({snapshots:points.slice(0,2),intervall:"off",status:"off"});
    assert.equal(selected().length,0);
    assert.ok(d.querySelector("#journal-auswahl-loeschen").disabled);
    assert.ok(d.querySelector("#zettel").textContent.includes("1"));
    console.log("JOURNAL SELECTION PASSED: "+web);
  } finally {w.close();}
}
(async()=>{
  for(const web of [path.resolve(__dirname,"../app/web"),path.resolve(__dirname,"../../magnolie-organizer/web")])
    if(fs.existsSync(web))await check(web);
})().catch(error=>{console.error(error);process.exitCode=1;});
