#!/usr/bin/env python3
"""Render static legal pages and language links from reviewed UTF-8 translations.

Python 3.9+, standard library only. Run normally after editing a translation or
operator details, or use --check to reject stale generated files without edits.
"""

import argparse
from collections import Counter
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "assets/legal-locales"
TOKEN = re.compile(r"\{\{([a-z_]+)\}\}")


class Fragment(HTMLParser):
    """Translations may contain only the original small inline markup set."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"a", "strong", "em", "bdi", "br"}:
            raise ValueError(f"Unsupported translation markup: {tag}")
        if tag == "a":
            if len(attrs) != 1 or attrs[0][0] != "href":
                raise ValueError("Translation anchors must contain only href")
            self.links.append(attrs[0][1])
        elif attrs:
            raise ValueError(f"Unexpected attributes in {tag}")
        if tag != "br":
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError(f"Unbalanced translation markup: {tag}")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != "br":
            self.handle_endtag(tag)


def inline_links(value):
    parser = Fragment()
    parser.feed(value)
    parser.close()
    if parser.stack:
        raise ValueError("Unclosed translation markup")
    return Counter(parser.links)


def check_translation(source, translated, path=""):
    if type(source) is not type(translated):
        raise ValueError(f"Translation type mismatch: {path}")
    if isinstance(source, dict):
        if source.keys() != translated.keys():
            raise ValueError(f"Translation keys differ: {path}")
        for key in source:
            check_translation(source[key], translated[key], f"{path}.{key}")
    elif isinstance(source, list):
        if len(source) != len(translated):
            raise ValueError(f"Translation list length differs: {path}")
        for index, item in enumerate(source):
            check_translation(item, translated[index], f"{path}[{index}]")
    elif isinstance(source, str):
        if not translated.strip():
            raise ValueError(f"Empty translation: {path}")
        if path.endswith((".id", ".kind")) and source != translated:
            raise ValueError(f"Structural translation value changed: {path}")
        if Counter(TOKEN.findall(source)) != Counter(TOKEN.findall(translated)):
            raise ValueError(f"Translation placeholders differ: {path}")
        if inline_links(source) != inline_links(translated):
            raise ValueError(f"Translation link targets differ: {path}")


def load_data():
    config = json.loads((DATA / "languages.json").read_text(encoding="utf-8"))
    source = json.loads((DATA / "de.json").read_text(encoding="utf-8"))
    operator = json.loads((DATA / "operator.json").read_text(encoding="utf-8"))
    translations = {}
    for entry in config["languages"]:
        code = entry["code"]
        translated = json.loads((DATA / f"{code}.json").read_text(encoding="utf-8"))
        check_translation(source, translated, code)
        if translated["locale"] != code:
            raise ValueError(f"Unexpected locale in {code}.json")
        if translated["direction"] != ("rtl" if code == "ar" else "ltr"):
            raise ValueError(f"Unexpected writing direction in {code}.json")
        translations[code] = translated
    if len(translations) != 20:
        raise ValueError("Exactly 20 distinct language sources are required")
    return config, operator, translations


def page_path(code, kind):
    prefix = "" if code == "de" else "en/" if code == "en" else f"intl/{code}/"
    return PurePosixPath(prefix + ("impressum" if kind == "imprint" else "datenschutz") + "/index.html")


def relative(page, destination, directory=False):
    value = posixpath.relpath(str(destination), str(PurePosixPath(page).parent))
    if directory:
        return "./" if value == "." else value + "/"
    return value


def directory_url(page, target):
    return relative(page, PurePosixPath(target).parent, directory=True)


def fragment(value, context):
    def replace(match):
        key = match.group(1)
        if key not in context:
            raise ValueError(f"Unknown legal text placeholder: {key}")
        return context[key]
    rendered = TOKEN.sub(replace, value)
    rendered = re.sub(r'<a href="(mailto:[^"]+)">', r'<a href="\1" dir="ltr">', rendered)
    if context.get('_rtl'):
        addresses = [
            'GitHub B.V., Prins Bernhardplein 200, 1097 JB Amsterdam, Niederlande',
            'GitHub, Inc., 88 Colin P. Kelly Jr. St., San Francisco, CA 94107, USA',
            'Google Ireland Limited, Gordon House, Barrow Street, Dublin 4, Irland',
            'GPL-3.0-or-later',
        ]
        for address in addresses:
            rendered = rendered.replace(address, '<bdi dir="ltr">' + escape(address) + '</bdi>')
        law = r'Art\.\s*\d+(?:[–-]\d+)?(?:\s+Abs\.\s*\d+)?(?:\s+Buchst\.\s*[a-z])?\s+DSGVO|§\s*\d+\s*Abs\.\s*\d+\s*MStV'
        rendered = re.sub(law, lambda m: '<bdi dir="ltr">' + escape(m.group(0)) + '</bdi>', rendered)
    return rendered


def alternates(config, kind=None):
    links = []
    for entry in config["languages"]:
        target = str(page_path(entry["code"], kind).parent) + "/" if kind else entry["home"]
        links.append(f'<link rel="alternate" hreflang="{entry["code"]}" href="{config["source_url"]}/{target}">')
    default = str(page_path("de", kind).parent) + "/" if kind else ""
    links.append(f'<link rel="alternate" hreflang="x-default" href="{config["source_url"]}/{default}">')
    return "\n".join(links)


def legal_page(config, operator, translations, code, kind):
    text = translations[code]
    labels = text["labels"]
    page = page_path(code, kind)
    home = next(item["home"] for item in config["languages"] if item["code"] == code)
    home_url = relative(page, home.rstrip("/"), directory=True)
    imprint_url = directory_url(page, page_path(code, "imprint"))
    privacy_url = directory_url(page, page_path(code, "privacy"))
    context = {"operator_name": "<bdi>" + escape(operator["name"]) + "</bdi>",
               "email": escape(operator["email"], quote=True),
               "project_notice": escape(text["project_notice"]),
               "_rtl": code == "ar",
               "imprint_url": imprint_url, "privacy_url": privacy_url,
               "source_notices_url": relative(page, "SOURCE-NOTICES.txt")}
    sections = []
    article = text[kind]
    for section in article["sections"]:
        sid = section["id"]
        parts = [f'<section id="{sid}" aria-labelledby="{sid}-title">',
                 f'<h2 id="{sid}-title">{escape(section["title"])}</h2>']
        if section.get("kind") == "provider":
            parts.append('<address><strong><bdi>' + escape(operator["name"]) + '</bdi></strong><br>'
                         '<bdi>' + escape(operator["street"]) + '</bdi><br>'
                         '<bdi>' + escape(operator["postal_city"]) + '</bdi><br>'
                         + escape(labels["country"]) + '</address>')
            parts.append('<p>' + escape(labels["email"]) + ': <a dir="ltr" href="mailto:'
                         + escape(operator["email"], quote=True) + '">' + escape(operator["email"]) + '</a></p>')
        else:
            parts.extend('<p>' + fragment(value, context) + '</p>' for value in section["paragraphs"])
        parts.append('</section>')
        sections.append("\n".join(parts))
    choices = []
    for entry in config["languages"]:
        current = ' aria-current="page"' if entry["code"] == code else ''
        choices.append(f'<a href="{directory_url(page, page_path(entry["code"], kind))}" '
                       f'hreflang="{entry["code"]}" lang="{entry["code"]}"{current}>'
                       f'<bdi>{escape(entry["name"])}</bdi></a>')
    source_link = '' if code == "de" else '<p class="language-note"><a lang="de" hreflang="de" href="' + directory_url(page, page_path("de", kind)) + '">' + escape(labels["german_original"]) + '</a></p>'
    contents = '<nav class="contents" aria-label="' + escape(labels["contents"], quote=True) + '">' + ''.join('<a href="#' + section["id"] + '">' + escape(section["title"]) + '</a>' for section in article["sections"]) + '</nav>'
    imprint_current = ' aria-current="page"' if kind == "imprint" else ''
    privacy_current = ' aria-current="page"' if kind == "privacy" else ''
    return f'''<!doctype html>
<html lang="{code}" dir="{text['direction']}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(article['title'])} · Magnolie Organizer</title>
<meta name="description" content="{escape(article['description'], quote=True)}">
<meta name="theme-color" content="#304d3b"><meta name="robots" content="noindex,follow">
<link rel="canonical" href="{config['source_url']}/{page.parent}/">
{alternates(config, kind)}
<link rel="icon" href="{relative(page, 'assets/favicon.svg')}" type="image/svg+xml">
<link rel="stylesheet" href="{relative(page, 'assets/legal.css')}">
</head>
<body>
<a class="skip" href="#inhalt">{escape(labels['skip'])}</a>
<header class="top"><nav class="nav wrap" aria-label="{escape(labels['main_navigation'], quote=True)}">
<a class="brand" href="{home_url}"><bdi>magnolie</bdi><small>Organizer</small></a>
<div class="nav-links"><a href="{home_url}">{escape(labels['home'])}</a><a href="{relative(page, 'presse', directory=True)}" hreflang="de">{escape(labels['press'])}</a><a href="{home_url}#{'download' if code in ('de', 'en') else 'downloads'}">{escape(labels['downloads'])}</a></div>
<details class="language-picker"><summary>{escape(labels['language'])}: <bdi>{escape(text['language_name'])}</bdi></summary><nav class="language-options" aria-label="{escape(labels['language'], quote=True)}">{''.join(choices)}</nav></details>
</nav></header>
<main id="inhalt" class="legal wrap">
<p class="eyebrow"><bdi>Magnolie Organizer</bdi></p>
<h1>{escape(article['title'])}</h1><p class="lead">{escape(article['lead'])}</p>
{source_link}
{contents}
{chr(10).join(sections)}
<p class="date">{escape(labels['updated'])}</p>
</main>
<footer class="foot wrap"><p><bdi>Magnolie Organizer · {escape(operator['name'])}</bdi><br>{escape(labels['footer_project'])}</p><nav class="foot-links" aria-label="{escape(labels['more_information'], quote=True)}"><a href="{home_url}">{escape(labels['home'])}</a><a href="{imprint_url}"{imprint_current}>{escape(labels['imprint'])}</a><a href="{privacy_url}"{privacy_current}>{escape(labels['privacy'])}</a></nav></footer>
</body></html>
'''


def replace_language_metadata(text, config):
    text = re.sub(r'<link rel="alternate" hreflang="[^"]+" href="[^"]+">\s*', '', text)
    text = text.replace('</head>', alternates(config) + '\n</head>')
    text = re.sub(r'\s*<small lang="en">English guide</small>', '', text)
    # German now has a fixed URL too, so manual choices never restart detection.
    def german_link(match):
        tag = match.group(0)
        if re.search(r'(?:hreflang|lang)="de"', tag):
            href = re.search(r'href="([^"]+)"', tag)
            if href and href[1] in {'./', '../', '../../'}:
                tag = tag.replace('href="' + href[1] + '"', 'href="' + href[1] + 'de/"', 1)
        return tag
    return re.sub(r'<a\b[^>]*>', german_link, text)


def homepage(config, translations, code, path, text):
    labels = translations[code]["labels"]
    text = replace_language_metadata(text, config)
    imprint_url = directory_url(path, page_path(code, "imprint"))
    privacy_url = directory_url(path, page_path(code, "privacy"))
    press_url = relative(path, "presse", directory=True)
    prefix = [('imprint', imprint_url), ('privacy', privacy_url), ('press', press_url),
              ('project', 'https://github.com/maik3531/Magnolie-Organizer'),
              ('product_information', 'https://github.com/maik3531/Magnolie-Organizer/blob/main/' + ('README.DE.md' if code == 'de' else 'README.md')),
              ('license', 'https://github.com/maik3531/Magnolie-Organizer/blob/main/LICENSE')]
    if code in {'de', 'en'}:
        prefix.append(('feedback', 'https://github.com/maik3531/Magnolie-Organizer/issues'))
    links = ''.join('<a href="' + href + '">' + escape(labels[key]) + '</a>' for key, href in prefix)
    link_class = 'foot-links' if code in {'de', 'en'} else 'footer-links'
    text, count = re.subn(r'<div class="' + link_class + r'">.*?</div>', '<div class="' + link_class + '">' + links + '</div>', text, count=1, flags=re.S)
    if count != 1:
        raise ValueError(f"Missing home footer links: {path}")
    note = '<span data-project-notice>' + escape(translations[code]["project_notice"]) + '</span> ' + escape(labels["source_note"])
    if code in {'de', 'en'}:
        text, count = re.subn(r'<div class="foot-fine">.*?</div>', '<div class="foot-fine"><p>' + note + '</p><p>' + escape(labels['downloads_note']) + '</p></div>', text, count=1, flags=re.S)
    else:
        text, count = re.subn(r'<p class="source-note"[^>]*>.*?</p>', '<p class="source-note" lang="' + code + '">' + note + '</p>', text, count=1, flags=re.S)
    if count != 1:
        raise ValueError(f"Missing home source note: {path}")
    return text


def german_home(text, config):
    text = re.sub(r'<script\b[^>]*data-browser-language[^>]*>\s*</script>\s*', '', text)
    def prefix(match):
        attribute, value = match.group(1), match.group(2)
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return match.group(0)
        if value == './':
            return match.group(0)
        return attribute + '="../' + value + '"'
    text = re.sub(r'(href|src|poster)="([^"]+)"', prefix, text)
    text = re.sub(r'(<link rel="canonical" href=")[^"]+(">)', lambda m: m.group(1) + config['source_url'] + '/de/' + m.group(2), text)
    return text


def outputs():
    config, operator, translations = load_data()
    result = {}
    for code in translations:
        for kind in ("imprint", "privacy"):
            result[str(page_path(code, kind))] = legal_page(config, operator, translations, code, kind)

    root_text = (ROOT / 'index.html').read_text(encoding='utf-8')
    root_text = homepage(config, translations, 'de', 'index.html', root_text)
    if 'data-browser-language' not in root_text:
        root_text = root_text.replace('<head>', '<head>\n<script src="assets/language.js" data-browser-language></script>', 1)
    result['index.html'] = root_text
    result['de/index.html'] = german_home(root_text, config)
    result['en/index.html'] = homepage(config, translations, 'en', 'en/index.html', (ROOT / 'en/index.html').read_text(encoding='utf-8'))

    sorbian = json.loads((DATA / 'hsb-home.json').read_text(encoding='utf-8'))
    sorbian_template = (ROOT / 'tools/templates/hsb-home.html').read_text(encoding='utf-8')
    for entry in config['languages']:
        code = entry['code']
        if code in {'de', 'en'}:
            continue
        path = f'intl/{code}/index.html'
        if code == 'hsb':
            text = re.sub(r'\{\{home\.([a-z_]+)\}\}', lambda m: escape(sorbian[m.group(1)], quote=True), sorbian_template)
            if '{{home.' in text:
                raise ValueError('Unresolved Sorbian homepage text')
        else:
            text = (ROOT / path).read_text(encoding='utf-8')
        result[path] = homepage(config, translations, code, path, text)

    press = (ROOT / 'presse/index.html').read_text(encoding='utf-8')
    press = re.sub(r'(<footer>.*?<span>).*?(</span>)', lambda m: m.group(1) + 'Gesammelt mit Dank. Verlinkt im Original.<br>' + escape(translations['de']['project_notice']) + m.group(2), press, count=1, flags=re.S)
    result['presse/index.html'] = press

    routes = {entry['code']: entry['home'] for entry in config['languages']}
    language_template = (ROOT / 'tools/templates/language.js').read_text(encoding='utf-8')
    result['assets/language.js'] = language_template.replace('{{language_routes}}', json.dumps(routes, ensure_ascii=False, separators=(',', ':')))

    urls = [config['source_url'] + '/']
    urls.extend(config['source_url'] + '/' + entry['home'] for entry in config['languages'])
    urls.append(config['source_url'] + '/presse/')
    urls.extend(config['source_url'] + '/' + str(page_path(code, kind).parent) + '/' for code in translations for kind in ('imprint', 'privacy'))
    ET.register_namespace('', 'http://www.sitemaps.org/schemas/sitemap/0.9')
    sitemap = ET.Element('{http://www.sitemaps.org/schemas/sitemap/0.9}urlset')
    for url in urls:
        item = ET.SubElement(sitemap, '{http://www.sitemaps.org/schemas/sitemap/0.9}url')
        ET.SubElement(item, '{http://www.sitemaps.org/schemas/sitemap/0.9}loc').text = url
    result['sitemap.xml'] = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(sitemap, encoding='unicode') + '\n'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='report stale generated files without writing')
    args = parser.parse_args()
    try:
        generated = outputs()
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    stale = []
    for name, content in generated.items():
        path = ROOT / name
        if not path.exists() or path.read_text(encoding='utf-8') != content:
            stale.append(name)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
    if args.check and stale:
        parser.error('Run python tools/render-legal-pages.py; stale outputs: ' + ', '.join(stale))
    print(f'Validated 20 legal translations; {len(generated)} static outputs ' + ('checked.' if args.check else f'rendered ({len(stale)} updated).'))


if __name__ == '__main__':
    main()
