import ast
import copy
import pathlib
import re


QUELLE = pathlib.Path(__file__).parents[1] / "bin" / "magnolie-organizer"


def _funktion(name):
    baum = ast.parse(QUELLE.read_text(encoding="utf-8"))
    knoten = next(k for k in baum.body if isinstance(k, ast.FunctionDef) and k.name == name)
    modul = ast.Module(body=[knoten], type_ignores=[])
    namespace = {"os": __import__("os"), "_": lambda text: text}
    exec(compile(modul, str(QUELLE), "exec"), namespace)
    return namespace[name], namespace


def test_linux_lokalimport_waehlt_evolution_und_thunderbird_getrennt(tmp_path):
    scannen, ns = _funktion("lokal_scannen")
    aufrufe = []
    ns.update({
        "_evolution_wurzeln": lambda *_: aufrufe.append("evolution") or [],
        "_thunderbird_profile": lambda *_: aufrufe.append("thunderbird") or [],
        "_lokale_kalender_dubletten_bereinigen": lambda *_: None,
        "_zaehl_satz": lambda *_: "",
    })

    assert scannen(tmp_path, True, "evolution")["quelle"] == "evolution"
    assert aufrufe == ["evolution"]
    aufrufe.clear()
    assert scannen(tmp_path, True, "thunderbird")["quelle"] == "thunderbird"
    assert aufrufe == ["thunderbird"]


def test_linux_lokalimport_verwirft_unbekannte_quelle(tmp_path):
    scannen, _ = _funktion("lokal_scannen")
    try:
        scannen(tmp_path, True, "iphone")
    except ValueError:
        pass
    else:
        raise AssertionError("Eine nicht implementierte Quelle wurde vorgetäuscht")


def test_android_importvertrag_begrenzt_karten_und_verbietet_loeschfelder():
    baum = ast.parse(QUELLE.read_text(encoding="utf-8"))
    namen = {"baum_kontakt_sync_pruefen", "baum_kontakt_import_pruefen"}
    knoten = [k for k in baum.body if isinstance(k, ast.FunctionDef) and k.name in namen]
    ns = {
        "_": lambda text: text, "re": re,
        "BAUM_KONTAKT_TEXT_MAX": 2048, "BAUM_KONTAKT_NOTIZ_MAX": 20000,
        "BAUM_KONTAKT_FOTO_MAX": 2800000, "BAUM_KONTAKT_LISTE_MAX": 100,
        "_maschinen_datum": lambda _wert: True,
    }
    exec(compile(ast.Module(body=knoten, type_ignores=[]), str(QUELLE), "exec"), ns)
    pruefen = ns["baum_kontakt_import_pruefen"]
    kontakt = {"vorname": "Ada", "nachname": "", "firma": "", "notiz": "",
               "geburtstag": "", "telefone": [], "emailEintraege": [], "anschriften": []}
    karte = {"art": "kontakt_import_karte", "fassung": 1, "importId": "import-1",
             "bindung": "urn:magnolie:import:android:" + "a" * 64,
             "herkuenfte": [{"kontoTyp": "type", "kontoName": "Privat", "dataSet": ""}],
             "kontakt": kontakt}
    assert pruefen("kontakt_import_karte", karte) is karte
    manipuliert = copy.deepcopy(karte)
    manipuliert["loeschen"] = True
    try:
        pruefen("kontakt_import_karte", manipuliert)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Der begrenzte Importvertrag akzeptierte eine Löschanweisung")
