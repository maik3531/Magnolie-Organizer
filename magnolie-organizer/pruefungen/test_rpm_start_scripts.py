"""#686: exercise the real RPM web install command, without rpmbuild or a VM."""
import importlib.util
from pathlib import Path
import shlex
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "rpm/magnolie-organizer.spec"
spec = importlib.util.spec_from_file_location(
    "rpm_web_startskripte_pruefen", ROOT / "werkzeuge/web_startskripte_pruefen.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def web_install_command():
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    matches = []
    for index, line in enumerate(lines):
        if line.startswith("install -pm 0644 web/index.html "):
            command = line
            while command.endswith("\\"):
                index += 1
                command = command[:-1] + lines[index].lstrip()
            matches.append(shlex.split(command))
    assert len(matches) == 1, "The actual RPM entry-point install command must be unambiguous"
    command = matches[0]
    assert command[:3] == ["install", "-pm", "0644"]
    assert command[-1] == "%{buildroot}%{_datadir}/%{name}/web/"
    for source in command[3:-1]:
        path = ROOT / source
        assert source.startswith("web/") and path.resolve().is_relative_to(ROOT / "web")
        assert path.is_file()
    return command


def test_real_rpm_web_install_contains_all_entry_scripts(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    command = web_install_command()
    subprocess.run(command[:-1] + [str(web)], cwd=ROOT, check=True, timeout=10)
    assert checker.pruefen(web) > 0


def test_rpm_checks_actual_buildroot_before_packaging():
    text = SPEC.read_text(encoding="utf-8")
    install = text.split("\n%install\n", 1)[1].split("\n%files", 1)[0]
    assert "/usr/bin/python3 -I -B werkzeuge/web_startskripte_pruefen.py %{buildroot}%{_datadir}/%{name}/web" in install


def test_rpm_check_runs_resource_and_payload_regressions():
    check = SPEC.read_text(encoding="utf-8").split("\n%check\n", 1)[1].split("\n%install\n", 1)[0]
    assert "pruefungen/test_organizer_resource_inventory.py" in check
    assert "pruefungen/test_rpm_start_scripts.py" in check
