(function (root, factory) {
  "use strict";
  var language = factory();
  if (typeof module === "object" && module.exports) module.exports = language;
  if (!root || !root.document || !root.navigator) return;
  var script = root.document.currentScript;
  if (!script || !script.hasAttribute("data-browser-language")) return;
  var preferences = root.navigator.languages || [root.navigator.language];
  var target = language.destination(root.location.href, script.src, preferences);
  if (target) root.location.replace(target);
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";
  var routes = {"ar":"intl/ar/","be":"intl/be/","cs":"intl/cs/","da":"intl/da/","de":"de/","en":"en/","es":"intl/es/","fr":"intl/fr/","hi":"intl/hi/","hsb":"intl/hsb/","it":"intl/it/","ja":"intl/ja/","nb":"intl/nb/","nl":"intl/nl/","pl":"intl/pl/","pt":"intl/pt/","ru":"intl/ru/","tr":"intl/tr/","uk":"intl/uk/","zh-CN":"intl/zh-CN/"};
  var codes = Object.keys(routes);

  function supported(value) {
    if (typeof value !== "string") return null;
    var tag = value.trim().toLowerCase().replace(/_/g, "-");
    if (!/^[a-z]{2,8}(?:-[a-z0-9]{1,8})*$/.test(tag)) return null;
    for (var i = 0; i < codes.length; i += 1) {
      if (codes[i].toLowerCase() === tag) return codes[i];
    }
    var base = tag.split("-")[0];
    if (base === "zh") return "zh-CN";
    if (base === "no") return "nb";
    for (var j = 0; j < codes.length; j += 1) {
      if (codes[j].toLowerCase() === base) return codes[j];
    }
    return null;
  }

  function negotiate(preferences) {
    if (!Array.isArray(preferences)) preferences = [];
    for (var i = 0; i < preferences.length; i += 1) {
      var code = supported(preferences[i]);
      if (code) return code;
    }
    return "de";
  }

  function destination(currentAddress, scriptAddress, preferences) {
    try {
      var current = new URL(currentAddress);
      var base = new URL("../", scriptAddress);
      if (current.origin !== base.origin) return null;
      if (current.pathname !== base.pathname && current.pathname !== base.pathname + "index.html") return null;

      // Existing links to German-only sections keep their exact destination.
      var fragment = current.hash;
      var commonFragments = ["", "#main", "#languages", "#download", "#downloads"];
      if (commonFragments.indexOf(fragment) === -1) return null;

      var explicit = supported(current.searchParams.get("lang"));
      var code = explicit || negotiate(preferences);
      var target = new URL(routes[code], base);
      target.search = current.search;
      target.searchParams.delete("lang");
      if (fragment === "#download" || fragment === "#downloads") {
        target.hash = code === "de" || code === "en" ? "download" : "downloads";
      } else {
        target.hash = fragment;
      }
      return target.href === current.href ? null : target.href;
    } catch (error) {
      // The static German entry remains usable in older or restricted browsers.
      return null;
    }
  }

  return { routes: routes, supported: supported, negotiate: negotiate, destination: destination };
});
