import importlib.machinery
import importlib.util
import sys


def quellmodul_laden(name, pfad):
    loader = importlib.machinery.SourceFileLoader(name, str(pfad))
    spec = importlib.util.spec_from_loader(name, loader)
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    try:
        loader.exec_module(modul)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return modul
