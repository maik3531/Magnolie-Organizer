from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT.parent / "magnolie-handbuch-stamm"
PROFILES = ("fedora", "opensuse", "mageia", "openmandriva", "pclinuxos", "rosa")


def read(path):
    return path.read_text(encoding="utf-8")


def test_builders_require_and_pin_explicit_profiles():
    for root in (ROOT, HANDBOOK):
        builder = read(root / "werkzeuge/rpm_bauen.sh")
        spec = read(root / "rpm" / ("magnolie-organizer.spec" if root == ROOT else "magnolie-handbuch.spec"))
        assert "--distro ist erforderlich" in builder
        assert 'TOPDIR="$TOPBASE/$DISTRO"' in builder
        assert 'sed "s/@MAGNOLIE_DISTRO@/$DISTRO/g"' in builder
        assert "rpmbuild --target" not in builder
        assert "%global magnolie_distro @MAGNOLIE_DISTRO@" in spec
        assert "magnolie-rpm-profile(%{magnolie_distro})" in spec
        for profile in PROFILES:
            assert profile in builder


def test_all_profiles_expand_to_explicit_dependency_sets():
    for root in (ROOT, HANDBOOK):
        builder = read(root / "werkzeuge/rpm_bauen.sh")
        spec_name = "magnolie-organizer.spec" if root == ROOT else "magnolie-handbuch.spec"
        spec = read(root / "rpm" / spec_name)
        assert "PCLinuxOS-Profil nicht gebaut" not in builder
        assert "dpkg-parsechangelog" not in builder
        assert "Requires:       %{magnolie_deps}" in spec
        assert "BuildRequires:  %{magnolie_build_deps}" in spec
        assert spec.count("%global magnolie_build_deps python3-pytest") == 5
        assert spec.count("%global magnolie_build_deps python-pytest") == 1
        assert "/usr/bin/python3" in spec and "%{python3}" not in spec
        for profile in PROFILES:
            expanded = spec.replace("@MAGNOLIE_DISTRO@", profile)
            assert f"%global magnolie_distro {profile}" in expanded
            assert "@MAGNOLIE_DISTRO@" not in expanded
        assert '"%{magnolie_distro}" == "pclinuxos"' in spec
        if root == ROOT:
            for required in ("python3-pyOpenSSL", "typelib-1_0-WebKit2-4_1",
                             "python3-openssl", "python-gobject3", "python3-OpenSSL"):
                assert required in spec


def test_fedora_remains_the_release_validated_wrapper():
    wrapper = read(ROOT / "werkzeuge/rpm_fedora_bauen.sh")
    release_builder = read(ROOT / "werkzeuge/release_bauen.sh")
    assert wrapper.count("--distro fedora") == 2
    assert "libnotify nodejs" in wrapper
    assert "rpm-build webkit2gtk4.1 xdg-utils" in wrapper
    assert "install fakeroot" in wrapper
    assert wrapper.count("/usr/bin/fakeroot /usr/bin/dnf") == 4
    assert wrapper.count("chmod -R u+rwX") == 2
    assert '--bind "$TOPDIR" "$TOPDIR"' in wrapper
    assert '--bind "$HANDBUCH_TOPDIR" "$HANDBUCH_TOPDIR"' in wrapper
    assert '--bind "$AKONADI_TOPDIR" "$AKONADI_TOPDIR"' in wrapper
    assert 'magnolie-organizer-akonadi-"$AKONADI_VERSION"-*.rpm' in wrapper
    assert 'AKONADI_ANTWORT="$AKONADI_TOPDIR/akonadi-response.json"' in wrapper
    assert "rpm -q magnolie-handbuch" in wrapper
    assert "test ! -e /usr/lib/magnolie-handbuch/magnolie_crash.py" in wrapper
    assert 'mkdir -p "$ARBEIT" "$TOPDIR" "$HANDBUCH_TOPDIR" "$AKONADI_TOPDIR"' in wrapper
    assert "akonadi-rpm/RPMS/*/magnolie-organizer-akonadi-" in release_builder
    assert "akonadi-rpm/SRPMS/magnolie-organizer-akonadi-" in release_builder
    for profile in PROFILES[1:]:
        assert f"--distro {profile}" not in wrapper
    assert "/fedora/RPMS/noarch/magnolie-organizer-" in wrapper
    assert "/fedora/RPMS/noarch/magnolie-handbuch-" in wrapper
    assert "rpm/fedora/RPMS/noarch/magnolie-organizer-" in release_builder
    assert "handbuch-rpm/fedora/RPMS/noarch/magnolie-handbuch-" in release_builder
    assert "bau/rpm/fedora/SRPMS" in release_builder
