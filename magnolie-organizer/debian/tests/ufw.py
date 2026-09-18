#!/usr/bin/python3
"""Ruft die produktive UFW-Einrichtung aus dem installierten Programm auf."""

import importlib.machinery
import importlib.util


lader = importlib.machinery.SourceFileLoader(
    "magnolie_installiert", "/usr/bin/magnolie-organizer")
spec = importlib.util.spec_from_loader("magnolie_installiert", lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)

ok, fehler = m.baum_firewall_einrichten()
if not ok:
    raise SystemExit(fehler or "UFW-Einrichtung fehlgeschlagen")
