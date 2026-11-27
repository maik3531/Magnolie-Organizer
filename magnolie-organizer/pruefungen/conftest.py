import pytest


collect_ignore = ["last_test.py", "test_flatpak.py"]


def pytest_addoption(parser):
    parser.addoption('--photo-receive-timing', metavar='JSON', default=None,
        help='Write the #753 synthetic automatic WLAN photo receive timing checkpoint.')


@pytest.fixture
def photo_receive_timing(request, monkeypatch):
    output = request.config.getoption('--photo-receive-timing')
    parameters = request.node.callspec.params
    selected = (parameters.get('transport'), parameters.get('direction'),
        parameters.get('kind'), parameters.get('automatic')) == ('wifi', 'phone_to_pc', 'images', True)
    if output is None or not selected:
        yield None
        return
    from photo_receive_timing import PhotoReceiveTiming, install_receive_timing
    recorder = PhotoReceiveTiming()
    install_receive_timing(monkeypatch, recorder)
    try:
        yield recorder
    finally:
        recorder.write(output)  # Only after the measured deadline and test cleanup.
