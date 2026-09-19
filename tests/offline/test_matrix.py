"""Fail-closed release evidence contracts (no container dependency)."""
import copy
import unittest
from tools.offline.matrix import validate_artifact_binding, validate_evidence

PLATFORMS = ('ubuntu-20.04', 'ubuntu-22.04', 'ubuntu-24.04', 'rocky-8', 'rocky-9')
CASES = ('archive_install', 'test_01_final_paths_and_science', 'test_02_isolation_all_entries_and_external_environment', 'test_03_process_boundaries_stdin_and_signals', 'test_04_optional_tools_and_custom_prefix', 'test_05_readonly_and_cache_fallback', 'test_06_corrupt_bundle_failures_preserve_old', 'test_07_destination_conflicts_preserve_old', 'test_08_actual_noexec_mount', 'test_09_real_lock_contention', 'test_10_process_group_interruptions', 'test_11_two_prefixes_same_bin_race', 'test_12_reuse_upgrade_rollback_and_sigkill')

def fixture():
    candidate = dict(artifact_sha256='a'*64, manifest_sha256='b'*64, source_commit='c'*40)
    reports=[]
    for platform in PLATFORMS:
        os_id, version=platform.split('-')
        reports.append(dict(candidate, schema_version=1, platform_id=platform,
            os_release={'ID':os_id,'VERSION_ID':version}, image_digest='repo@sha256:'+'d'*64,
            kernel='shared host kernel', arch='x86_64', cpu_flags=['sse2'], glibc='2.31',
            bash='5.0', awk='mawk' if os_id=='ubuntu' else 'gawk', base_packages=['bash=5'],
            network_mode='none', uid=1000, test_harness_commit='c'*40,
            test_harness_sha256='e'*64, started_at='2026-09-20T00:00:00+00:00',
            finished_at='2026-09-20T00:01:00+00:00', cases={name:'passed' for name in CASES},
            status='passed', evidence={'results':{'path':platform+'/results.json','sha256':'f'*64},
                                      'inspect':{'path':platform+'/inspect.json','sha256':'f'*64}},
            failures=[], skipped=[]))
    baseline=dict(candidate, schema_version=1,status='passed',platform_id='ubuntu-20.04',
        kernel='5.4.0-216-generic', arch='x86_64', cpu_model='qemu64,vendor=GenuineIntel,-sse3',
        cpu_flags=['sse','sse2'], network_mode='none', uid=1000, emulator='QEMU 8.2.2 TCG',
        negative_control={'instruction':'HADDPS','signal':'SIGILL'},
        cases={name:'passed' for name in ('archive_install','full_smoke','sse3_negative_control','actual_noexec')},
        evidence={'console':{'path':'baseline/console.log','sha256':'f'*64}}, failures=[],skipped=[])
    return candidate,reports,baseline

class MatrixGateTests(unittest.TestCase):
    def test_complete(self): validate_evidence(*fixture())
    def test_five_reports_must_describe_the_same_artifact(self):
        c,r,b=fixture();r[3]['artifact_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'artifact'):validate_artifact_binding(c['artifact_sha256'],r)
    def test_each_required_report_field(self):
        c,r,b=fixture()
        for key in r[0]:
            with self.subTest(key=key):
                changed=copy.deepcopy(r);del changed[0][key]
                with self.assertRaises(ValueError):validate_evidence(c,changed,b)
    def test_each_required_case_rejects_absent_or_nonpass(self):
        for name in CASES:
            for status in (None,'failed','not_run','skipped','skip'):
                c,r,b=fixture()
                if status is None:del r[0]['cases'][name]
                else:r[0]['cases'][name]=status
                with self.subTest(name=name,status=status),self.assertRaises(ValueError):validate_evidence(c,r,b)
    def test_bad_platform_bindings_and_execution(self):
        for key,value in [('artifact_sha256','0'*64),('manifest_sha256','0'*64),('source_commit','0'*40),('test_harness_commit','0'*40),('network_mode','bridge'),('uid',0),('os_release',{'ID':'ubuntu','VERSION_ID':'24.04'}),('status','not_run'),('skipped',['smoke']),('failures',['failure']),('evidence',{})]:
            c,r,b=fixture();r[0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_evidence(c,r,b)
    def test_missing_duplicate_platform(self):
        c,r,b=fixture()
        for changed in (r[:-1],r+[r[0]],r[:-1]+[r[0]]):
            with self.assertRaises(ValueError):validate_evidence(c,changed,b)
    def test_each_baseline_field_and_case_required(self):
        c,r,b=fixture()
        for key in b:
            changed=copy.deepcopy(b);del changed[key]
            with self.subTest(key=key),self.assertRaises(ValueError):validate_evidence(c,r,changed)
        for name in b['cases']:
            changed=copy.deepcopy(b);changed['cases'][name]='not_run'
            with self.subTest(name=name),self.assertRaises(ValueError):validate_evidence(c,r,changed)
    def test_baseline_cannot_be_modern_cpu_or_cpuid_only(self):
        for key,value in [('cpu_flags',['sse2','pni']),('negative_control',{'instruction':'HADDPS','signal':'none'}),('emulator','QEMU 6.2 TCG'),('uid',0),('network_mode','user')]:
            c,r,b=fixture();b[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_evidence(c,r,b)

if __name__=='__main__':unittest.main()
