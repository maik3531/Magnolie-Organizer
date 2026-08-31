#!/bin/sh
# Bringt alle Handbuchbilder auf ein einheitliches Format: WebP.
#
#   Bildschirmfotos (PNG)  -> WebP verlustfrei   (Text bleibt scharf, ~20 % kleiner)
#   Fotos (JPG)            -> WebP verlustbehaftet q=85 (deutlich kleiner)
#
# Persönliche Bilder liegen nur als MGA-Container vor und werden nicht erfasst.
#
# Aufruf aus dem Wurzelverzeichnis des Handbuch-Quellpakets:
#
#     werkzeuge/bilder_vereinheitlichen.sh          # nur berichten
#     werkzeuge/bilder_vereinheitlichen.sh --schreiben
#
# Voraussetzung: cwebp aus webp (Debian/Ubuntu: apt install webp).

set -eu

WEB="web"
SCHREIBEN=0
[ "${1:-}" = "--schreiben" ] && SCHREIBEN=1

command -v cwebp >/dev/null 2>&1 || {
  echo "cwebp fehlt. Unter Debian/Ubuntu: sudo apt install webp" >&2
  exit 1
}

GESCHUETZT=""

geschuetzt() {
  for g in $GESCHUETZT; do [ "$1" = "$g" ] && return 0; done
  return 1
}

alt_gesamt=0
neu_gesamt=0

for pfad in "$WEB"/*.png "$WEB"/*.jpg; do
  [ -e "$pfad" ] || continue
  name=$(basename "$pfad")
  if geschuetzt "$name"; then
    echo "  uebersprungen (geschuetzt): $name"
    continue
  fi
  ziel="$WEB/${name%.*}.webp"
  case "$name" in
    *.png) cwebp -quiet -lossless -exact "$pfad" -o "$ziel" ;;
    *.jpg) cwebp -quiet -q 85 "$pfad" -o "$ziel" ;;
  esac
  alt=$(wc -c < "$pfad")
  neu=$(wc -c < "$ziel")
  alt_gesamt=$((alt_gesamt + alt))
  neu_gesamt=$((neu_gesamt + neu))
  printf '  %-30s %7d -> %7d Byte  (%d %%)\n' \
    "$name" "$alt" "$neu" "$((neu * 100 / alt))"
  if [ "$SCHREIBEN" = "1" ]; then
    rm -f "$pfad"
    # Verweise im Buchtext und in den Pruefungen mitziehen
    sed -i "s/${name}/${name%.*}.webp/g" "$WEB/inhalt.js"
  else
    rm -f "$ziel"
  fi
done

printf '\n  Summe %d -> %d Byte (%d %%)\n' \
  "$alt_gesamt" "$neu_gesamt" "$((neu_gesamt * 100 / alt_gesamt))"

if [ "$SCHREIBEN" = "1" ]; then
  echo
  echo "  Geschrieben. Jetzt die Pruefsummen in beiden Pruefstaenden erneuern:"
  echo
  for pfad in "$WEB"/*.webp "$WEB"/*.mga; do
    [ -e "$pfad" ] || continue
    printf '    "%s": "%s",\n' "$(basename "$pfad")" \
      "$(sha256sum "$pfad" | cut -d' ' -f1)"
  done
  echo
  echo "  Ziele: pruefungen/handbuch_test.js und tests/handbook-protection.js"
  echo "  Dazu in handbook-protection.js die Zusicherung auf 01.jpg/02.jpg/03.jpg"
  echo "  auf die neuen Dateinamen umstellen."
else
  echo
  echo "  Nur berichtet. Mit --schreiben wird umgewandelt."
fi
