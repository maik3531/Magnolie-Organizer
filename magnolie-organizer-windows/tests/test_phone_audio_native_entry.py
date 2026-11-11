"""Source gates for the explicit native prerequisite utility, never a GUI test."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_audio_setup_is_explicit_and_reserved_before_normal_startup():
    program = (ROOT / "Program.cs").read_text(encoding="utf-8")
    entry = (ROOT / "PhoneCameraAudioSetupEntry.cs").read_text(encoding="utf-8")
    form = (ROOT / "PhoneCameraAudioSetupForm.cs").read_text(encoding="utf-8")
    assert '"--prepare-phone-webcam-audio"' in program
    assert program.index('"--prepare-phone-webcam-audio"') < program.index('"--mcp-stdio"')
    assert 'if (!audioSetupHandled) Environment.ExitCode = 50;' in program
    assert 'if (args.Length != 1) { Environment.ExitCode = 87; return; }' in entry
    assert 'using var form = new PhoneCameraAudioSetupForm();' in entry
    assert 'Application.Run(form);' in entry
    assert 'AskAndPrepareAsync(this, RequireOriginalWindow, lifetime.Token)' in form
    assert 'RunConfirmedAsync' not in form
    assert 'DownloadAsync' not in form
    assert 'PhoneCameraSession' not in form
    assert 'BindWebcamControl' not in form


def test_native_window_cancellation_retains_original_action_and_no_readiness():
    form = (ROOT / "PhoneCameraAudioSetupForm.cs").read_text(encoding="utf-8")
    entry = (ROOT / "PhoneCameraAudioSetupEntry.cs").read_text(encoding="utf-8")
    ui = (ROOT / "PhoneCameraAudioSetupUi.cs").read_text(encoding="utf-8")
    assert 'Handle != originalHandle' in form
    assert 'lifetime.Token.ThrowIfCancellationRequested();' in form
    assert 'args.Cancel = running;' in form
    assert 'running = false; finished = true;' in form
    assert 'PhoneCameraAudioSetupState.RebootRequired => 3010' in entry
    assert 'PhoneCameraAudioSetupState.UnknownPending => 1618' in entry
    assert 'PhoneCameraAudioSetupState.PreparedOnly =>' not in entry
    assert 'MessageBoxDefaultButton.Button2' in ui
    assert ui.index('!= DialogResult.Yes') < ui.index('PhoneCameraAudioPackage.DownloadAsync')
    assert ui.index('PhoneCameraAudioPackage.DownloadAsync') < ui.index('PhoneCameraAudioSetup.RunConfirmedAsync')
