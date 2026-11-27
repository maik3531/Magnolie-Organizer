# Originale Mac-Patchfolge aus dem API-Prüfzweig wiederherstellen

Dieser Nachweis ist auf den unveränderten Originalstand
`0dfeb1b30a208480eb6901e3d3148a5efeaae5ff` eingefroren. Sein vollständiger
Git-Tree lautet `d731a6bd56acd68e79aab83fbadb19ab94ad6547`. Die ausgeschlossene
Main-Basis ist `d4da48a5eadd0bda22422b924bef4ee3b4324040`.

Die Veröffentlichung erfolgt über die Git Data API, weil der lokale Git-/gh-
Transport keine Zugangsdaten hat. Der GitHub-Connector ist authentifiziert.
Seine Commit-Erzeugung bietet keine originalen Autor-/Committerzeitfelder.
Der tatsächlich erzeugte **API-Quellcommit A** ist
[`8efc6834abd16f18300f3d59a1897c81758b0c34`](https://github.com/maik3531/Magnolie-Organizer/commit/8efc6834abd16f18300f3d59a1897c81758b0c34).
Sein von der API zurückgegebener Tree ist exakt der ursprüngliche
`d731a6bd56acd68e79aab83fbadb19ab94ad6547`; die andere Commit-ID stammt aus
anderen Commitmetadaten und der zusammengefassten Übernahmegeschichte.
Seine Eltern sind `616069f15fed21d8d8d05c8ef795f4ed21bd059c` und
`d4da48a5eadd0bda22422b924bef4ee3b4324040`. Darauf ergänzt der
**API-Dokumentationscommit B** ausschließlich Übergabe-/Rechercheunterlagen
und Lieferartefakte; sein oberster Tree verändert sich dadurch bewusst.
Die SHA und der bestätigte Tree von A stehen im Veröffentlichungsmanifest, die SHA von B
in den anschließend auf diesen Stand gebundenen Issue-Kommentaren.
**Das Bundle erhält die originalen Commitobjekte einschließlich
Metadaten und Merge exakt.** Einzelne `git format-patch`-Dateien erhalten den
Diff und die originale `From`-ID; `git am` garantiert dagegen keine identische
neue Commit-ID.

`manifest.json` nennt für jeden der 24 lokal noch nicht remote erreichbaren
Nichtmergecommits Original-ID, Eltern, Tree, Patchdatei, Bytezahl und SHA-256.
Das Bundle enthält die vollständige Mac-Folge von 32 Commits jenseits der
Main-Basis, einschließlich der bereits veröffentlichten Mac-Vorgänger und eines
Merges. Seine Voraussetzungen sind die Main-Basis sowie deren Vorfahr
`00776ce70e155c7a607ed55a4502d6fcee5a860c`.

## 1. Den veröffentlichten API-Prüfzweig klonen

```sh
git clone --no-single-branch \
  --branch work/macos-issue-fixes-20261126 \
  https://github.com/maik3531/Magnolie-Organizer.git Magnolie-macos-api-review
cd Magnolie-macos-api-review
git fetch origin main
git rev-parse HEAD
```

Die Ausgabe ist die tatsächliche API-Commit-ID. Sie ist keine Bestätigung,
dass der originale Commit `0dfeb1b3…` bereits als GitHub-Commit existiert.
Den tatsächlichen API-Veröffentlichungsbeleg mit Commit A und dessen Tree
zusätzlich lesen: A muss exakt `d731a6bd56acd68e79aab83fbadb19ab94ad6547`
verwenden. Die spätere Ergänzung von Lieferartefakten oder korrigierten
Dokumentationslinks in B darf nicht als identischer vollständiger Originaltree
ausgegeben werden. Produktquellen und beabsichtigte Dokumentationsabweichungen
sind separat zu vergleichen.

## 2. Bundle prüfen und in einen eigenen lokalen Prüfzweig holen

Der folgende Aufruf findet die veröffentlichte Bundledatei anhand ihres
eindeutigen Namens; er setzt keinen bestimmten Ablageordner voraus.

```sh
MACOS_BUNDLE_PATH="$(git ls-files -- '*macos-issue-fixes-0dfeb1b30a208480eb6901e3d3148a5efeaae5ff.bundle')"
test -f "$MACOS_BUNDLE_PATH"
python3 -c 'import hashlib,sys; data=open(sys.argv[1],"rb").read(); assert len(data)==1219360; assert hashlib.sha256(data).hexdigest()=="a775686b950ffd30a6fcbd0c20b063efc777ffc1953980b5f6eae81dc24e7224"; print("Frozen bundle size and SHA-256 verified")' "$MACOS_BUNDLE_PATH"
git bundle verify "$MACOS_BUNDLE_PATH"
git fetch "$MACOS_BUNDLE_PATH" \
  refs/heads/work/macos-issue-fixes-20261126:refs/heads/review/macos-original-0df
test "$(git rev-parse review/macos-original-0df)" = \
  0dfeb1b30a208480eb6901e3d3148a5efeaae5ff
test "$(git rev-parse 'review/macos-original-0df^{tree}')" = \
  d731a6bd56acd68e79aab83fbadb19ab94ad6547
git worktree add ../Magnolie-macos-original review/macos-original-0df
```

Diese Schritte führen keinen Merge nach `main` aus. Im neuen Worktree sind die
originalen Issue-Commits samt Eltern und Original-SHAs verfügbar. Die separate
API-Arbeitskopie bleibt für den Vergleich und die veröffentlichten Unterlagen
erhalten. `git diff --stat review/macos-original-0df HEAD` zeigt Abweichungen
zum API-Prüfzweig; Lieferartefakte und dokumentierte Linkanpassungen von
Produktänderungen unterscheiden.

## 3. Prüfen und erst danach gezielt übernehmen

Im Originalworktree die vorhandenen Issue-Verträge, `ARBEITSSTAND.md`, den
Mac-Gesamtbericht sowie `CLOUD-MAC-TESTING.md` lesen. Vor einer Einzelübernahme
die tatsächliche Zielbasis und bereits enthaltene Commits prüfen. Die im
Manifest aufgeführte Reihenfolge respektiert die Eltern; Mergeobjekte werden
nur über das Bundle exakt erhalten. Die 24 Patchdateien deshalb nicht ohne
Basis-/Abhängigkeitsprüfung auf `main` anwenden.

Der große Kontakt-/Katalogpatch `c9c3ebeb…` wird als `.patch.gz` veröffentlicht.
Der Gzip-Header hat mtime 0 und keinen gespeicherten Dateinamen. Die komprimierte
Datei hat **2.348.188 Bytes**, SHA-256
`ddc2902272476e8bb90255736e6a6f8f19d4098eddb661ec36c77f4489fb9b25`.
Nach Dekompression müssen es **7.696.563 Bytes** und SHA-256
`3bf587a48f77564ee1bfc999e1902c63e27e5943bc72fa691e014ef2fa4084e6`
sein. Erst danach den ursprünglichen Patch mit `git apply --check` an der
passenden Basis prüfen. Die rohe `.patch` bleibt zusätzlich lokal erhalten;
der veröffentlichte `publicationPath` und `encoding` im Manifest sind maßgeblich.

Python-/JSDOM-Prüfungen, vorbereitete Swift-Tests und tatsächlich bestandene
native Mac-VM-Prüfungen bleiben unterschiedliche Belege. Diese Auslieferung
erteilt keine neue Main-Merge-, Konto-/Geräte- oder Paketfreigabe.

## Verifikationsbeleg

`bundle-verify.txt` hält die erfolgreiche Git-Prüfung fest.
`restore-verification.json` dokumentiert die tatsächliche Wiederherstellung
in einem separaten Bare-Repository: zuerst ausschließlich Main-Voraussetzungen
holen, Bundle prüfen und fetchen, Originalcommit und -tree vergleichen sowie
`git fsck --strict --no-reflogs --no-dangling` ausführen. Die Prüfung verwendet
keinen neuen nativen Mac-Lauf. `SHA256SUMS` bindet die veröffentlichten Dateien;
die nur lokal behaltene große Rohpatchdatei ist über ihren separaten
unkomprimierten Manifesthash gebunden.
