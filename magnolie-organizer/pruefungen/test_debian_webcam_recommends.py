"""Actual control metadata generation in a private directory; no DEB install."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'werkzeuge'))
from debian_webcam_recommends import webcam_recommends


@pytest.mark.parametrize('camera,photo',[(False,False),(False,True),(True,False),(True,True)])
def test_actual_debian_metadata_recommends_driver_only_for_camera_payload(tmp_path,camera,photo):
    data=tmp_path/'data';data.mkdir()
    (data/'build-config.json').write_text(json.dumps(dict(phoneFeatures=dict(phone_camera=camera,photo_sync=photo))))
    expected='v4l2loopback-dkms' if camera else ''
    assert webcam_recommends(data)==expected
    result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'werkzeuge/debian_webcam_recommends.py'),str(data)],
        capture_output=True,text=True,check=True,timeout=10)
    assert result.stdout.strip()==expected
    control=ROOT/'debian/control';source=control.read_text()
    assert '${magnolie:WebcamRecommends}' in source.split('Recommends:',1)[1].split('Suggests:',1)[0]
    tool=shutil.which('dpkg-gencontrol')
    if tool is None:pytest.skip('Native Debian metadata generator unavailable')
    stage=tmp_path/'stage';stage.mkdir()
    result=subprocess.run([tool,'-pmagnolie-organizer','-c'+str(control),'-l'+str(ROOT/'debian/changelog'),
        '-P'+str(stage),'-T'+str(tmp_path/'substvars'),'-f'+str(tmp_path/'files'),'-Vmisc:Depends=','-Vpython3:Depends=',
        '-Vmagnolie:WebcamRecommends='+expected,'-O'],cwd=tmp_path,capture_output=True,text=True,check=True,timeout=10)
    fields={}
    for line in result.stdout.splitlines():
        if line and not line[0].isspace() and ':' in line:
            name,value=line.split(':',1);fields[name]=value.strip()
    assert 'v4l2loopback' not in fields['Depends']
    assert ('v4l2loopback-dkms' in fields['Recommends']) is camera


def test_missing_composition_recommends_nothing_and_invalid_data_fails_closed(tmp_path):
    assert webcam_recommends(tmp_path)==''
    (tmp_path/'build-config.json').write_text('{"phoneFeatures":{"phone_camera":"yes"}}')
    with pytest.raises(ValueError):webcam_recommends(tmp_path)


def test_debian_rules_generates_substitution_after_payload_composition():
    rules=(ROOT/'debian/rules').read_text()
    assert 'override_dh_gencontrol:' in rules
    assert 'werkzeuge/debian_webcam_recommends.py debian/magnolie-organizer/usr/share/magnolie-organizer' in rules
    assert 'dh_gencontrol -- -Vmagnolie:WebcamRecommends="$$empfiehlt"' in rules
