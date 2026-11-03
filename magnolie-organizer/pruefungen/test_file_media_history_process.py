"""Fresh-process historical inspection with the actual existing native key."""
import json
from pathlib import Path
import subprocess
import sys

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_media_history import admit,unpublished


def test_fresh_process_reads_native_history_without_live_binding_sealing_or_republication(receiving):
    connection=receiving[3];receiver=admit(receiving)
    index=receiver._index;history=index.media_history;job=receiver.job
    parent=index._parent;receiver.close()
    script=r'''
import json,sys
value=json.loads(sys.stdin.read())
sys.path.insert(0,value['bin'])
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import FileManifest,NativeTransferBinding
from magnolie_transfer_job_index import ProtectedTransferJobIndex
def no_seal(*args):raise AssertionError('historical inspection must not seal')
with ExistingFileTransferProtection(value['native_directory']) as protection:
    with ProtectedTransferJobIndex(value['parent'],FileManifest.parse(value['manifest']),NativeTransferBinding(**value['binding']),
            lambda:None,no_seal,protection.unseal,owner=value['owner']) as index:
        history=index.media_history
        print(json.dumps(dict(history=history.wire(),write=history.grants_write_authority,saved=history.is_saved_receipt)))
'''
    process=subprocess.run([sys.executable,'-c',script],input=json.dumps(dict(
        bin=str(Path(__file__).resolve().parents[1]/'bin'),native_directory=connection._authority.binding.native_directory,
        parent=str(parent),manifest=job.accepted.manifest.wire(),binding=vars(job.accepted.binding),owner=job.owner)),
        text=True,capture_output=True,check=True,timeout=20)
    assert json.loads(process.stdout)==dict(history=history.wire(),write=False,saved=False)
    unpublished(receiving,receiver)
