"""Pure resource-policy tests; never starts a guest or changes actual affinity."""
import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('capacity',Path(__file__).resolve().parents[1]/'tools/host-capacity.py')
capacity=importlib.util.module_from_spec(spec)
spec.loader.exec_module(capacity)


class FakeTasks:
    def __init__(self):
        self.expected = dict(pid=800, uid=1000, start='100', boot='fake-boot')
        self.current = dict(self.expected)
        self.tasks = {801:dict(tid=801, tgid=800, uid=1000, start='101')}
        self.masks = {801:{0,1,2,3}}
        self.writes = []
        self.reads = []
        self.on_get = lambda tid: None
        self.on_set = lambda tid: None
        self.apply_set = True

    def parent(self, pid): return dict(self.current) if self.current is not None else None
    def tids(self, pid): return sorted(self.tasks)
    def task(self, pid, tid):
        if tid not in self.tasks: raise FileNotFoundError(tid)
        return dict(self.tasks[tid])
    def get(self, tid):
        self.reads.append(tid)
        if tid not in self.tasks: raise ProcessLookupError(tid)
        result=set(self.masks[tid]); self.on_get(tid); return result
    def set(self, tid, mask):
        self.writes.append((tid,set(mask)))
        if self.apply_set: self.masks[tid]=set(mask)
        self.on_set(tid)


class CapacityTest(unittest.TestCase):
    def test_newer_gate_requires_current_provider_not_installed_alternative(self):
        capacity.require_newer_webview('Current WebView package (name, version): (com.google.android.webview, 131.0.6778.200)')
        for text in ('', 'Current WebView package is null',
                     'Current WebView package (name, version): (com.google.android.webview, 113.0.5672.136)\nValid package 140.0.0.1',
                     'Current WebView package (name, version): (com.google.android.webview, 131.bad)'):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                capacity.require_newer_webview(text)

    def test_package_binding_rejects_paths_and_non_hash_values(self):
        valid={'appSourceHash':'a'*64,'apks':{name:'b'*64 for name in capacity.APK_NAMES}}
        capacity.validate_package_binding(valid)
        with self.assertRaises(RuntimeError):
            capacity.validate_package_binding({'appSourceHash':'a'*64,'apks':{'../private.json':'b'*64}})
        with self.assertRaises(RuntimeError):
            capacity.validate_package_binding({'appSourceHash':'a'*64,'apks':{'/tmp/private.apk':'b'*64}})
        with self.assertRaises(RuntimeError):
            capacity.validate_package_binding({**valid,'appSourceHash':'not-a-hash'})

    def test_four_distinct_cores_avoid_smt_siblings(self):
        self.assertEqual(capacity.select_cpus(4,range(8),lambda cpu:(0,cpu//2)),[0,2,4,6])

    def test_parent_allowed_mask_is_respected(self):
        self.assertEqual(capacity.select_cpus(4,[1,3,5,7],lambda cpu:(0,cpu//2)),[1,3,5,7])
        with self.assertRaises(RuntimeError):
            capacity.select_cpus(4,[0,1,2,3],lambda cpu:(0,cpu//2))

    def test_two_cpu_profile_stays_two(self):
        self.assertEqual(capacity.select_cpus(2,range(20),lambda cpu:(0,cpu//2)),[0,2])

    def test_no_unverified_or_more_than_four_core_profile(self):
        for count in (0,1,3,5,8):
            with self.assertRaises(ValueError): capacity.select_cpus(count,range(20),lambda cpu:(0,cpu))
        def absent(cpu): raise FileNotFoundError('topology unavailable')
        with self.assertRaises(FileNotFoundError): capacity.select_cpus(4,range(8),absent)

    def test_quota_memory_swap_and_affinity_must_match(self):
        capacity.validate_limits(4,str(6*1024**3),'0','400000','100000',[0,2,4,6])
        capacity.validate_limits(2,str(6*1024**3),'0','200000','100000',[0,2])
        invalid=[(4,str(6*1024**3),'0','200000','100000',[0,2,4,6]),
                 (2,str(6*1024**3),'0','400000','100000',[0,2]),
                 (4,'max','0','400000','100000',[0,2,4,6]),
                 (4,str(7*1024**3),'0','400000','100000',[0,2,4,6]),
                 (4,str(6*1024**3),'1','400000','100000',[0,2,4,6]),
                 (4,str(6*1024**3),'0','max','100000',[0,2,4,6]),
                 (4,str(6*1024**3),'0','400000','100000',[0,2])]
        for args in invalid:
            with self.subTest(args=args),self.assertRaises(RuntimeError): capacity.validate_limits(*args)

    def test_owned_task_repin_records_original_and_actual_readback(self):
        ops=FakeTasks(); records=[]
        result=capacity.audit_process(ops.expected,[0,2,4,6],ops,records.append,repair=True)
        self.assertEqual(ops.writes,[(801,{0,2,4,6})])
        self.assertEqual(len(ops.reads),2)
        self.assertEqual(result[0]['original'],[0,1,2,3])
        self.assertEqual(result[0]['actual'],[0,2,4,6])
        self.assertTrue(result[0]['repaired'])
        self.assertEqual(records[0]['taskIdentity']['tgid'],800)

    def test_parent_identity_mismatch_never_writes(self):
        for key, value in [('pid',900),('uid',2000),('start','recycled'),('boot','different-boot')]:
            ops=FakeTasks(); ops.current[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                capacity.audit_process(ops.expected,[0,2,4,6],ops,lambda row:None,repair=True)
            self.assertEqual(ops.writes,[])

    def test_wrong_tgid_refuses_before_touching_task(self):
        ops=FakeTasks(); ops.tasks[801]['tgid']=999
        with self.assertRaises(RuntimeError):
            capacity.audit_process(ops.expected,[0,2,4,6],ops,lambda row:None,repair=True)
        self.assertEqual(ops.writes,[]); self.assertEqual(ops.reads,[])

    def test_reused_tid_after_read_refuses_write(self):
        ops=FakeTasks()
        ops.on_get=lambda tid:ops.tasks[tid].update(start='recycled')
        with self.assertRaises(RuntimeError):
            capacity.audit_process(ops.expected,[0,2,4,6],ops,lambda row:None,repair=True)
        self.assertEqual(ops.writes,[])

    def test_task_exit_is_ignored_only_while_parent_identity_survives(self):
        ops=FakeTasks(); records=[]
        ops.on_get=lambda tid:ops.tasks.pop(tid)
        self.assertEqual(capacity.audit_process(ops.expected,[0,2,4,6],ops,records.append,repair=True),[])
        self.assertEqual(records[-1]['phase'],'task-exited'); self.assertEqual(ops.writes,[])
        ops=FakeTasks()
        def exit_parent(tid): ops.tasks.pop(tid); ops.current=None
        ops.on_get=exit_parent
        with self.assertRaises(RuntimeError):
            capacity.audit_process(ops.expected,[0,2,4,6],ops,lambda row:None,repair=True)
        self.assertEqual(ops.writes,[])

    def test_bad_actual_mask_after_set_raises(self):
        ops=FakeTasks(); ops.apply_set=False; records=[]
        with self.assertRaises(RuntimeError):
            capacity.audit_process(ops.expected,[0,2,4,6],ops,records.append,repair=True)
        self.assertEqual(len(ops.writes),1); self.assertEqual(len(ops.reads),2)
        self.assertEqual(records[-1]['actual'],[0,1,2,3]); self.assertFalse(records[-1]['repaired'])

    def test_identity_is_checked_after_set(self):
        ops=FakeTasks(); ops.on_set=lambda tid:ops.current.update(start='recycled')
        with self.assertRaises(RuntimeError):
            capacity.audit_process(ops.expected,[0,2,4,6],ops,lambda row:None,repair=True)
        self.assertEqual(len(ops.writes),1); self.assertEqual(len(ops.reads),1)

    def test_task_exit_after_set_is_not_counted_as_verified_correction(self):
        ops=FakeTasks(); records=[]
        ops.on_set=lambda tid:ops.tasks.pop(tid)
        self.assertEqual(capacity.audit_process(ops.expected,[0,2,4,6],ops,records.append,repair=True),[])
        self.assertEqual(len(ops.writes),1)
        self.assertEqual(records[-1]['phase'],'task-exited')
        self.assertFalse(any(r.get('repaired') for r in records))

    def test_measurement_audit_rejects_sdk_reassignment_without_repair(self):
        ops=FakeTasks()
        with self.assertRaises(RuntimeError):
            capacity.audit_process(ops.expected,[0,2,4,6],ops,lambda row:None,repair=False)
        self.assertEqual(ops.writes,[])

    def test_no_metadata_only_ownership_or_second_correction(self):
        ops=FakeTasks()
        owner=SimpleNamespace(state={'emulatorIdentity':ops.expected},children=[])
        with self.assertRaises(RuntimeError): capacity.owned_sdk_processes(owner)
        for active, attempted in [(True,False),(False,True)]:
            owner=SimpleNamespace(measurement_active=active,correction_attempted=attempted)
            with self.assertRaises(RuntimeError): capacity.correct_owned_affinity(owner,{'hostCpus':4})

    def test_periodic_measurement_monitor_verifies_and_never_repairs(self):
        with patch.object(capacity.session,'identity',return_value=FakeTasks().expected):
            owner=capacity.CapacityOwner(runtime=1200)
        owner.measurement_active=True; owner.next_affinity_audit=0
        owner.next_progress=float('inf'); owner.profile={'hostCpus':4}
        with patch.object(capacity,'verify_children_affinity',side_effect=RuntimeError('SDK reassigned')) as verify, \
             patch.object(capacity,'correct_owned_affinity') as repair:
            with self.assertRaisesRegex(RuntimeError,'SDK reassigned'): owner.check()
            verify.assert_called_once_with(owner,owner.profile,'periodic-verification-only')
            repair.assert_not_called()


if __name__=='__main__': unittest.main(verbosity=2)
