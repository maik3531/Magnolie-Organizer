/*
 * Magnolie Organizer – Handbuch
 * Copyright (C) 2026 Maik Walter <maik3531@gmail.com>
 * Freie Software unter der GNU General Public License, Version 3 oder
 * später, ohne jede Gewährleistung. <https://www.gnu.org/licenses/>
 */
/* ==========================================================================
   Magnolie Organizer – Handbuch
   Blättern, Inhaltsverzeichnis und Druckfassung.
   ========================================================================== */
(function () {
  "use strict";

  const $ = (w) => document.querySelector(w);
  const SEITEN = window.HANDBUCH_SEITEN || [];
  const ANZEIGE = [];
  const _ = window.MagnolieI18n.gettext;
  const bildLader = new Map();
  let umbruchLaeuft = false;
  let umbruchVorgemerkt = false;

  /* Der Programmkern nimmt Nachrichten über diese Brücke entgegen. */
  const Bruecke = {
    vorhanden: !!(window.webkit && window.webkit.messageHandlers &&
      window.webkit.messageHandlers.bruecke),
    sende(nachricht) {
      if (!this.vorhanden) return false;
      try {
        window.webkit.messageHandlers.bruecke.postMessage(
          JSON.stringify(nachricht));
        return true;
      } catch (fehler) {
        return false;
      }
    }
  };

  /* Der linke Bogen trägt immer eine gerade Blattnummer: Seite 1 steht
     rechts, wie in einem gedruckten Buch. */
  let bogen = 0;                  /* 0 = Seiten 1/2, 1 = Seiten 3/4 … */

  function seitenZahl() { return ANZEIGE.length; }

  function seitenIndex(id) {
    const index = ANZEIGE.findIndex((seite) => seite.quellId === id || seite.id === id);
    if (index >= 0) return index;
    const quelle = SEITEN.find((seite) => seite.id === id);
    return quelle && quelle.platzhalter === "inhalt"
      ? ANZEIGE.findIndex((seite) => seite.istVerzeichnis) : -1;
  }

  /* Waehrend der Druckausgabe zeigen Verweise auf die gedruckte Seite,
     nicht auf die Nummer der ungeteilten Quellseite. */
  let druckNummern = null;

  function quellSeitenIndex(id) {
    return SEITEN.findIndex((seite) => seite.id === id);
  }

  function verweiseAufloesen(markup, druck) {
    const huelle = document.createElement("div");
    huelle.innerHTML = markup || "";
    for (const verweis of huelle.querySelectorAll("[data-page]")) {
      const ziel = verweis.dataset.page;
      const gedruckt = (druck && druckNummern) ? druckNummern.get(ziel) : undefined;
      const nummer = gedruckt !== undefined ? gedruckt : quellSeitenIndex(ziel) + 1;
      if (nummer > 0 && !verweis.textContent.trim()) {
        verweis.textContent = String(nummer);
      }
    }
    return huelle.innerHTML;
  }

  function el(art, klasse, text) {
    const knoten = document.createElement(art);
    if (klasse) knoten.className = klasse;
    if (text !== undefined && text !== null) knoten.textContent = text;
    return knoten;
  }

  function zeichneSeite(seite, _nummer, wo) {
    const kopf = $("#kopf-" + wo);
    const inhalt = $("#inhalt-" + wo);
    const fuss = $("#fuss-" + wo);
    kopf.textContent = "";
    inhalt.textContent = "";
    fuss.textContent = "";
    inhalt.classList.remove("scroll-ausnahme");
    inhalt.classList.toggle("bildschirm-kompakt", !!(seite && seite.bildschirmKompakt));

    if (!seite) {
      inhalt.innerHTML = "";
      fuss.append(el("span", null, ""), el("span", "seitenzahl", ""));
      return;
    }

    const titelblock = el("div");
    if (seite.kapitel) titelblock.append(el("div", "kapitel", seite.kapitel));
    titelblock.append(el("h2", null, seite.titel || ""));
    kopf.append(titelblock);

    inhalt.innerHTML = verweiseAufloesen(seite.inhalt);

    /* Stabile Seitenkennungen bleiben bei eingefügten Blättern gültig. */
    for (const verweis of inhalt.querySelectorAll("[data-page]")) {
      const index = seitenIndex(verweis.dataset.page);
      if (index < 0) continue;
      verweis.addEventListener("click", () => {
        blaettereZu(index);
      });
    }

    /* Das Inhaltsverzeichnis wird als Text eingesetzt – seine Knöpfe
       bekommen hier wieder Leben. */
    for (const knopf of inhalt.querySelectorAll(".inhalt-eintrag")) {
      const ziel = seitenIndex(knopf.dataset.handbookTarget);
      if (ziel < 0) continue;
      knopf.addEventListener("click", () => {
        blaettereZu(ziel);
      });
    }

    const quellNummer = quellSeitenIndex(seite.quellId || seite.id) + 1;
    fuss.append(el("span", null, _("Magnolie Organizer · Handbook")));
    fuss.append(el("span", "seitenzahl", String(quellNummer)));
  }

  function zeichne() {
    const links = bogen * 2 - 1;      /* Blattnummer der linken Seite */
    const rechts = bogen * 2;
    zeichneSeite(ANZEIGE[links], links + 1, "links");
    zeichneSeite(ANZEIGE[rechts], rechts + 1, "rechts");

    $("#ecke-links").classList.toggle("aus", bogen <= 0);
    $("#ecke-rechts").classList.toggle("aus", rechts >= seitenZahl() - 1);

    const sichtbareQuellnummern = [ANZEIGE[links], ANZEIGE[rechts]]
      .filter(Boolean).map((seite) => quellSeitenIndex(seite.quellId || seite.id) + 1);
    const von = Math.min(...sichtbareQuellnummern);
    const bis = Math.max(...sichtbareQuellnummern);
    const muster = von === bis
      ? _("Page {first} of {total}") : _("Pages {first} and {last} of {total}");
    $("#stand").textContent = muster.replace(/\{(first|last|total)\}/g,
      (_treffer, name) => String({ first: von, last: bis, total: SEITEN.length }[name]));
    $("#inhalt-links").scrollTop = 0;
    $("#inhalt-rechts").scrollTop = 0;
  }

  function blaettere(um) {
    const neu = bogen + um;
    if (neu < 0 || neu * 2 - 1 >= seitenZahl()) return;
    bogen = neu;
    zeichne();
  }

  /* Springt zu einer Seite (0-basiert) und schlägt den passenden Bogen auf. */
  function blaettereZu(seitenIndex) {
    const ziel = Math.max(0, Math.min(seitenZahl() - 1, seitenIndex));
    bogen = Math.floor((ziel + 1) / 2);
    zeichne();
  }

  /* ---------------------------------------------------------------------- */
  /* Inhaltsverzeichnis                                                      */
  /* ---------------------------------------------------------------------- */

  function baueInhaltsverzeichnis() {
    const liste = el("ul", "inhalt-liste");
    SEITEN.forEach((seite) => {
      if (!seite.imInhalt) return;
      const i = seitenIndex(seite.id);
      if (i < 0) return;
      const zeile = el("li");
      const knopf = el("button", "inhalt-eintrag" +
        (seite.imInhalt === "haupt" ? " haupt" : ""));
      knopf.type = "button";
      knopf.dataset.handbookTarget = seite.id;
      knopf.append(el("span", null, seite.titel));
      knopf.append(el("span", "punkte"));
      knopf.append(el("span", "zahl", String(quellSeitenIndex(seite.id) + 1)));
      knopf.addEventListener("click", () => blaettereZu(i));
      zeile.append(knopf);
      liste.append(zeile);
    });
    return liste;
  }

  /* ---------------------------------------------------------------------- */
  /* Suche über alle logischen Handbuchseiten                               */
  /* ---------------------------------------------------------------------- */

  function suchText(wert) {
    return String(wert || "").normalize("NFKC").toLocaleLowerCase(
      document.documentElement.lang || undefined).replace(/\s+/g, " ").trim();
  }

  function seitenText(seite) {
    const huelle = document.createElement("div");
    huelle.innerHTML = seite.inhalt || "";
    return suchText([seite.kapitel, seite.titel, huelle.textContent,
      String(seite.id || "").replace(/-/g, " ")].join(" "));
  }

  function suchTreffer(anfrage) {
    const teile = suchText(anfrage).split(" ").filter(Boolean);
    if (!teile.length) return [];
    return SEITEN.filter((seite) => !seite.platzhalter &&
      teile.every((teil) => seitenText(seite).includes(teil)));
  }

  let suchRueckkehrFokus = null;

  function sucheAktualisieren() {
    const feld = $("#handbuch-suchfeld");
    const ausgabe = $("#handbuch-suchergebnisse");
    ausgabe.textContent = "";
    if (!feld.value.trim()) return;
    const treffer = suchTreffer(feld.value);
    if (!treffer.length) {
      ausgabe.append(el("p", "handbuch-suche-leer", _("No matching handbook pages.")));
      return;
    }
    for (const seite of treffer) {
      const knopf = el("button", "handbuch-suchtreffer");
      knopf.type = "button";
      knopf.dataset.page = seite.id;
      knopf.append(el("strong", null, seite.titel || seite.id));
      if (seite.kapitel) knopf.append(el("span", null, seite.kapitel));
      knopf.addEventListener("click", () => {
        const index = seitenIndex(seite.id);
        if (index >= 0) blaettereZu(index);
        oeffneBuch();
        sucheSchliessen();
      });
      const eintrag = el("div", "handbuch-suchtreffer-eintrag");
      eintrag.setAttribute("role", "listitem");
      eintrag.append(knopf);
      ausgabe.append(eintrag);
    }
  }

  function sucheOeffnen() {
    oeffneBuch();
    const bereich = $("#handbuch-suche");
    if (bereich.hidden) suchRueckkehrFokus = document.activeElement;
    bereich.hidden = false;
    sucheAktualisieren();
    $("#handbuch-suchfeld").focus();
    $("#handbuch-suchfeld").select();
  }

  function sucheSchliessen() {
    $("#handbuch-suche").hidden = true;
    const fokusZiel = suchRueckkehrFokus && suchRueckkehrFokus.isConnected
      ? suchRueckkehrFokus : $("#knopf-suche");
    if (fokusZiel && typeof fokusZiel.focus === "function") fokusZiel.focus();
    suchRueckkehrFokus = null;
  }

  function einheiten(markup) {
    const huelle = document.createElement("div");
    huelle.innerHTML = markup || "";
    const ergebnis = [];
    let gruppe = 0;
    for (const knoten of Array.from(huelle.children)) {
      if ((knoten.tagName === "OL" || knoten.tagName === "UL") && knoten.children.length) {
        const schablone = knoten.cloneNode(false);
        const start = knoten.tagName === "OL" ? Number(knoten.getAttribute("start") || 1) : 0;
        Array.from(knoten.children).forEach((li, index) => {
          ergebnis.push({ li: li.cloneNode(true), schablone, gruppe, index, start });
        });
        gruppe += 1;
      } else {
        ergebnis.push({ knoten: knoten.cloneNode(true) });
      }
    }
    return ergebnis;
  }

  function einheitenMarkup(teile) {
    const huelle = document.createElement("div");
    let liste = null;
    let gruppe = -1;
    for (const teil of teile) {
      if (!teil.li) {
        liste = null;
        gruppe = -1;
        huelle.append(teil.knoten.cloneNode(true));
        continue;
      }
      if (teil.gruppe !== gruppe) {
        liste = teil.schablone.cloneNode(false);
        if (liste.tagName === "OL") {
          const start = teil.start + teil.index;
          liste.setAttribute("start", String(start));
          if (liste.classList.contains("schritte")) {
            liste.style.counterReset = "schritt " + (start - 1);
          }
        }
        huelle.append(liste);
        gruppe = teil.gruppe;
      }
      liste.append(teil.li.cloneNode(true));
    }
    return huelle.innerHTML;
  }

  function anzeigeSeite(quelle, inhalt, teil) {
    return Object.assign({}, quelle, {
      id: teil ? quelle.id + "--" + (teil + 1) : quelle.id,
      quellId: quelle.id,
      inhalt,
      teil: teil + 1
    });
  }

  /* Gemessen wird absichtlich im echten rechten Inhaltskasten. So gehen
     Medienregeln, Schriften, Innenabstände und die jeweilige Titelhöhe ein. */
  function passtInAnzeigekasten(seite) {
    const kopf = $("#kopf-rechts");
    const inhalt = $("#inhalt-rechts");
    kopf.textContent = "";
    const titelblock = el("div");
    if (seite.kapitel) titelblock.append(el("div", "kapitel", seite.kapitel));
    titelblock.append(el("h2", null, seite.titel || ""));
    kopf.append(titelblock);
    inhalt.classList.remove("scroll-ausnahme");
    inhalt.classList.toggle("bildschirm-kompakt", !!seite.bildschirmKompakt);
    inhalt.innerHTML = verweiseAufloesen(seite.inhalt);
    const hoehe = inhalt.clientHeight;
    if (!hoehe) return true;
    if (inhalt.scrollHeight > hoehe + 1) return false;

    const letzter = inhalt.lastElementChild;
    if (!letzter || !inhalt.getBoundingClientRect || !window.getComputedStyle) return true;
    const kasten = inhalt.getBoundingClientRect();
    const ende = letzter.getBoundingClientRect();
    const stil = window.getComputedStyle(letzter);
    const rand = parseFloat(stil.marginBottom) || 0;
    const innen = parseFloat(window.getComputedStyle(inhalt).paddingBottom) || 0;
    return ende.bottom + rand <= kasten.bottom - innen + 1;
  }

  function teileSeite(quelle, markup) {
    return teileSeiteMit(quelle, markup, passtInAnzeigekasten);
  }

  function teileSeiteMit(quelle, markup, passt) {
    const alle = einheiten(markup);
    if (!alle.length) return [anzeigeSeite(quelle, "", 0)];
    const seiten = [];
    let aktuell = [];
    for (const einheit of alle) {
      const kandidat = aktuell.concat(einheit);
      const probe = anzeigeSeite(quelle, einheitenMarkup(kandidat), seiten.length);
      if (aktuell.length && !passt(probe)) {
        /* Eine Überschrift bleibt nach Möglichkeit beim folgenden Block –
           aber nur, wenn beide zusammen auf die nächste Seite passen. */
        const letztes = aktuell[aktuell.length - 1];
        const paar = [letztes, einheit];
        if (letztes.knoten && /^H[1-6]$/.test(letztes.knoten.tagName) &&
            passt(anzeigeSeite(quelle, einheitenMarkup(paar), seiten.length))) {
          aktuell.pop();
          if (aktuell.length) {
            seiten.push(anzeigeSeite(quelle, einheitenMarkup(aktuell), seiten.length));
          }
          aktuell = paar;
        } else {
          seiten.push(anzeigeSeite(quelle, einheitenMarkup(aktuell), seiten.length));
          aktuell = [einheit];
        }
      } else {
        aktuell = kandidat;
      }
    }
    if (aktuell.length) {
      seiten.push(anzeigeSeite(quelle, einheitenMarkup(aktuell), seiten.length));
    }
    return seiten;
  }

  function setzeAnzeige(seiten) {
    ANZEIGE.splice(0, ANZEIGE.length, ...seiten);
  }

  function mitInhaltsseiten(teile, inhaltsseiten) {
    const ergebnis = [];
    let eingesetzt = false;
    for (const quelle of SEITEN) {
      if (quelle.platzhalter === "inhalt") {
        if (!eingesetzt) ergebnis.push(...inhaltsseiten);
        eingesetzt = true;
      } else {
        ergebnis.push(...teile.get(quelle));
      }
    }
    return ergebnis;
  }

  function baueInhaltsseiten(platzhalter) {
    const liste = baueInhaltsverzeichnis();
    const huelle = el("div");
    huelle.append(liste);
    const roh = teileSeite(platzhalter[0], huelle.innerHTML);
    return roh.map((seite, index) => {
      const quelle = platzhalter[Math.min(index, platzhalter.length - 1)];
      return Object.assign(anzeigeSeite(quelle, seite.inhalt, index), {
        istVerzeichnis: true,
        id: index < platzhalter.length ? quelle.id : platzhalter[0].id + "--" + (index + 1),
        quellId: quelle.id
      });
    });
  }

  function bilderBeobachten() {
    const huelle = document.createElement("div");
    huelle.innerHTML = SEITEN.map((seite) => seite.inhalt || "").join("");
    for (const bild of huelle.querySelectorAll("img[src]")) {
      const quelle = new URL(bild.getAttribute("src"), document.baseURI).href;
      if (bildLader.has(quelle)) continue;
      const lader = new window.Image();
      bildLader.set(quelle, lader);
      lader.addEventListener("load", umbruchPlanen);
      lader.addEventListener("error", umbruchPlanen);
      lader.src = quelle;
    }
  }

  function umbruch() {
    if (umbruchLaeuft) return;
    umbruchLaeuft = true;
    const hatteAnzeige = ANZEIGE.length > 0;
    const rechterIndex = bogen * 2;
    const bisher = ANZEIGE[rechterIndex] ||
      ANZEIGE[Math.max(0, rechterIndex - 1)] || ANZEIGE[0];
    const zielId = bisher && bisher.quellId;
    try {
      const platzhalter = SEITEN.filter((seite) => seite.platzhalter === "inhalt");
      const vorher = new Map(SEITEN.map((seite) => [seite.id, seitenIndex(seite.id)]));
      const baueAnzeige = () => {
        const teile = new Map();
        for (const quelle of SEITEN) {
          if (!quelle.platzhalter) teile.set(quelle, teileSeite(quelle, quelle.inhalt));
        }
        let anzahl = Math.max(1, platzhalter.length);
        let inhaltsseiten = platzhalter.map((quelle, index) =>
          anzeigeSeite(quelle, "", index));
        for (let versuch = 0; versuch < 8; versuch += 1) {
          setzeAnzeige(mitInhaltsseiten(teile, inhaltsseiten));
          const neu = baueInhaltsseiten(platzhalter);
          inhaltsseiten = neu;
          if (neu.length === anzahl) break;
          anzahl = neu.length;
        }
        setzeAnzeige(mitInhaltsseiten(teile, inhaltsseiten));
      };
      baueAnzeige();
      /* Geänderte Zielnummern können selbst einen Zeilenumbruch auslösen. */
      if (hatteAnzeige &&
          SEITEN.some((seite) => vorher.get(seite.id) !== seitenIndex(seite.id))) {
        baueAnzeige();
      }
      if (zielId) {
        const ziel = seitenIndex(zielId);
        if (ziel >= 0) bogen = Math.floor((ziel + 1) / 2);
      }
      bogen = Math.max(0, Math.min(bogen, Math.floor(ANZEIGE.length / 2)));
      bilderBeobachten();
    } finally {
      umbruchLaeuft = false;
    }
    zeichne();
  }

  function umbruchPlanen(groessenwechsel = false) {
    if (groessenwechsel) $("#buch").classList.add("groessenwechsel");
    if (umbruchVorgemerkt) return;
    umbruchVorgemerkt = true;
    const spaeter = window.requestAnimationFrame || ((funktion) => setTimeout(funktion, 0));
    spaeter(() => {
      spaeter(() => {
        umbruchVorgemerkt = false;
        try {
          umbruch();
        } finally {
          $("#buch").classList.remove("groessenwechsel");
        }
      });
    });
  }

  /* ---------------------------------------------------------------------- */
  /* Drucken: das ganze Handbuch auf A4                                      */
  /* ---------------------------------------------------------------------- */

  /* ----------------------------------------------------------------
     Druck. Gemessen wird in einem unsichtbaren Rahmen mit der echten
     Blattgeometrie, damit der Umbruch nicht von der Fenstergroesse
     abhaengt und kein Text ueber den Blattrand laeuft.
     ---------------------------------------------------------------- */

  function druckStil() {
    return "@page { size: A4 landscape; margin: 0; }" +
      "* { -webkit-print-color-adjust: exact; print-color-adjust: exact;" +
      " box-sizing: border-box; }" +
      "html, body { margin: 0; padding: 0; background: #2a150e; }" +
      "body { font: 11.5pt/1.45 'Liberation Sans', 'DejaVu Sans', sans-serif;" +
      " color: #2f2921; }" +
      /* Ein Bogen ist ein aufgeschlagenes Doppel auf einem A4-Querblatt. */
      ".bogen { width: 297mm; height: 210mm; padding: 5mm; overflow: hidden;" +
      " page-break-after: always; break-after: page;" +
      " page-break-inside: avoid; break-inside: avoid;" +
      " background: linear-gradient(160deg, #6b3a29 0%, #55291c 45%, #3c1f15 100%); }" +
      ".bogen:last-child { page-break-after: auto; break-after: auto; }" +
      ".seiten { display: flex; height: 100%; border-radius: 2mm; overflow: hidden; }" +
      ".blatt, .leerblatt { position: relative; flex: 1; min-width: 0;" +
      " display: flex; flex-direction: column; padding: 7mm 8mm 4mm;" +
      " background-color: #f6efdc; }" +
      '.blatt[data-seite="links"] { background-image:' +
      " linear-gradient(90deg, rgba(0,0,0,0.13), rgba(0,0,0,0) 8%); }" +
      '.blatt[data-seite="rechts"], .leerblatt { background-image:' +
      " linear-gradient(270deg, rgba(0,0,0,0.13), rgba(0,0,0,0) 8%); }" +
      ".bindung { width: 13mm; flex: none; display: flex; flex-direction: column;" +
      " align-items: center; justify-content: space-around; padding: 8mm 0;" +
      " background: linear-gradient(90deg, #2a150e 0%, #402014 18%, #1d0f0a 50%," +
      " #402014 82%, #2a150e 100%); }" +
      ".ring { width: 6mm; height: 6mm; border-radius: 50%;" +
      " border: 0.8mm solid #e8e2d4; }" +
      ".blatt-inhalt { flex: 1; min-height: 0; }" +
      ".kapitel { font-size: 8.2pt; font-weight: 600; letter-spacing: .14em;" +
      " text-transform: uppercase; color: #7a684c; }" +
      "h2 { font-family: 'Liberation Serif', Georgia, serif; font-size: 15pt;" +
      " color: #3a3128; margin: 0.8mm 0 2.6mm; border-bottom: 0.9mm solid #d8b25c;" +
      " padding-bottom: 1.4mm; }" +
      "h3 { font-family: 'Liberation Serif', Georgia, serif; font-size: 11.6pt;" +
      " color: #463a2c; margin: 2.6mm 0 1.1mm; border-bottom: 1px dotted #ab9468;" +
      " padding-bottom: .6mm; }" +
      "p { margin: 0 0 2mm; orphans: 3; widows: 3; }" +
      "ul, ol { margin: 0 0 2mm; padding-left: 6mm; }" +
      "li { margin-bottom: .8mm; }" +
      ".merke, .beispiel, .achtung, .technik { margin: 2mm 0; padding: 1.8mm 3mm;" +
      " border-radius: 1.2mm; page-break-inside: avoid; break-inside: avoid; }" +
      ".merke { border-left: 0.8mm solid #a8823c; background: #f7f0dc; }" +
      ".beispiel { border-left: 0.8mm solid #5d7a52; background: #eef3ea; }" +
      ".achtung { border-left: 0.8mm solid #b5443a; background: #fbeceb; }" +
      ".technik { border: 1px dotted #ab9468; background: #f4f4f1; font-size: 10.4pt; }" +
      ".merke b, .beispiel b, .achtung b, .technik b:first-child { display: block; }" +
      ".technik b:first-child { font-size: 8.6pt; letter-spacing: .09em;" +
      " text-transform: uppercase; color: #4a4238; }" +
      "code { font-family: 'DejaVu Sans Mono', monospace; font-size: 10pt; }" +
      ".schritte { list-style: decimal; padding-left: 6.5mm; }" +
      "kbd { border: 1px solid #ab9468; border-radius: 1mm; padding: 0 .8mm;" +
      " font-size: 9.4pt; }" +
      ".knopfwort { border: 1px solid #ab9468; border-radius: 1mm;" +
      " padding: 0 .8mm; font-weight: 600; }" +
      "figure { margin: 2.2mm 0; text-align: center; page-break-inside: avoid; }" +
      "figure svg { max-width: 100%; max-height: 62mm; width: auto; height: auto;" +
      " border: 1px solid #cbb894; border-radius: 1.2mm; }" +
      /* Einheitliche, feste Bildhoehe. Sie haelt den Platzbedarf jeder
         Abbildung gleich und macht den Kasten schon vor dem Laden des
         Bildes messbar; sonst zaehlte ein leeres Bild als null hoch. */
      "figure img { max-width: 100%; width: auto; height: 37mm;" +
      " object-fit: contain; border: 1px solid #cbb894; border-radius: 1.2mm; }" +
      "figcaption { font-style: italic; font-size: 9.2pt; color: #5a4630; }" +
      ".abbildungsreihe { display: grid; gap: 2mm;" +
      " grid-template-columns: repeat(3, minmax(0, 1fr)); }" +
      ".abbildungsreihe figure { margin: 0; }" +
      ".abbildungsreihe img { width: 100%; height: 26mm; object-fit: contain; }" +
      ".inhalt-liste { list-style: none; padding: 0; margin: 0; }" +
      ".inhalt-eintrag { display: flex; gap: 2mm; width: 100%; border: 0;" +
      " background: none; padding: .5mm 0; font-size: 10.4pt; text-align: left; }" +
      ".inhalt-eintrag.haupt { font-weight: 600; }" +
      ".inhalt-eintrag .punkte { flex: 1; border-bottom: 1px dotted #ab9468; }" +
      ".fuss { flex: none; display: flex; justify-content: space-between;" +
      " align-items: center; margin-top: 2.5mm; padding-top: 1.4mm;" +
      " border-top: 1px dotted #ab9468; font-size: 8.4pt; color: #6a5c44; }" +
      ".fuss .zahl { font-family: 'Liberation Serif', Georgia, serif;" +
      " font-size: 9.6pt; font-weight: 600; color: #5a4630; }" +
      ".kompakt .blatt-inhalt { font-size: 10.4pt; line-height: 1.32; }" +
      ".kompakt h2 { margin-bottom: 1.9mm; padding-bottom: 1.1mm; }" +
      ".kompakt h3 { margin: 1.8mm 0 .8mm; padding-bottom: .4mm; }" +
      ".kompakt p, .kompakt ul, .kompakt ol { margin-bottom: 1.3mm; }" +
      ".kompakt li { margin-bottom: .4mm; }" +
      ".kompakt .merke, .kompakt .beispiel, .kompakt .achtung, .kompakt .technik {" +
      " margin: 1.3mm 0; padding: 1.4mm 2.6mm; }";
  }

  function druckHuelle(koerper) {
    return "<!DOCTYPE html><html lang='" + document.documentElement.lang +
      "' dir='" + (document.documentElement.dir === "rtl" ? "rtl" : "ltr") +
      "'><head><meta charset='utf-8'><title>" +
      _("Magnolie Organizer - Handbook") + "</title><style>" + druckStil() +
      "</style></head><body>" + koerper + "</body></html>";
  }

  /* Ohne bekannte Maße zaehlt ein noch nicht geladenes Bild als null hoch.
     Die vorgeladenen natuerlichen Groessen machen den Kasten berechenbar. */
  function bildmasseSetzen(markup) {
    const huelle = document.createElement("div");
    huelle.innerHTML = markup || "";
    for (const bild of huelle.querySelectorAll("img[src]")) {
      if (bild.getAttribute("width") && bild.getAttribute("height")) continue;
      let lader = null;
      try {
        lader = bildLader.get(new URL(bild.getAttribute("src"), document.baseURI).href);
      } catch (fehler) {
        lader = null;
      }
      if (lader && lader.naturalWidth && lader.naturalHeight) {
        bild.setAttribute("width", String(lader.naturalWidth));
        bild.setAttribute("height", String(lader.naturalHeight));
      }
    }
    return huelle.innerHTML;
  }

  function druckInhaltMarkup(seite) {
    return (seite.kapitel ? '<div class="kapitel">' + seite.kapitel + "</div>" : "") +
      "<h2>" + (seite.titel || "") + "</h2>" +
      '<div class="text">' +
      bildmasseSetzen(verweiseAufloesen(seite.inhalt, true)) + "</div>";
  }

  function druckMesser() {
    let rahmen = null;
    try {
      rahmen = document.createElement("iframe");
      rahmen.setAttribute("aria-hidden", "true");
      rahmen.setAttribute("tabindex", "-1");
      rahmen.style.cssText = "position:fixed;left:-20000px;top:0;width:297mm;" +
        "height:210mm;border:0;visibility:hidden;";
      document.body.appendChild(rahmen);
      const d = rahmen.contentDocument;
      if (!d) throw new Error("kein Messrahmen");
      d.open();
      /* Der Rahmen traegt das vollstaendige Doppel. Eine einzelne Seite wuerde
         sich ueber die ganze Bogenbreite dehnen und viel zu viel Text fassen. */
      d.write(druckHuelle('<div class="bogen"><div class="seiten">' +
        '<section class="blatt" data-seite="links">' +
        '<div class="blatt-inhalt"></div>' +
        '<div class="fuss"><span class="zahl">888</span>' +
        '<span class="marke">M</span></div></section>' +
        '<div class="bindung">' + '<div class="ring"></div>'.repeat(7) + '</div>' +
        '<section class="blatt" data-seite="rechts" id="mess-blatt">' +
        '<div class="blatt-inhalt" id="mess-inhalt"></div>' +
        '<div class="fuss"><span class="marke">M</span>' +
        '<span class="zahl">888</span></div></section></div></div>'));
      d.close();
      const blatt = d.getElementById("mess-blatt");
      const kasten = d.getElementById("mess-inhalt");
      if (!blatt || !kasten || !kasten.clientHeight) throw new Error("keine Messung");
      /* Der Messkasten ist bewusst zwei Millimeter niedriger als das gedruckte
         Blatt. Dieser Vorbehalt faengt Rundung und den letzten Zeilenabstand
         ab, damit kein Absatz an den Blattrand stoesst. */
      blatt.style.paddingBottom = "6mm";
      return {
        passt(seite) {
          blatt.className = "blatt" + (seite.druckKompakt ? " kompakt" : "");
          kasten.innerHTML = druckInhaltMarkup(seite);
          return kasten.scrollHeight <= kasten.clientHeight;
        },
        schliessen() {
          if (rahmen && rahmen.parentNode) rahmen.parentNode.removeChild(rahmen);
        }
      };
    } catch (fehler) {
      if (rahmen && rahmen.parentNode) rahmen.parentNode.removeChild(rahmen);
      return null;
    }
  }

  function druckVerzeichnisMarkup(seiten) {
    const liste = el("ul", "inhalt-liste");
    seiten.forEach((seite, index) => {
      if (!seite.imInhalt || (seite.teil && seite.teil > 1)) return;
      const zeile = el("li");
      const eintrag = el("div", "inhalt-eintrag" +
        (seite.imInhalt === "haupt" ? " haupt" : ""));
      eintrag.append(el("span", null, seite.titel), el("span", "punkte"),
        el("span", "zahl", String(index + 1)));
      zeile.append(eintrag);
      liste.append(zeile);
    });
    const huelle = el("div");
    huelle.append(liste);
    return huelle.innerHTML;
  }

  function druckSeiten() {
    const messer = druckMesser();
    const passt = messer ? ((seite) => messer.passt(seite)) : null;
    const teilen = (seite) => {
      const kopie = Object.assign({}, seite);
      if (!passt || passt(kopie)) return [kopie];
      return teileSeiteMit(kopie, kopie.inhalt, passt);
    };

    const platzhalter = SEITEN.filter((seite) => seite.platzhalter === "inhalt");
    const teile = new Map();
    for (const seite of SEITEN) {
      if (seite.platzhalter !== "inhalt") teile.set(seite, teilen(seite));
    }

    let verzeichnis = platzhalter.map((seite) => Object.assign({}, seite, { inhalt: "" }));
    let ergebnis = [];
    /* Das Verzeichnis nennt Seitenzahlen und veraendert dadurch seine eigene
       Laenge. Zwei bis drei Runden genuegen, bis sich nichts mehr bewegt. */
    for (let runde = 0; runde < 4; runde += 1) {
      ergebnis = [];
      let eingesetzt = false;
      for (const seite of SEITEN) {
        if (seite.platzhalter === "inhalt") {
          if (!eingesetzt) ergebnis.push(...verzeichnis);
          eingesetzt = true;
        } else {
          ergebnis.push(...teile.get(seite));
        }
      }
      if (!platzhalter.length) break;
      const markup = druckVerzeichnisMarkup(ergebnis);
      const roh = passt
        ? teileSeiteMit(platzhalter[0], markup, passt)
        : [{ inhalt: markup }];
      const neu = roh.map((seite, index) => Object.assign(
        {}, platzhalter[Math.min(index, platzhalter.length - 1)],
        { inhalt: seite.inhalt, platzhalter: "inhalt" }));
      const unveraendert = neu.length === verzeichnis.length &&
        neu.every((seite, i) => seite.inhalt === verzeichnis[i].inhalt);
      verzeichnis = neu;
      if (unveraendert) break;
    }

    if (messer) messer.schliessen();
    return ergebnis;
  }

  function druckBlatt(seite, nummer) {
    const klasse = "blatt" + (seite.druckKompakt ? " kompakt" : "");
    const seitenlage = (nummer % 2) ? "links" : "rechts";
    const zahl = '<span class="zahl">' + nummer + "</span>";
    const marke = '<span class="marke">' + _("Magnolie Organizer \u00b7 Handbook") + "</span>";
    const fuss = '<div class="fuss">' +
      (seitenlage === "links" ? zahl + marke : marke + zahl) + "</div>";
    return '<section class="' + klasse + '" data-seite="' + seitenlage + '">' +
      '<div class="blatt-inhalt">' + druckInhaltMarkup(seite) + "</div>" +
      fuss + "</section>";
  }

  function druckFassung() {
    const seiten = druckSeiten();
    druckNummern = new Map();
    seiten.forEach((seite, index) => {
      if (seite.teil && seite.teil > 1) return;
      const kennung = seite.quellId || seite.id;
      if (kennung && !druckNummern.has(kennung)) druckNummern.set(kennung, index + 1);
    });
    const blaetter = seiten.map((seite, i) => druckBlatt(seite, i + 1));
    druckNummern = null;
    const ringe = '<div class="bindung">' +
      '<div class="ring"></div>'.repeat(7) + "</div>";
    const teile = [];
    for (let i = 0; i < blaetter.length; i += 2) {
      const rechts = blaetter[i + 1] ||
        '<section class="leerblatt" data-seite="rechts"></section>';
      teile.push('<div class="bogen"><div class="seiten">' +
        blaetter[i] + ringe + rechts + "</div></div>");
    }
    return druckHuelle(teile.join(""));
  }

  function drucken() {
    const html = druckFassung();
    if (Bruecke.sende({ cmd: "drucken", html: html })) return true;
    /* Ohne Programmkern öffnet sich der Druckdialog des Browsers. */
    const fenster = window.open("", "_blank");
    if (fenster) {
      fenster.document.write(html);
      fenster.document.close();
      fenster.focus();
      setTimeout(() => fenster.print(), 400);
    }
    return false;
  }

  /* ---------------------------------------------------------------------- */
  /* Aufschlagen und Bedienung                                               */
  /* ---------------------------------------------------------------------- */

  function oeffneBuch() {
    const buch = $("#buch");
    if (buch.classList.contains("offen")) return;
    buch.classList.add("offen");
    if (!ANZEIGE.length) umbruch();
    setTimeout(() => $("#deckel").classList.add("weg"), 1250);
  }

  function start() {
    umbruch();
    if (document.fonts?.ready) document.fonts.ready.then(umbruchPlanen).catch(() => {});

    $("#deckel").addEventListener("click", oeffneBuch);
    $("#ecke-rechts").addEventListener("click", () => blaettere(1));
    $("#ecke-links").addEventListener("click", () => blaettere(-1));
    $("#knopf-inhalt").addEventListener("click", () => {
      const quelle = SEITEN.find((seite) => seite.platzhalter === "inhalt");
      const stelle = quelle ? seitenIndex(quelle.id) : -1;
      blaettereZu(stelle >= 0 ? stelle : 0);
      oeffneBuch();
    });
    $("#knopf-drucken").addEventListener("click", drucken);
    $("#knopf-suche").addEventListener("click", sucheOeffnen);
    $("#handbuch-suche-schliessen").addEventListener("click", sucheSchliessen);
    $("#handbuch-suchfeld").addEventListener("input", sucheAktualisieren);

    document.addEventListener("magnolie-locale-changed", () => {
      umbruch();
      sucheAktualisieren();
    });
    window.addEventListener("resize", () => umbruchPlanen(true));
    document.addEventListener("keydown", (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLocaleLowerCase() === "f") {
        ev.preventDefault();
        sucheOeffnen();
      } else if (ev.key === "Escape" && !$("#handbuch-suche").hidden) {
        ev.preventDefault();
        sucheSchliessen();
      } else if (ev.target && (ev.target.matches("input, textarea, select") ||
          ev.target.isContentEditable)) {
        return;
      } else if (ev.key === "ArrowRight" || ev.key === "PageDown") {
        ev.preventDefault();
        blaettere(1);
      } else if (ev.key === "ArrowLeft" || ev.key === "PageUp") {
        ev.preventDefault();
        blaettere(-1);
      } else if (ev.key === "Home") {
        ev.preventDefault();
        blaettereZu(0);
      } else if (ev.key === "End") {
        ev.preventDefault();
        blaettereZu(seitenZahl() - 1);
      } else if (ev.key === "Enter" && !$("#buch").classList.contains("offen")) {
        oeffneBuch();
      }
    });

    /* Für den Programmkern und für Prüfungen */
    window.Handbuch = {
      drucken: drucken,
      blaettere: blaettere,
      blaettereZu: blaettereZu,
      blaettereZuId: (id) => {
        const index = seitenIndex(id);
        if (index < 0) return false;
        blaettereZu(index);
        return true;
      },
      bogen: () => bogen,
      seiten: () => SEITEN,
      anzeige: () => ANZEIGE,
      neuUmbrechen: umbruch,
      druckFassung: druckFassung,
      oeffneBuch: oeffneBuch,
      suche: (anfrage) => suchTreffer(anfrage).map((seite) => seite.id),
      sucheOeffnen: sucheOeffnen,
      sucheSchliessen: sucheSchliessen
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
