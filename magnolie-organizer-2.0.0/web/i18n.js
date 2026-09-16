/* Minimaler gettext-Laufzeitkern für die WebKit-Oberfläche. */
"use strict";

(function (global) {
  const kataloge = Object.create(null);
  let sprache = "de"; // Fundamentphase: bestehende Darstellung unverändert lassen.
  let katalog = null;

  function sprachCode(wert) {
    const roh = String(wert || "").trim().replace(/_/g, "-");
    if (!roh || roh === "system") {
      const system = (global.navigator && (global.navigator.languages ||
        [global.navigator.language])).find(Boolean);
      return sprachCode(system || "en");
    }
    if (/^zh(?:-|$)/i.test(roh)) return "zh-cn";
    return /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(roh)
      ? roh.toLowerCase() : "en";
  }

  function katalogFuer(code) {
    return kataloge[code] || kataloge[code.split("-")[0]] || null;
  }

  function pluralFunktion(regel) {
    const rueckfall = (n) => Number(Number(n) !== 1);
    try {
      const felder = Object.create(null);
      for (const teil of String(regel || "").split(";")) {
        if (!teil.trim()) continue;
        const feld = teil.match(/^\s*([A-Za-z]+)\s*=\s*(.*?)\s*$/);
        if (!feld || felder[feld[1].toLowerCase()] !== undefined) throw new Error();
        felder[feld[1].toLowerCase()] = feld[2];
      }
      if (!/^[1-9][0-9]*$/.test(felder.nplurals || "")) throw new Error();
      const formen = Number(felder.nplurals);
      const ausdruck = felder.plural || "";
      if (formen > 16 || !ausdruck || ausdruck.length > 512) throw new Error();

      const token = [];
      for (let pos = 0; pos < ausdruck.length;) {
        const rest = ausdruck.slice(pos);
        const leer = rest.match(/^\s+/);
        if (leer) { pos += leer[0].length; continue; }
        const zahl = rest.match(/^[0-9]+/);
        if (zahl) {
          if (zahl[0].length > 16) throw new Error();
          token.push({ art: "zahl", wert: Number(zahl[0]) });
          pos += zahl[0].length;
          continue;
        }
        if (rest[0] === "n") {
          token.push({ art: "n" }); pos += 1; continue;
        }
        const doppelt = rest.slice(0, 2);
        if (["||", "&&", "==", "!=", "<=", ">="].includes(doppelt)) {
          token.push({ art: doppelt }); pos += 2; continue;
        }
        if ("?:<>+-*/%!()".includes(rest[0])) {
          token.push({ art: rest[0] }); pos += 1; continue;
        }
        throw new Error();
      }
      if (!token.length || token.length > 256) throw new Error();
      token.push({ art: "ende" });

      let stelle = 0;
      let tiefe = 0;
      const ist = (art) => token[stelle].art === art;
      const nimm = (art) => {
        if (!ist(art)) throw new Error();
        return token[stelle++];
      };
      const sicher = (wert) => {
        if (!Number.isSafeInteger(wert)) throw new Error();
        return wert;
      };
      const binaer = (art, links, rechts) => (n) => {
        if (art === "&&") return links(n) ? Number(!!rechts(n)) : 0;
        if (art === "||") return links(n) ? 1 : Number(!!rechts(n));
        const a = links(n), b = rechts(n);
        if (art === "==") return Number(a === b);
        if (art === "!=") return Number(a !== b);
        if (art === "<") return Number(a < b);
        if (art === "<=") return Number(a <= b);
        if (art === ">") return Number(a > b);
        if (art === ">=") return Number(a >= b);
        if (art === "+") return sicher(a + b);
        if (art === "-") return sicher(a - b);
        if (art === "*") return sicher(a * b);
        if ((art === "/" || art === "%") && b === 0) throw new Error();
        if (art === "/") return sicher(Math.trunc(a / b));
        return sicher(a % b);
      };
      let bedingt;
      const primaer = () => {
        if (ist("zahl")) {
          const wert = nimm("zahl").wert;
          if (!Number.isSafeInteger(wert)) throw new Error();
          return () => wert;
        }
        if (ist("n")) { nimm("n"); return (n) => n; }
        if (ist("(")) {
          nimm("(");
          if (++tiefe > 32) throw new Error();
          const wert = bedingt();
          nimm(")");
          tiefe -= 1;
          return wert;
        }
        throw new Error();
      };
      const unaer = () => {
        if (["!", "+", "-"].includes(token[stelle].art)) {
          const art = token[stelle++].art;
          const wert = unaer();
          if (art === "!") return (n) => Number(!wert(n));
          if (art === "+") return (n) => sicher(wert(n));
          return (n) => sicher(-wert(n));
        }
        return primaer();
      };
      const ebene = (weiter, operatoren) => () => {
        let links = weiter();
        while (operatoren.includes(token[stelle].art)) {
          const art = token[stelle++].art;
          links = binaer(art, links, weiter());
        }
        return links;
      };
      const mal = ebene(unaer, ["*", "/", "%"]);
      const plus = ebene(mal, ["+", "-"]);
      const vergleich = ebene(plus, ["<", "<=", ">", ">="]);
      const gleich = ebene(vergleich, ["==", "!="]);
      const und = ebene(gleich, ["&&"]);
      const oder = ebene(und, ["||"]);
      bedingt = () => {
        const frage = oder();
        if (!ist("?")) return frage;
        nimm("?");
        const ja = bedingt();
        nimm(":");
        const nein = bedingt();
        return (n) => frage(n) ? ja(n) : nein(n);
      };
      const berechnen = bedingt();
      nimm("ende");
      return (n) => {
        const anzahl = Number(n);
        if (!Number.isSafeInteger(anzahl) || anzahl < 0) return rueckfall(anzahl);
        try {
          const wert = berechnen(anzahl);
          return Number.isInteger(wert) && wert >= 0 && wert < formen ? wert : 0;
        } catch (_fehler) {
          return rueckfall(anzahl);
        }
      };
    } catch (_fehler) {
      return rueckfall;
    }
  }

  function registrieren(code, daten) {
    const sauber = sprachCode(code);
    kataloge[sauber] = Object.assign({ messages: {}, pluralForms: "" }, daten || {});
    kataloge[sauber]._plural = pluralFunktion(kataloge[sauber].pluralForms);
  }

  function schluessel(msgid, kontext) {
    return kontext ? kontext + "\u0004" + msgid : msgid;
  }

  function gettext(msgid, kontext) {
    const eintrag = katalog && katalog.messages[schluessel(msgid, kontext)];
    return typeof eintrag === "string" && eintrag ? eintrag : msgid;
  }

  function ngettext(einzahl, mehrzahl, anzahl, kontext) {
    const eintrag = katalog && katalog.messages[schluessel(einzahl, kontext)];
    if (Array.isArray(eintrag) && eintrag.length) {
      const index = Math.min(katalog._plural(Number(anzahl)), eintrag.length - 1);
      return eintrag[index] || eintrag[0] || (Number(anzahl) === 1 ? einzahl : mehrzahl);
    }
    return Number(anzahl) === 1 ? einzahl : mehrzahl;
  }

  function format(text, werte) {
    return String(text).replace(/%\(([^)]+)\)s/g, (_alles, name) =>
      Object.prototype.hasOwnProperty.call(werte || {}, name) ? String(werte[name]) : _alles);
  }

  function uebersetzeElement(element) {
    if (element.dataset.i18n) element.textContent = gettext(element.dataset.i18n);
    for (const [datenName, attribut] of [
      ["i18nTitle", "title"], ["i18nAriaLabel", "aria-label"],
      ["i18nPlaceholder", "placeholder"]
    ]) {
      if (element.dataset[datenName]) {
        element.setAttribute(attribut, gettext(element.dataset[datenName]));
      }
    }
  }

  function uebersetzeDokument(wurzel) {
    const basis = wurzel || document;
    if (basis.nodeType === 1) uebersetzeElement(basis);
    basis.querySelectorAll("[data-i18n], [data-i18n-title], " +
      "[data-i18n-aria-label], [data-i18n-placeholder]").forEach(uebersetzeElement);
  }

  function setzeSprache(wert) {
    sprache = sprachCode(wert);
    katalog = katalogFuer(sprache);
    document.documentElement.lang = katalog ? sprache : "en";
    document.documentElement.dir = document.documentElement.lang === "ar" ? "rtl" : "ltr";
    uebersetzeDokument(document);
    return document.documentElement.lang;
  }

  global.MagnolieI18n = {
    registerCatalog: registrieren,
    setLocale: setzeSprache,
    gettext: gettext,
    pgettext: (kontext, msgid) => gettext(msgid, kontext),
    ngettext: ngettext,
    format: format,
    translateDocument: uebersetzeDokument,
    locale: () => sprache
  };
})(window);
