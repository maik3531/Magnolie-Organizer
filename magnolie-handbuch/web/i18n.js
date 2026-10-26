/* Minimal gettext runtime for the handbook. */
"use strict";

(function (global) {
  const catalogs = Object.create(null);
  const books = [];
  let locale = "en";
  let catalog = null;

  function localeCode(value) {
    const raw = String(value || "").trim().split(/[.@]/, 1)[0].replace(/_/g, "-");
    if (!raw || raw === "system") return "en";
    if (/^zh(?:-|$)/i.test(raw)) return "zh-cn";
    return /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(raw)
      ? raw.toLowerCase() : "en";
  }

  function catalogFor(code) {
    return catalogs[code] || catalogs[code.split("-")[0]] || null;
  }

  function registerCatalog(code, data) {
    catalogs[localeCode(code)] = Object.assign({ messages: {} }, data || {});
  }

  function gettext(msgid) {
    const entry = catalog && catalog.messages[msgid];
    return typeof entry === "string" && entry ? entry : msgid;
  }

  function translateElement(element) {
    if (element.dataset.i18n) element.textContent = gettext(element.dataset.i18n);
    for (const [dataName, attribute] of [
      ["i18nTitle", "title"], ["i18nAriaLabel", "aria-label"],
      ["i18nPlaceholder", "placeholder"]
    ]) {
      if (element.dataset[dataName]) {
        element.setAttribute(attribute, gettext(element.dataset[dataName]));
      }
    }
  }

  function translateDocument(root) {
    const base = root || document;
    if (base.nodeType === 1) translateElement(base);
    base.querySelectorAll("[data-i18n], [data-i18n-title], [data-i18n-aria-label], " +
      "[data-i18n-placeholder]")
      .forEach(translateElement);
    document.title = gettext("Magnolie Organizer - Handbook");
  }

  function translateBook(book) {
    for (const page of book) {
      if (!page._source) {
        page._source = {
          kapitel: page.kapitel || "", titel: page.titel || "", inhalt: page.inhalt || ""
        };
      }
      for (const key of ["kapitel", "titel", "inhalt"]) {
        page[key] = gettext(page._source[key]);
      }
      if (page.notesRequirementsIntro) {
        const intro = page.notesRequirementsIntro[locale] || page.notesRequirementsIntro[locale.split("-")[0]] || page.notesRequirementsIntro.en;
        const sentence = /^[\s\S]*?(?:[.!?](?=\s|$)|[。।؟])/;
        page.inhalt = page.inhalt.replace(/<p>([\s\S]*?)<\/p>/, (_html, previous) => {
          const lead = previous.match(sentence)?.[0];
          if (!lead) throw new Error("Missing handbook platform overview");
          return "<p>" + lead + " " + intro.replace(sentence, "").trim() + "</p>";
        });
      }
      if (Number.isInteger(page.developerLogParagraph)) {
        const content = document.createElement("div");
        content.innerHTML = page.inhalt;
        const paragraph = content.querySelectorAll("p")[page.developerLogParagraph];
        if (!paragraph) throw new Error("Missing retired diagnostic paragraph: " + page.id);
        paragraph.remove();
        page.inhalt = content.innerHTML;
      }
      if (page.notificationDescription) {
        const content = document.createElement("div");
        content.innerHTML = page.inhalt;
        const item = content.querySelectorAll("ul > li")[5];
        const label = item && item.querySelector("b");
        if (!label) throw new Error("Missing notification settings description");
        item.replaceChildren(label, document.createTextNode(" – " +
          (page.notificationDescription[locale] || page.notificationDescription.en)));
        page.inhalt = content.innerHTML;
      }
      if (page.developerLogPath) {
        const paths = {
          en: "Settings ▸ Developer options", de: "Einstellungen ▸ Entwickleroptionen",
          fr: "Paramètres ▸ Options de développement", es: "Ajustes ▸ Opciones de desarrollador",
          it: "Impostazioni ▸ Opzioni sviluppatore", nl: "Instellingen ▸ Ontwikkelaarsopties",
          pt: "Definições ▸ Opções de desenvolvedor", cs: "Nastavení ▸ Možnosti pro vývojáře",
          pl: "Ustawienia ▸ Opcje programistyczne", hsb: "Nastajenja ▸ Wuwiwarske nastajenja",
          da: "Indstillinger ▸ Udviklerindstillinger", nb: "Innstillinger ▸ Utvikleralternativer",
          ru: "Настройки ▸ Параметры разработчика", uk: "Налаштування ▸ Параметри розробника",
          be: "Налады ▸ Параметры распрацоўшчыка", tr: "Ayarlar ▸ Geliştirici seçenekleri",
          hi: "सेटिंग ▸ डेवलपर विकल्प", ar: "الإعدادات ▸ خيارات المطوّر",
          ja: "設定 ▸ 開発者向けオプション", "zh-cn": "设置 ▸ 开发者选项"
        };
        // Each diagnostic chapter has one settings path. Labels around it remain translated.
        page.inhalt = page.inhalt.replace(/(<(?:span class=['"]knopfwort['"]|b)>)[^<]*[▸→][^<]*(<\/(?:span|b)>)/,
          (_match, open, close) => open + (paths[locale] || paths.en) + close);
      }
      if (page.entferneBildManifest) {
        const escaped = page.entferneBildManifest.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        page.inhalt = page.inhalt.replace(new RegExp(
          `<div[^>]*data-image-manifest=['"]${escaped}['"][^>]*>[\\s\\S]*?<\\/div>`), "");
      }
      if (page.inhaltAnhang) {
        const source = page.inhaltAnhang.en || "";
        const localized = page.inhaltAnhangNeutral ? source :
          (page.inhaltAnhang[locale] || page.inhaltAnhang[locale.split("-")[0]] || gettext(source));
        page.inhalt = page.inhaltAnhangErsetzt ? localized : page.inhalt + localized;
      }
      if (page.notesVerweise) page.inhalt += "<p class='notes-organizer-links'><b>Magnolie Notes:</b> " +
        page.notesVerweise.map(id => "<b data-page='" + id + "' data-page-title='true' class='knopfwort'></b>").join(" · ") + "</p>";
      if (page.notesParagraphPaths) {
        let paragraph = -1;
        const seen = new Set();
        page.inhalt = page.inhalt.replace(/<p(?:\s[^>]*)?>[\s\S]*?<\/p>/g, html => {
          paragraph++;
          const replacement = page.notesParagraphPaths.find(value => value.index === paragraph);
          if (!replacement) return html;
          const start = html.indexOf(">") + 1, text = html.slice(start, -4);
          const sentence = /^[\s\S]*?(?:[.!?](?=\s|$)|[。।؟])/;
          if (!sentence.test(text)) throw new Error("Missing retired Notes navigation sentence: " + page.id);
          seen.add(paragraph);
          const current = replacement.text[locale] || replacement.text[locale.split("-")[0]] || replacement.text.en;
          return html.slice(0, start) + text.replace(sentence, current + " ") + "</p>";
        });
        if (seen.size !== page.notesParagraphPaths.length) throw new Error("Missing Notes navigation paragraph: " + page.id);
      }
    }
  }

  function registerBook(book) {
    books.push(book);
    translateBook(book);
    return book;
  }

  function setLocale(value) {
    locale = localeCode(value);
    catalog = catalogFor(locale);
    document.documentElement.lang = catalog ? locale : "en";
    document.documentElement.dir = document.documentElement.lang.split("-")[0] === "ar" ? "rtl" : "ltr";
    books.forEach(translateBook);
    translateDocument(document);
    document.dispatchEvent(new CustomEvent("magnolie-locale-changed"));
    return document.documentElement.lang;
  }

  global.MagnolieI18n = {
    registerCatalog,
    registerBook,
    setLocale,
    gettext,
    translateDocument,
    locale: () => locale
  };
})(window);
