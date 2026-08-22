"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const WEB = process.env.MAGNOLIE_HANDBUCH_WEB || path.join(ROOT, "web");
const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
const runtime = fs.readFileSync(path.join(WEB, "handbuch.js"), "utf8");
const css = fs.readFileSync(path.join(WEB, "stil.css"), "utf8");

let capacity = 100;
let imageHeight = 20;

function height(element) {
  if (element.matches(".inhalt-liste")) return element.children.length * 25;
  if (element.matches("ol, ul")) {
    return Array.from(element.children).reduce((sum, child) => sum + height(child), 0);
  }
  if (element.matches("figure") && element.querySelector("img")) return imageHeight;
  return Number(element.dataset.height || (element.matches("li") ? 30 : 0));
}

function createBook() {
  const dom = new JSDOM(html, {
    url: "https://handbook.test/", pretendToBeVisual: true, runScripts: "outside-only"
  });
  const w = dom.window;
  const pages = [
    { id: "intro", kapitel: "Test", titel: "Intro", inhalt:
      "<p data-height='40'>A</p><p data-height='40'>B</p><p data-height='40'>C</p>" },
    { id: "contents", kapitel: "Test", titel: "Contents", platzhalter: "inhalt", inhalt: "" },
    { id: "contents-continued", kapitel: "Test", titel: "Contents continued",
      platzhalter: "inhalt", inhalt: "" },
    { id: "ordered", kapitel: "Test", titel: "Ordered", imInhalt: "haupt", inhalt:
      "<ol start='3'><li data-height='30'>Three</li><li data-height='30'>Four</li>" +
      "<li data-height='30'>Five</li><li data-height='30'>Six</li></ol>" },
    { id: "margins", kapitel: "Test", titel: "Margins", imInhalt: true, inhalt:
      "<p data-height='40'>First</p><p data-height='45' style='margin-bottom:20px'>Second</p>" },
    { id: "picture", kapitel: "Test", titel: "Picture", imInhalt: true, inhalt:
      "<p data-height='60'>Text</p><figure><img src='probe.png' alt='Probe'></figure>" },
    { id: "language", kapitel: "Test", titel: "Language", imInhalt: true, inhalt:
      "<p data-height='40'>One</p><p data-height='40'>Two</p>" },
    { id: "target", kapitel: "Test", titel: "Target", imInhalt: true, inhalt:
      "<p data-height='20'>Target <b data-page='ordered'></b></p>" },
    { id: "extra-1", titel: "Extra 1", imInhalt: true, inhalt: "<p data-height='20'>1</p>" },
    { id: "extra-2", titel: "Extra 2", imInhalt: true, inhalt: "<p data-height='20'>2</p>" },
    { id: "extra-3", titel: "Extra 3", imInhalt: true, inhalt: "<p data-height='20'>3</p>" },
    { id: "extra-4", titel: "Extra 4", imInhalt: true, inhalt: "<p data-height='20'>4</p>" },
    { id: "extra-5", titel: "Extra 5", imInhalt: true, inhalt: "<p data-height='20'>5</p>" },
    { id: "support-with-a-coffee", titel: "Coffee", inhalt:
      "<p data-height='80'>Protected A</p><p data-height='80'>Protected B</p>" }
  ];
  const sourceMarkup = pages.map((page) => page.inhalt);
  let measurements = 0;
  w.HANDBUCH_SEITEN = pages;
  w.MagnolieI18n = {
    gettext: (text) => text,
    setLocale(locale) {
      const page = pages.find((item) => item.id === "language");
      page.inhalt = locale === "de"
        ? "<p data-height='40'>Eins</p><p data-height='40'>Zwei</p><p data-height='40'>Drei</p>"
        : "<p data-height='40'>One</p><p data-height='40'>Two</p>";
      w.document.dispatchEvent(new w.CustomEvent("magnolie-locale-changed"));
    }
  };

  Object.defineProperty(w.HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get() {
      if (!this.classList.contains("seiten-inhalt")) return 0;
      measurements += 1;
      return capacity;
    }
  });
  Object.defineProperty(w.HTMLElement.prototype, "scrollHeight", {
    configurable: true,
    get() {
      if (!this.classList.contains("seiten-inhalt")) return 0;
      return Array.from(this.children).reduce((sum, child) => sum + height(child), 0);
    }
  });
  w.HTMLElement.prototype.getBoundingClientRect = function () {
    if (this.classList.contains("seiten-inhalt")) {
      return { top: 0, bottom: capacity, height: capacity, left: 0, right: 500, width: 500 };
    }
    const parent = this.parentElement;
    const siblings = parent ? Array.from(parent.children) : [];
    const bottom = siblings.slice(0, siblings.indexOf(this) + 1)
      .reduce((sum, child) => sum + height(child), 0);
    return { top: bottom - height(this), bottom, height: height(this), left: 0, right: 500, width: 500 };
  };

  w.eval(runtime);
  if (!w.Handbuch) w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  return { dom, w, H: w.Handbuch, pages, sourceMarkup,
    measurements: () => measurements };
}

async function run() {
  assert.match(css, /\.seiten-inhalt\s*\{[^}]*overflow:\s*hidden/s);
  assert.ok(!css.includes("scroll-ausnahme"), "no handbook page may enable an inner scrollbar");
  assert.ok(!/\.seiten-inhalt\s*\{[^}]*overflow-y:\s*auto/s.test(css));

  const { dom, w, H, pages, sourceMarkup, measurements } = createBook();
  const shown = () => H.anzeige();
  const parts = (id) => shown().filter((page) => page.quellId === id);

  const initialMeasurements = measurements();
  H.neuUmbrechen();
  assert.strictEqual(measurements() - initialMeasurements, initialMeasurements,
    "initial pagination must perform exactly one full display build");
  const beforeOpen = measurements();
  w.document.querySelector("#deckel").click();
  assert.strictEqual(measurements(), beforeOpen,
    "opening an already paginated handbook must not paginate again");
  assert.ok(w.document.querySelector("#buch").classList.contains("offen"),
    "the optimized handbook opening must still open the book");

  assert.strictEqual(parts("intro").length, 2, "blocks must break at measured height");
  assert.strictEqual(parts("ordered").length, 2, "lists must break between list items");
  assert.strictEqual(new JSDOM(parts("ordered")[1].inhalt).window.document.querySelector("ol").start, 6,
    "continued ordered lists need the correct start value");
  assert.strictEqual(parts("margins").length, 2, "the last block margin must count towards height");
  assert.ok(shown().filter((page) => page.istVerzeichnis).length >= 3,
    "the table of contents must grow beyond its two source placeholders");
  assert.deepStrictEqual(pages.map((page) => page.inhalt), sourceMarkup,
    "pagination must not mutate translated source pages");

  H.blaettereZuId("target");
  const targetPage = pages.findIndex((page) => page.id === "ordered") + 1;
  assert.strictEqual(w.document.querySelector("[data-page='ordered']").textContent, String(targetPage));

  H.blaettereZuId("picture");
  imageHeight = 60;
  w.document.querySelector("#seiten img").dispatchEvent(new w.Event("load"));
  await new Promise((resolve) => w.setTimeout(resolve, 30));
  assert.strictEqual(parts("picture").length, 2, "image dimensions loaded later must repaginate");

  w.MagnolieI18n.setLocale("de");
  assert.strictEqual(parts("language").length, 2, "a locale change must measure translated markup again");

  H.blaettereZuId("support-with-a-coffee");
  assert.strictEqual(parts("support-with-a-coffee").length, 2,
    "the protected coffee text must use two pages without changing its source");
  assert.ok(!w.document.querySelector(".seiten-inhalt.scroll-ausnahme"),
    "the coffee pages must not use an inner scrollbar");

  if (shown().length % 2) {
    pages.push({ id: "end-parity", titel: "End parity", inhalt: "<p data-height='20'>End</p>" });
    H.neuUmbrechen();
  }
  const finalSource = shown()[shown().length - 1].quellId;
  H.blaettereZu(shown().length - 1);
  H.neuUmbrechen();
  const visibleSources = () => [H.bogen() * 2 - 1, H.bogen() * 2]
    .map((index) => shown()[index] && shown()[index].quellId).filter(Boolean);
  assert.ok(visibleSources().includes(finalSource),
    "repagination on a final left page must not jump to the first page");
  w.document.body.dispatchEvent(new w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
  assert.ok(visibleSources().includes(finalSource),
    "the right arrow at the end must keep the final page visible");

  const beforeResize = shown().length;
  capacity = 60;
  const rahmen = [];
  w.requestAnimationFrame = (funktion) => rahmen.push(funktion);
  w.dispatchEvent(new w.Event("resize"));
  assert.strictEqual(rahmen.length, 1, "resize must schedule the paint frame");
  rahmen.shift()();
  assert.strictEqual(shown().length, beforeResize,
    "resize must let the scaled book paint before repagination");
  assert.strictEqual(rahmen.length, 1, "repagination must follow in a separate frame");
  rahmen.shift()();
  assert.ok(shown().length > beforeResize, "resize must schedule a fresh measurement");

  dom.window.close();
  console.log("HANDBOOK DYNAMIC PAGINATION PASSED");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
