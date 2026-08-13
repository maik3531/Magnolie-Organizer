#!/usr/bin/python3
"""Schaltet den echten benutzereigenen Erinnerungsdienst ein oder aus."""

import importlib.machinery
import importlib.util
import sys


lader = importlib.machinery.SourceFileLoader(
    "magnolie_installiert", "/usr/bin/magnolie-organizer")
spec = importlib.util.spec_from_loader("magnolie_installiert", lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)

ergebnis = m.erinnerungsdienst_einrichten(sys.argv[1] == "enable")
if not ergebnis.get("ok"):
    raise SystemExit(ergebnis.get("fehler") or "Erinnerungsdienst fehlgeschlagen")
