import importlib.util
from pathlib import Path


PFAD = Path(__file__).parents[1] / "werkzeuge" / "elf_glibc_pruefen.py"
SPEC = importlib.util.spec_from_file_location("elf_glibc_pruefen", PFAD)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def test_glibc_fassungen_werden_numerisch_gelesen():
    text = "Name: GLIBC_2.4  Name: GLIBC_2.35  Name: GLIBC_PRIVATE"
    assert m.verlangte_fassungen(text) == {(2, 4), (2, 35)}


def test_zu_neue_elf_datei_wird_abgewiesen(tmp_path, monkeypatch):
    elf = tmp_path / "programm"
    elf.write_bytes(b"\x7fELFprobe")

    class Ergebnis:
        stdout = "Name: GLIBC_2.38"

    monkeypatch.setattr(m.subprocess, "run", lambda *args, **kwargs: Ergebnis())
    try:
        m.pruefen(tmp_path, "2.35")
    except SystemExit as fehler:
        assert "GLIBC_2.35" in str(fehler)
    else:
        raise AssertionError("Eine zu neue glibc-Anforderung wurde akzeptiert")
