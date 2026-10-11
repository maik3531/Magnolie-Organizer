"""Explicit vCard profile evidence. Never infer messenger membership from TEL/FN."""
import re
from urllib.parse import urlsplit, urlunsplit, parse_qs

SERVICES = {name: name for name in ("whatsapp", "signal", "telegram", "threema", "facebook", "instagram", "teams",
    "snapchat", "tiktok", "youtube", "mastodon", "x", "linkedin", "reddit")}
SERVICES.update(twitter="x", **{"whatsapp business": "whatsapp"})


def profile_url(raw, declared=None):
    try:
        uri = urlsplit(raw)
        if uri.scheme.lower() not in {"http", "https"} or uri.username is not None or uri.port not in {None, 80, 443}:
            return None
        host = (uri.hostname or "").lower().removeprefix("www.")
        parts = [part for part in uri.path.split("/") if part]
        path = "/".join(parts)
        query = fragment = ""
        single = lambda pattern, excluded=(): len(parts) == 1 and re.fullmatch(pattern, parts[0]) and parts[0].lower() not in excluded
        if host == "instagram.com" and single(r"[A-Za-z0-9._]{1,30}", {"accounts", "explore", "direct", "stories", "reels", "reel", "p", "about"}): service = "instagram"
        elif host in {"facebook.com", "m.facebook.com"} and path == "profile.php":
            values = parse_qs(uri.query).get("id", [])
            if len(values) != 1 or not re.fullmatch(r"[0-9]+", values[0]): return None
            service, query = "facebook", "id=" + values[0]
        elif host in {"facebook.com", "m.facebook.com"} and (single(r"[A-Za-z0-9.]+", {"login", "help", "pages", "groups", "watch", "share", "sharer", "privacy", "settings", "marketplace", "events", "photo", "photos", "reel"}) or len(parts) == 3 and parts[0] == "people" and parts[2].isdigit()): service = "facebook"
        elif host in {"twitter.com", "x.com"} and single(r"[A-Za-z0-9_]{1,15}", {"home", "explore", "search", "settings", "intent", "i", "compose", "messages", "notifications"}): service = "x"
        elif host in {"t.me", "telegram.me"} and single(r"[A-Za-z][A-Za-z0-9_]{4,31}", {"share", "joinchat", "addstickers", "proxy", "login"}): service = "telegram"
        elif host == "wa.me" and single(r"[0-9]{5,20}"): service = "whatsapp"
        elif host == "threema.id" and single(r"[A-Za-z0-9]{8}"): service = "threema"
        elif host == "signal.me" and re.fullmatch(r"p/\+[0-9]{5,20}|eu/[A-Za-z0-9_-]+", uri.fragment): service, fragment = "signal", uri.fragment
        elif host == "linkedin.com" and len(parts) == 2 and parts[0] in {"in", "company"}: service = "linkedin"
        elif host == "youtube.com" and (single(r"@[A-Za-z0-9._-]+") or len(parts) == 2 and parts[0] == "channel"): service = "youtube"
        elif host == "tiktok.com" and single(r"@[A-Za-z0-9._]+"): service = "tiktok"
        elif host == "snapchat.com" and len(parts) == 2 and parts[0] == "add": service = "snapchat"
        elif host == "reddit.com" and len(parts) == 2 and parts[0] in {"u", "user"}: service = "reddit"
        elif declared == "mastodon" and (single(r"@[A-Za-z0-9_.-]+") or len(parts) == 2 and parts[0] == "users"): service = "mastodon"
        else: return None
        if declared and service != declared: return None
        return {"dienst": service, "wert": urlunsplit(("https", host, uri.path, query, fragment))}
    except (ValueError, TypeError):
        return None


def from_vcard(name, value, parameters):
    if name not in {"URL", "IMPP", "X-SOCIALPROFILE", "X-SOCIAL-PROFILE"} or not isinstance(value, str): return None
    value = value.strip()
    if not value or len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value): return None
    hints = [parameters.get("X-SERVICE-TYPE", ""), *parameters.get("TYPE", "").split(",")]
    declared = next((SERVICES[hint.strip(' "').lower()] for hint in hints if hint.strip(' "').lower() in SERVICES), None)
    if re.match(r"https?://", value, re.I): return profile_url(value, declared)
    if name == "URL": return None
    scheme, separator, identifier = value.partition(":")
    explicit = SERVICES.get(scheme.lower()) if separator else None
    if explicit:
        if declared and declared != explicit: return None
        declared, value = explicit, identifier.removeprefix("//")
    elif separator:
        value = parameters.get("X-USER", "").strip(' "')
    if not declared or not value or value in {"/", "//"}: return None
    return {"dienst": declared, "wert": value}
