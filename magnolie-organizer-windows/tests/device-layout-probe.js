/* Rendered-browser regression. Native host supplies validated synthetic v4 reports. */
"use strict";
window.DeviceLayoutProbe = (() => {
  const id = "11111111-1111-4111-8111-111111111111";
  let peer;
  const rect = e => {
    const r = e.getBoundingClientRect();
    return { x:r.x, y:r.y, width:r.width, height:r.height, right:r.right, bottom:r.bottom };
  };
  const frames = async () => { await document.fonts.ready; await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); };
  function prepare(locale, own = true) {
    document.querySelector('.geraet-dialog-knoepfe button:last-child')?.click();
    MagnolieI18n.setLocale(locale);
    peer = { device_id:id, display_name:"Synthetic device", own_device:own, remote_own_device:true,
      fingerprint:"synthetic-layout-key", state:"online_wifi",
      capabilities:{ revision:1, items:{ device_status:{ available:true, versions:[4] } } },
      local_grants:{ grants:{ device_status:true } }, grants:{ grants:{ device_status:true } } };
    App.telefonStand({ enabled:false, peers:[peer], kdeconnect:{ available:false } });
    OrganizerTest.oeffneGeraeteDialog({ kennung:id, name:"Synthetic device", status:{ online:true } });
    return { locale:document.documentElement.lang, id };
  }
  async function measure() {
    await frames();
    const dialog = document.querySelector('#geraet-dialog'), body = dialog.querySelector('.geraet-dialog-inhalt');
    const grid = dialog.querySelector('.geraet-details'), close = dialog.querySelector('.geraet-dialog-knoepfe button:last-child');
    const errors = [], check = (ok, message) => { if (!ok) errors.push(message); };
    const d = rect(dialog), b = rect(body);
    check(d.x >= -1 && d.right <= innerWidth + 1 && d.y >= -1 && d.bottom <= innerHeight + 1, "dialog outside viewport");
    check(dialog.scrollWidth <= dialog.clientWidth + 1 && body.scrollWidth <= body.clientWidth + 1, "horizontal dialog overflow");
    check(b.height >= 40, "less than two text lines of scroll viewport");
    const fields = [];
    for (const e of grid.querySelectorAll('dt,dd')) {
      if (e.hidden || !e.getClientRects().length) continue;
      const name = e.dataset.geraet || e.dataset.identifier || "label:" + (e.nextElementSibling?.dataset.geraet || e.nextElementSibling?.dataset.identifier);
      const r = rect(e), style = getComputedStyle(e);
      check(e.scrollWidth <= e.clientWidth + 1 && e.scrollHeight <= e.clientHeight + 1, name + " text internally clipped");
      if (e.tagName === "DD") check(r.width >= 80, name + " value width below 80 CSS px");
      const range = document.createRange(); range.selectNodeContents(e);
      const lines = [...range.getClientRects()];
      check(lines.every(line => line.left >= r.x - 2 && line.right <= r.right + 2), name + " glyph line outside cell");
      if (e.tagName !== "DD") continue;
      e.scrollIntoView({ block:"start", inline:"nearest" });
      const first = range.getClientRects()[0], top = rect(body);
      check(!first || first.top >= top.y - 2 && first.bottom <= top.bottom + 2, name + " first line unreachable");
      e.scrollIntoView({ block:"end", inline:"nearest" });
      const last = [...range.getClientRects()].at(-1), bottom = rect(body);
      check(!last || last.top >= bottom.y - 2 && last.bottom <= bottom.bottom + 2, name + " last line unreachable");
      fields.push({ name, width:r.width, height:r.height, lines:lines.length, font:style.fontFamily, fontSize:style.fontSize });
    }
    const buttons = [...dialog.querySelectorAll('.geraet-dialog-knoepfe button')].map(e => {
      const r = rect(e), hit = document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
      check(r.x >= d.x && r.right <= d.right + 1 && r.y >= d.y && r.bottom <= d.bottom + 1, "footer button outside dialog");
      check(e.scrollWidth <= e.clientWidth + 1, "footer button text clipped");
      check(hit === e || e.contains(hit), "footer button obscured");
      return { text:e.textContent, ...r };
    });
    close.focus(); check(document.activeElement === close, "Close is not focusable");
    check(close.textContent === MagnolieI18n.gettext("Close"), "Close label is not translated");
    const serial = grid.querySelector('[data-identifier=serial]');
    if (!serial.hidden) serial.scrollIntoView({ block:"center", inline:"nearest" });
    else body.scrollTop = 0;
    return { locale:document.documentElement.lang, direction:document.documentElement.dir,
      viewport:[innerWidth,innerHeight], devicePixelRatio, dialog:d, scrollViewport:b,
      gridWidth:grid.getBoundingClientRect().width, columns:getComputedStyle(grid).gridTemplateColumns,
      minValueWidth:Math.min(...fields.map(f=>f.width)), fields, buttons, errors,
      fontStatus:document.fonts.status, loadedFonts:[...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family) };
  }
  function revoke() {
    peer.own_device = false;
    App.telefonStand({ enabled:false, peers:[peer], kdeconnect:{ available:false } });
    const fields = [...document.querySelectorAll('#geraet-dialog [data-identifier]')];
    const hidden = fields.length === 3 && fields.every(e => e.hidden && e.previousElementSibling.hidden && !e.getClientRects().length && !e.previousElementSibling.getClientRects().length);
    if (!hidden) throw Error("Unowned identifier labels/values remain in layout");
    if (fields.some(e => /SYNTHETIC-PRIVATE-SERIAL|^\+0|^0{15}/.test(e.textContent))) throw Error("Identifier value survived ownership removal");
    return { allIdentifiersHidden:hidden };
  }
  return { prepare, measure, revoke };
})();
