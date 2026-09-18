"use strict";

// Keep the established German presentation when no host selects a language.
(function () {
  const supported = ["en", "de", "ar", "be", "cs", "da", "es", "fr", "hi", "hsb",
    "it", "ja", "nb", "nl", "pl", "pt", "ru", "tr", "uk", "zh-cn"];
  const resolve = (value) => {
    const code = String(value || "").trim().replace(/_/g, "-").toLowerCase();
    if (code === "zh" || code.startsWith("zh-")) return "zh-cn";
    return supported.find((item) => code === item || code.startsWith(item + "-")) || "";
  };
  let saved = "";
  try {
    saved = localStorage.getItem("magnolie-handbook-locale") ||
      localStorage.getItem("magnolie-locale") || "";
  } catch (_error) {}
  const browser = navigator.languages && navigator.languages.length
    ? navigator.languages : [navigator.language];
  const candidates = [window.__MAGNOLIE_SPRACHE__, window.MAGNOLIE_LOCALE, saved]
    .concat(browser || [], ["de", "en"]);
  window.MagnolieI18n.setLocale(candidates.map(resolve).find(Boolean) || "de");
})();
