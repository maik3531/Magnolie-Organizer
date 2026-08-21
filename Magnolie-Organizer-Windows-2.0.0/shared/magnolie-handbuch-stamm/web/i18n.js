/* Minimal gettext runtime for the handbook. */
"use strict";

(function (global) {
  const catalogs = Object.create(null);
  const books = [];
  let locale = "en";
  let catalog = null;

  function localeCode(value) {
    const raw = String(value || "").trim().replace(/_/g, "-");
    if (!raw || raw === "system") return "en";
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
      if (page.entferneBildManifest) {
        const escaped = page.entferneBildManifest.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        page.inhalt = page.inhalt.replace(new RegExp(
          `<div[^>]*data-image-manifest=['"]${escaped}['"][^>]*>[\\s\\S]*?<\\/div>`), "");
      }
      if (page.inhaltAnhang) {
        page.inhalt += page.inhaltAnhang[locale] || page.inhaltAnhang.en || "";
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
    document.documentElement.dir = document.documentElement.lang === "ar" ? "rtl" : "ltr";
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
