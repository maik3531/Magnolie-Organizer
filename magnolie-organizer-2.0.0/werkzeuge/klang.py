#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Erzeugt den Erinnerungsklang des Magnolie Organizers.

Zwei weiche Glockentöne, die absteigend erklingen – kurz, freundlich und
einprägsam genug, dass man schon beim Hören weiß: da steht ein Termin an.
Der Klang wird beim Bau des Pakets berechnet, damit keine fremde
Klangdatei mitgeliefert werden muss.
"""

import array
import math
import os
import sys
import wave

ABTASTRATE = 44100
LAENGE = 1.9            # Sekunden
LAUTSTAERKE = 0.62


def glocke(zeit, grundton, anschlag, dauer):
    """Ein glockenartiger Ton: Grundton mit leicht unreinen Obertönen,
    die schneller verklingen als der Grundton."""
    seit = zeit - anschlag
    if seit < 0 or seit > dauer:
        return 0.0

    # Sanfter Anschlag, damit es nicht knackt
    anstieg = min(1.0, seit / 0.006)
    huelle = anstieg * math.exp(-3.1 * seit)

    # Obertöne einer Glocke liegen nicht genau auf dem Vielfachen
    klang = (
        1.00 * math.sin(2 * math.pi * grundton * seit)
        + 0.42 * math.sin(2 * math.pi * grundton * 2.01 * seit) * math.exp(-1.9 * seit)
        + 0.18 * math.sin(2 * math.pi * grundton * 3.02 * seit) * math.exp(-3.4 * seit)
        + 0.09 * math.sin(2 * math.pi * grundton * 4.07 * seit) * math.exp(-5.2 * seit)
    )
    return huelle * klang


def erzeuge():
    werte = array.array("h")
    gesamt = int(ABTASTRATE * LAENGE)
    for schritt in range(gesamt):
        zeit = schritt / ABTASTRATE
        wert = (
            0.62 * glocke(zeit, 987.77, 0.00, LAENGE)        # H5
            + 0.70 * glocke(zeit, 659.25, 0.30, LAENGE)      # E5
            + 0.22 * glocke(zeit, 329.63, 0.30, LAENGE)      # E4, gibt Wärme
        )
        # Am Ende sauber ausblenden
        rest = LAENGE - zeit
        if rest < 0.12:
            wert *= max(0.0, rest / 0.12)
        wert = max(-1.0, min(1.0, wert * LAUTSTAERKE))
        werte.append(int(wert * 32767))
    return werte


def schreibe(pfad):
    ordner = os.path.dirname(pfad)
    if ordner:
        os.makedirs(ordner, exist_ok=True)
    werte = erzeuge()
    if sys.byteorder == "big":
        werte.byteswap()
    with wave.open(pfad, "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(ABTASTRATE)
        datei.writeframes(werte.tobytes())
    return pfad


if __name__ == "__main__":
    ziel = sys.argv[1] if len(sys.argv) > 1 else "klang/erinnerung.wav"
    print("Klang geschrieben: " + schreibe(ziel))
