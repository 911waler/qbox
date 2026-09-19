"""Offline acceptance orchestration and fail-closed, content-bound release gate.

Reports are local maintainer evidence, not signatures or third-party attestations.
The gate verifies their raw records and bytes; it never treats an absent run as PASS.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = ('ubuntu-20.04', 'ubuntu-22.04', 'ubuntu-24.04', 'rocky-8', 'rocky-9')
CASES = ('archive_install', 'test_01_final_paths_and_science', 'test_02_isolation_all_entries_and_external_environment', 'test_03_process_boundaries_stdin_and_signals', 'test_04_optional_tools_and_custom_prefix', 'test_05_readonly_and_cache_fallback', 'test_06_corrupt_bundle_failures_preserve_old', 'test_07_destination_conflicts_preserve_old', 'test_08_actual_noexec_mount', 'test_09_real_lock_contention', 'test_10_process_group_interruptions', 'test_11_two_prefixes_same_bin_race', 'test_12_reuse_upgrade_rollback_and_sigkill')
REPORT_FIELDS = 'schema_version platform_id os_release image_digest kernel arch cpu_flags glibc bash awk base_packages network_mode uid artifact_sha256 manifest_sha256 source_commit test_harness_commit test_harness_sha256 started_at finished_at cases status evidence failures skipped'.split()
BASELINE_FIELDS = 'schema_version platform_id kernel arch cpu_model cpu_flags network_mode uid emulator negative_control cases evidence failures skipped status artifact_sha256 manifest_sha256 source_commit'.split()
BASELINE_CASES = ('archive_install', 'full_smoke', 'sse3_negative_control', 'actual_noexec')
BINDING = ('artifact_sha256', 'manifest_sha256', 'source_commit')
SUPPLEMENT_CASES = {
    'regressions': ('shell', 'python'),
    'offline_tests': ('unit_suite', 'five_actual_targets', 'gate_unit_tests'),
    'reproducibility': ('first_build', 'second_build', 'identical_archives'),
    'elf_loads': ('all_members_bound', 'all_loader_resolutions', 'allowed_library_origins'),
    'documentation': ('checksum_extract', 'default_install', 'custom_spaces', 'verify_smoke', 'owned_lock_rollback', 'uninstall_ownership'),
}
SUPPLEMENTS = tuple(SUPPLEMENT_CASES)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def now():
    return datetime.now(timezone.utc).isoformat()


def _fields(value, fields, context):
    require(isinstance(value, dict), context + ': object required')
    for field in fields:
        require(field in value, context + ': missing ' + field)
        require(value[field] is not None, context + ': null ' + field)


def _passed(value, context):
    require(value.get('status') == 'passed', context + ': status must be passed')
    require(value.get('failures') == [] and value.get('skipped') == [], context + ': failures/skipped')


def _binding(candidate, value):
    for key in BINDING:
        require(value.get(key) == candidate.get(key) and candidate.get(key), 'mismatched ' + key)


def _cases(value, required):
    require(isinstance(value, dict) and set(value) == set(required), 'missing/unknown cases')
    require(all(status == 'passed' for status in value.values()), 'failed/not_run/skipped case')


def _refs(value):
    require(isinstance(value, dict) and value, 'missing evidence references')
    for record in value.values():
        require(isinstance(record, dict) and isinstance(record.get('path'), str), 'missing evidence path')
        require(re.fullmatch('[0-9a-f]{64}', record.get('sha256', '')), 'missing evidence sha256')


def validate_artifact_binding(candidate_sha: str, reports: list[dict]) -> None:
    require(re.fullmatch('[0-9a-f]{64}', candidate_sha or ''), 'invalid artifact sha256')
    for report in reports:
        require(report.get('artifact_sha256') == candidate_sha, 'mismatched artifact sha256')


def validate_evidence(candidate: dict, reports: list[dict], baseline_cpu_report: dict) -> None:
    validate_artifact_binding(candidate.get('artifact_sha256'), reports)
    require(len(reports) == 5 and {r.get('platform_id') for r in reports} == set(PLATFORMS), 'five distinct required platforms')
    harnesses = set()
    for report in reports:
        _fields(report, REPORT_FIELDS, 'platform report')
        _binding(candidate, report); _passed(report, report['platform_id'])
        _cases(report['cases'], CASES); _refs(report['evidence'])
        require({'results', 'inspect'} <= report['evidence'].keys(), 'missing results/inspect evidence')
        require(report['schema_version'] == 1 and report['arch'] == 'x86_64', 'schema/architecture')
        os_id, version = report['platform_id'].split('-')
        require(report['os_release'].get('ID') == os_id and (report['os_release'].get('VERSION_ID') == version if os_id == 'ubuntu' else report['os_release'].get('VERSION_ID', '').split('.')[0] == version), 'base platform mismatch')
        require(report['network_mode'] == 'none' and type(report['uid']) is int and report['uid'] > 0, 'network/root uid')
        for key in ('kernel', 'cpu_flags', 'glibc', 'bash', 'awk', 'base_packages', 'image_digest'):
            require(bool(report[key]), 'empty ' + key)
        require(re.fullmatch(r'.+@sha256:[0-9a-f]{64}', report['image_digest']), 'unpinned image')
        require('mawk' in report['awk'] if os_id == 'ubuntu' else 'gawk' in report['awk'], 'unexpected system awk')
        require(datetime.fromisoformat(report['finished_at']) >= datetime.fromisoformat(report['started_at']), 'invalid timestamps')
        require(re.fullmatch('[0-9a-f]{40}', report['test_harness_commit']), 'invalid harness commit')
        require(re.fullmatch('[0-9a-f]{64}', report['test_harness_sha256']), 'invalid harness sha')
        if report['test_harness_commit'] != candidate['source_commit']:
            require(bool(report.get('harness_deviation')), 'unrecorded harness/source difference')
        harnesses.add((report['test_harness_commit'], report['test_harness_sha256']))
    require(len(harnesses) == 1, 'platform harness mismatch')
    b = baseline_cpu_report
    _fields(b, BASELINE_FIELDS, 'baseline CPU'); _binding(candidate, b); _passed(b, 'baseline CPU')
    _cases(b['cases'], BASELINE_CASES); _refs(b['evidence'])
    require(b['schema_version'] == 1 and b['platform_id'] in ('ubuntu-20.04', 'rocky-8') and b['arch'] == 'x86_64', 'baseline platform')
    require(b['uid'] > 0 and b['network_mode'] == 'none' and bool(b['kernel']), 'baseline isolation/kernel')
    require('TCG' in b['emulator'] and re.search(r'8\.2\.', b['emulator']), 'baseline requires verified QEMU 8.2 TCG')
    require('vendor=GenuineIntel' in b['cpu_model'] and 'qemu64' in b['cpu_model'], 'baseline CPU model')
    flags = set(b['cpu_flags'])
    require({'sse', 'sse2'} <= flags and not flags & {'pni','sse3','ssse3','sse4_1','sse4_2','popcnt','cx16','lahf_lm','avx','avx2','fma','f16c','xsave','3dnowprefetch','svm'}, 'baseline CPU flags')
    require(b['negative_control'] == {'instruction':'HADDPS','signal':'SIGILL'}, 'baseline instruction negative control')


def validate_supplements(candidate, records):
    require(set(records) == set(SUPPLEMENTS), 'missing/unknown supplements')
    for name, record in records.items():
        _fields(record, (*BINDING, 'status', 'failures', 'skipped', 'cases', 'evidence'), name)
        _binding(candidate, record); _passed(record, name)
        _cases(record['cases'], SUPPLEMENT_CASES[name]); _refs(record['evidence'])


def validate_static_report(value, name):
    require(value.get('status') == 'passed-static' and value.get('errors') == [], name + ': missing/failed/not_run static audit')


def verify_candidate(candidate_path, bundle):
    """Check actual archive plus every declared byte, rejecting links/traversal."""
    candidate_path = Path(candidate_path).resolve(strict=True)
    candidate = read(candidate_path)
    name = candidate['artifact']
    require(Path(name).name == name, 'unsafe artifact filename')
    archive = candidate_path.parent / name
    require(sha(archive) == candidate['artifact_sha256'], 'actual artifact SHA mismatch')
    bundle = Path(bundle)
    require(not bundle.exists(), 'candidate extraction must be fresh')
    bundle.mkdir(parents=True)
    with tarfile.open(archive) as source:
        names = set()
        for item in source:
            require(not Path(item.name).is_absolute() and '..' not in Path(item.name).parts, 'unsafe archive path')
            require(item.isfile() or item.isdir(), 'archive links forbidden')
            require(item.name not in names, 'duplicate archive member'); names.add(item.name)
        source.extractall(bundle, filter='data')
    manifest = read(bundle / 'manifest.json')
    from .model import validate_manifest
    validate_manifest(manifest)
    require(sha(bundle / 'manifest.json') == candidate['manifest_sha256'], 'actual manifest SHA mismatch')
    require(manifest['source']['commit'] == candidate['source_commit'] and manifest['release_id'] == candidate['release_id'], 'manifest/source binding')
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    require(actual == {r['path'] for r in manifest['files']} | {'manifest.json','SHA256SUMS'}, 'actual payload set')
    for record in manifest['files']:
        path = bundle / record['path']
        require(path.stat().st_size == record['size'] and sha(path) == record['sha256'], 'payload mismatch: ' + record['path'])
    require(sha(bundle / 'checks/final-payload-audit.json') == candidate['audit_sha256'], 'audit binding')
    audit = read(bundle / 'checks/final-payload-audit.json')
    require(audit['status'] == 'passed-static' and audit['errors'] == [] and audit['source_commit'] == candidate['source_commit'], 'payload audit failure')
    for key in ('licenses','elf'):
        require(sha(bundle / ('checks/source-audit/' + key + '.json')) == audit['historical_reports'][key], key + ' audit binding')
        validate_static_report(read(bundle / ('checks/source-audit/' + key + '.json')), key)
    return candidate, archive, manifest


def reference(path, root):
    return {'path': Path(path).relative_to(root).as_posix(), 'sha256': sha(path)}


def _checked_reference(root, record):
    path = root / record['path']
    require(not Path(record['path']).is_absolute() and '..' not in Path(record['path']).parts, 'unsafe evidence path')
    require(path.resolve().is_relative_to(root.resolve()) and path.is_file(), 'missing evidence file')
    require(sha(path) == record['sha256'], 'evidence hash mismatch: ' + record['path'])
    return path


# This wrapper records the actual target OS, then uses target tar to expand the
# delivered archive. The reviewed Task10 script is copied byte-for-byte.
WRAPPER = r'''#!/bin/bash
set -euo pipefail
out=/evidence
cat /etc/os-release > "$out/os-release"
uname -r > "$out/kernel"
uname -m > "$out/arch"
id -u > "$out/uid"
grep -m1 '^flags' /proc/cpuinfo > "$out/cpu-flags"
getconf GNU_LIBC_VERSION > "$out/glibc"
bash --version > "$out/bash"
readlink -f /usr/bin/awk > "$out/awk"
if command -v dpkg-query >/dev/null; then dpkg-query -W > "$out/base-packages"; else rpm -qa --qf '%{NAME}=%{VERSION}-%{RELEASE}\n' > "$out/base-packages"; fi
mkdir /tmp/archive-install
sha256sum /payload/artifact.tar.gz > "$out/archive.sha256"
tar -xzf /payload/artifact.tar.gz -C /tmp/archive-install
(cd /tmp/archive-install && sha256sum -c SHA256SUMS) > "$out/archive-inventory.log"
printf 'passed\n' > "$out/archive-install"
exec bash /harness/run-target.sh /tmp/archive-install /evidence/target
'''


def matrix(candidate: Path, engine: str, output: Path) -> None:
    require(os.getuid() != 0, 'matrix requires nonroot maintainer')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    payload = output / 'payload'; payload.mkdir()
    identity, archive, _ = verify_candidate(candidate, payload / 'bundle')
    shutil.copyfile(archive, payload / 'artifact.tar.gz')
    harness = output / 'harness'; harness.mkdir()
    shutil.copyfile(ROOT / 'tests/offline/run-target.sh', harness / 'run-target.sh')
    (harness / 'matrix-target.sh').write_text(WRAPPER)
    (harness / 'pip.conf').write_text('[global]\nindex-url=http://127.0.0.1:9/poison\nno-binary=:all:\ntarget=/forbidden-global-target\n')
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    committed = subprocess.check_output(['git','show',commit+':tests/offline/run-target.sh'],cwd=ROOT)
    require(committed == (harness / 'run-target.sh').read_bytes(), 'uncommitted harness')
    images = read(ROOT / 'packaging/offline/images.lock.json')['validation']
    image_map = dict(zip(PLATFORMS, [images['public.ecr.aws/ubuntu/ubuntu:'+v] for v in ('20.04','22.04','24.04')] + [images['quay.io/rockylinux/rockylinux:'+v] for v in ('8','9')]))
    write(output / 'candidate.json', identity)
    def target(platform):
        target_output = output / platform; target_output.mkdir()
        started = now(); image = image_map[platform]
        command = [engine,'create','--pull=never','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,exec,mode=1777','--tmpfs','/noexec:rw,noexec,mode=1777','--env','QBOX_E2E_NOEXEC=/noexec']
        for src,dest,readonly in ((payload,'/payload',True),(harness,'/harness',True),(target_output,'/evidence',False),(harness/'pip.conf','/etc/pip.conf',True),(harness/'pip.conf','/etc/xdg/pip/pip.conf',True)):
            command += ['--mount',f'type=bind,src={src},dst={dest}'+(',readonly' if readonly else '')]
        command += [image,'bash','/harness/matrix-target.sh']
        write(target_output / 'command.json', command)
        container = subprocess.check_output(command,text=True).strip()
        try:
            inspect = json.loads(subprocess.check_output([engine,'inspect',container],text=True))[0]
            write(target_output / 'inspect.json', inspect)
            write(target_output / 'image-inspect.json',json.loads(subprocess.check_output([engine,'image','inspect',image],text=True))[0])
            with (target_output/'console.log').open('w') as log:
                result = subprocess.run([engine,'start','--attach',container],stdout=log,stderr=subprocess.STDOUT,timeout=10800)
            raw = read(target_output/'target/results.json') if (target_output/'target/results.json').exists() else {}
            logtext = (target_output/'target/unittest.log').read_text() if (target_output/'target/unittest.log').exists() else ''
            cases = {name:('passed' if re.search(r'^'+re.escape(name)+r' \(.*\) \.\.\. ok$',logtext,re.M) else 'not_run') for name in CASES[1:]}
            cases['archive_install'] = 'passed' if (target_output/'archive-install').exists() else 'not_run'
            def txt(name):return (target_output/name).read_text().strip() if (target_output/name).exists() else ''
            os_release = dict(line.split('=',1) for line in txt('os-release').replace('"','').splitlines() if '=' in line)
            report = {**{k:identity[k] for k in BINDING},'schema_version':1,'platform_id':platform,'os_release':os_release,'image_digest':image,'kernel':txt('kernel'),'kernel_scope':'container shares host kernel','arch':txt('arch'),'cpu_flags':txt('cpu-flags').split(':')[-1].split(),'glibc':txt('glibc'),'bash':txt('bash').split('\n')[0],'awk':txt('awk'),'base_packages':txt('base-packages').splitlines(),'network_mode':inspect['HostConfig']['NetworkMode'],'uid':int(txt('uid') or 0),'test_harness_commit':commit,'test_harness_sha256':sha(harness/'run-target.sh'),'started_at':started,'finished_at':now(),'cases':cases,'failures':raw.get('failures',['missing results']),'skipped':raw.get('skipped',[]),'status':'passed' if result.returncode==0 and all(v=='passed' for v in cases.values()) else 'failed','evidence':{}}
            if commit != identity['source_commit']:report['harness_deviation']='Test-driver commit recorded separately; exact committed harness bytes verified.'
            for key,path in [('results',target_output/'target/results.json'),('inspect',target_output/'inspect.json'),('image',target_output/'image-inspect.json'),('console',target_output/'console.log'),('unittest',target_output/'target/unittest.log')]:
                if path.exists():report['evidence'][key]=reference(path,output)
            write(target_output/'report.json',report)
            print(platform,report['status'],flush=True)
        finally:
            subprocess.run([engine,'rm','--force',container],check=True,stdout=subprocess.DEVNULL)
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(target,PLATFORMS))


def gate(candidate: Path, evidence: Path) -> None:
    """Write ready only after raw evidence, archive and all supplements agree."""
    import tempfile
    ready = ROOT / 'dist/offline/release-ready.json'
    if ready.exists():ready.unlink()  # never leave a stale successful verdict
    evidence = Path(evidence).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='qbox-gate-') as temporary:
        identity, _, manifest = verify_candidate(candidate, Path(temporary)/'bundle')
        reports = [read(evidence/platform/'report.json') for platform in PLATFORMS]
        baseline = read(evidence/'baseline-cpu.json')
        validate_evidence(identity,reports,baseline)
        images = read(ROOT/'packaging/offline/images.lock.json')['validation']
        expected_images = dict(zip(PLATFORMS,[images['public.ecr.aws/ubuntu/ubuntu:'+v] for v in ('20.04','22.04','24.04')]+[images['quay.io/rockylinux/rockylinux:'+v] for v in ('8','9')]))
        for report in [*reports,baseline]:
            for record in report['evidence'].values():_checked_reference(evidence,record)
        for report in reports:
            require(report['image_digest']==expected_images[report['platform_id']], 'wrong pinned platform image')
            raw=read(_checked_reference(evidence,report['evidence']['results']))
            require(raw['complete_suite'] is True and raw['tests_run']==12 and raw['selected_cases']==[] and raw['failures']==[] and raw['skipped']==[], 'incomplete raw target results')
            require(raw['manifest_sha256']==identity['manifest_sha256'] and raw['candidate_release_id']==identity['release_id'], 'raw target binding')
            inspect=read(_checked_reference(evidence,report['evidence']['inspect']))
            image=read(_checked_reference(evidence,report['evidence']['image']))
            require(inspect['HostConfig']['NetworkMode']=='none' and inspect['HostConfig']['ReadonlyRootfs'] is True, 'actual engine isolation')
            require(inspect['Image']==image['Id'] and report['image_digest'] in image['RepoDigests'], 'actual engine image identity')
            require(inspect['Config']['User'].split(':')[0]==str(report['uid']), 'actual engine uid')
            host=inspect['HostConfig']
            require(host['CapDrop']==['ALL'] and 'no-new-privileges' in host['SecurityOpt'], 'actual capabilities/security')
            require(host['Tmpfs'].get('/tmp')=='rw,exec,mode=1777' and host['Tmpfs'].get('/noexec')=='rw,noexec,mode=1777', 'actual temporary mounts')
            require(inspect['Config']['Cmd']==['bash','/harness/matrix-target.sh'], 'actual target command')
            destinations={m['Destination']:m for m in inspect['Mounts']}
            require(set(destinations)=={'/payload','/harness','/evidence','/etc/pip.conf','/etc/xdg/pip/pip.conf'}, 'unexpected host mounts')
            expected_sources={'/payload':evidence/'payload','/harness':evidence/'harness','/evidence':evidence/report['platform_id'],'/etc/pip.conf':evidence/'harness/pip.conf','/etc/xdg/pip/pip.conf':evidence/'harness/pip.conf'}
            for name,mount in destinations.items():
                require(mount['RW']==(name=='/evidence') and mount['Type']=='bind', 'host mount mutability')
                require(Path(mount['Source']).resolve()==expected_sources[name].resolve(), 'unexpected host mount source')
            require(set(p.name for p in (evidence/'harness').iterdir())=={'run-target.sh','matrix-target.sh','pip.conf'}, 'unexpected harness contents')
            require(sha(evidence/'payload/artifact.tar.gz')==identity['artifact_sha256'], 'mounted actual archive binding')
            require((evidence/report['platform_id']/'target/forbidden.log').read_bytes()==b'', 'forbidden host tool invoked')
            text=_checked_reference(evidence,report['evidence']['unittest']).read_text()
            for case in CASES[1:]:require(re.search(r'^'+re.escape(case)+r' \(.*\) \.\.\. ok$',text,re.M), 'raw target case not passed: '+case)
            import ast
            module=ast.parse(subprocess.check_output(['git','show',report['test_harness_commit']+':tools/offline/matrix.py'],cwd=ROOT))
            wrapper=next(ast.literal_eval(node.value) for node in module.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='WRAPPER' for t in node.targets))
            require((evidence/'harness/matrix-target.sh').read_text()==wrapper, 'committed target wrapper binding')
            committed=subprocess.check_output(['git','show',report['test_harness_commit']+':tests/offline/run-target.sh'],cwd=ROOT)
            require(hashlib.sha256(committed).hexdigest()==report['test_harness_sha256']==sha(evidence/'harness/run-target.sh'), 'actual harness binding')
        supplements={name:read(evidence/(name+'.json')) for name in SUPPLEMENTS}
        validate_supplements(identity, supplements)
        for name,record in supplements.items():
            _binding(identity,record);_passed(record,name);_refs(record.get('evidence'))
            for ref in record['evidence'].values():_checked_reference(evidence,ref)
            require(record.get('cases') and all(v=='passed' for v in record['cases'].values()), name+': incomplete cases')
        reproducibility=supplements['reproducibility']
        require(reproducibility.get('archive_sha256s')==[identity['artifact_sha256']]*2, 'two-build artifact binding')
        for name in ('archive1','archive2'):
            require(sha(_checked_reference(evidence,reproducibility['evidence'][name]))==identity['artifact_sha256'], 'actual reproducibility archive mismatch')
        require(reproducibility['evidence']['archive1']['path']!=reproducibility['evidence']['archive2']['path'], 'distinct build archives required')
        regressions=_checked_reference(evidence,supplements['regressions']['evidence']['raw']).read_text()
        require(len(re.findall(r'^PASS:',regressions,re.M))==241 and re.search(r'Ran 49 tests.*\n\nOK\s*$',regressions,re.S), 'original regression counts/results')
        require(not re.search(r'FAIL:|FAILED|skipped=',regressions), 'original regression failures/skip')
        units=read(_checked_reference(evidence,supplements['offline_tests']['evidence']['raw']))
        require(units['tests_run']>=196 and units['failures']==units['errors']==0 and units['skipped']==[], 'offline unit failures/count/skip')
        # Compare the actual verbose log with discovery; a plausible count alone
        # must not hide an omitted offline regression or duplicate test execution.
        import unittest
        def test_ids(suite):
            for item in suite:
                if isinstance(item,unittest.TestSuite):yield from test_ids(item)
                else:yield item.id()
        expected_tests={name for name in test_ids(unittest.TestLoader().discover(str(ROOT/'tests/offline'))) if not name.startswith('test_end_to_end.')}
        unit_log=_checked_reference(evidence,supplements['offline_tests']['evidence']['log']).read_text()
        actual_tests=re.findall(r'^test_\w+ \(([^)]+)\) \.\.\. ok$',unit_log,re.M)
        require(set(actual_tests)==expected_tests and len(actual_tests)==len(expected_tests)==units['tests_run'], 'omitted/duplicate offline tests')
        gate_tests=_checked_reference(evidence,supplements['offline_tests']['evidence']['gate']).read_text()
        require(re.search(r'Ran [1-9][0-9]* tests.*\n\nOK\s*$',gate_tests,re.S) and 'skipped=' not in gate_tests, 'gate unit tests')
        elf=supplements['elf_loads']
        rawelf=read(_checked_reference(evidence,elf['evidence']['raw']))
        expected=read(Path(temporary)/'bundle/checks/source-audit/elf.json')['elf']
        require(rawelf.get('expected_count')==len(expected)==249 and rawelf.get('resolved_count')==249 and rawelf.get('unresolved')==[], 'complete 249 ELF load closure required')
        require({r['member'] for r in rawelf['records']}==set(expected) and len(rawelf['records'])==249, 'missing/duplicate raw ELF members')
        source_audit=read(Path(temporary)/'bundle/checks/source-audit/elf.json')
        system_hashes={r['sha256'] for r in source_audit['baseline_system_libraries']['rocky8'].values()}
        delivered_hashes={r['sha256'] for r in expected.values()}
        for row in rawelf['records']:
            require(row['sha256']==expected[row['member']]['sha256'] and row['returncode']==0 and 'not found' not in row['output'], 'actual ELF bytes/loader failure')
            require(row['resolved'] and any(r['sha256']==row['sha256'] for r in row['resolved']), 'tested ELF not actually mapped')
            for library in row['resolved']:
                require(library['scope'] in ('release','OS'), 'unresolved library origin')
                require(library['sha256'] in (delivered_hashes if library['scope']=='release' else system_hashes), 'unbound loaded library bytes')
                require('/releases/'+identity['release_id']+'/' in library['path'] if library['scope']=='release' else library['path'].startswith(('/lib/','/lib64/','/usr/lib/','/usr/lib64/')), 'unexpected library path')
        diagnostic=read(_checked_reference(evidence,elf['evidence']['inspect']))[0]
        require(diagnostic['HostConfig']['NetworkMode']=='none' and diagnostic['HostConfig']['ReadonlyRootfs'] is True and diagnostic['Config']['User'].split(':')[0]!='0', 'diagnostic isolation')
        require(diagnostic['Config']['Image']==expected_images['rocky-8'], 'diagnostic base image')
        require({m['Destination'] for m in diagnostic['Mounts']}=={'/payload','/scripts','/evidence'} and all(m['RW']==(m['Destination']=='/evidence') for m in diagnostic['Mounts']), 'diagnostic mounts')
        docs=read(_checked_reference(evidence,supplements['documentation']['evidence']['raw']))
        _passed(docs,'actual documentation');_cases(docs['cases'],SUPPLEMENT_CASES['documentation'])
        require(all(row['returncode']==0 for row in docs['blocks']) and docs['uninstall_wrong_link_returncode']!=0 and docs['uninstall_owned_link_returncode']==0 and docs['sentinel_unchanged'] is True, 'actual documentation command results')
        blocks=re.findall(r'```bash\n(.*?)```',(Path(temporary)/'bundle/README.zh-CN.md').read_text(),re.S)
        require(len(docs['blocks'])==3 and {r['block'] for r in docs['blocks']}=={1,2,3}, 'required documentation blocks')
        for row in docs['blocks']:require(row['sha256']==hashlib.sha256(blocks[row['block']].encode()).hexdigest(), 'actual bundled documentation binding')
        guest=read(_checked_reference(evidence,baseline['evidence']['raw']))
        _binding(identity,guest);_passed(guest,'actual baseline guest');_cases(guest['cases'],BASELINE_CASES)
        require(guest['cpu_flags']==baseline['cpu_flags'] and guest['uid']==baseline['uid'] and guest['kernel']==baseline['kernel'] and guest['arch']==baseline['arch'], 'actual baseline facts')
        require(guest['negative_returncode']==-4 and guest['noexec_returncode']!=0 and guest['noexec_denied'] is True and guest['interfaces']==['lo'] and guest['manifest_actual']==identity['manifest_sha256'], 'actual baseline negative controls/binding/network')
        console=_checked_reference(evidence,baseline['evidence']['console']).read_text()
        require('SSE3_HADDPS_SIGILL -4' in console and 'QBOX_FINAL_VM_EXIT=0' in console and 'QBOX_FINAL_VM_PASSED' in console, 'actual VM completion log')
        command=read(_checked_reference(evidence,baseline['evidence']['commands']))[-1]
        require(command[command.index('-cpu')+1]==baseline['cpu_model'] and command[command.index('-accel')+1]=='tcg' and command[command.index('-nic')+1]=='none', 'actual VM command baseline')
        inspect=read(_checked_reference(evidence,baseline['evidence']['inspect']))[0]
        require(inspect['HostConfig']['NetworkMode']=='none' and inspect['Config']['User'].split(':')[0]==str(baseline['uid']) and inspect['Image']=='sha256:7cbb7eb643e1bc7802755fdcdacfa71c439451cffe7f406f5744881c881c43ec', 'actual VM engine identity/isolation')
        require(inspect['Config']['Cmd']==command[command.index(inspect['Image'])+1:], 'actual inspected VM command')
        smoke=read(_checked_reference(evidence,baseline['evidence']['smoke']))
        require(smoke['release_id']==identity['release_id'] and smoke['manifest_sha256']==identity['manifest_sha256'], 'actual VM smoke binding')
        names={'isolation','numpy-scipy','matplotlib-agg','ase-pymatgen','seekpath-spglib','qbox-convert-ase','qbox-convert-pymatgen','qbox-convert-basic','qbox-kpath','qbox-band-edges','native-components'}
        require(len(smoke['checks'])==len(names) and {r['name'] for r in smoke['checks']}==names and all(r['status']=='passed' for r in smoke['checks']), 'actual complete VM smoke required')

    index={str(p.relative_to(evidence)):sha(p) for p in sorted(evidence.rglob('*.json')) if 'payload' not in p.relative_to(evidence).parts}
    ready.parent.mkdir(parents=True,exist_ok=True)
    write(ready,{'schema_version':1,'status':'passed',**identity,'evidence':index,'created_at':now(),'scope':'local acceptance only; no publication'})
