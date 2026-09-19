"""Small, network-forbidden offline assembly fixtures."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.offline import build as builder
from tools.offline.model import canonical_json, sha256_file, validate_manifest

ROOT = Path(__file__).resolve().parents[2]


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.locks = self.source / 'packaging/offline'
        self.locks.mkdir(parents=True)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.source.joinpath('.gitignore').write_text('.venv/\n__pycache__/\ncalc.out\nprivate.conf\n')
        for name in ('install.sh', 'qbox-launcher.sh'):
            shutil.copyfile(ROOT / 'packaging/offline' / name, self.locks / name)
        self.locks.joinpath('README.zh-CN.md').write_text('候选包，待最终兼容性验证。\n')
        shutil.copyfile(ROOT / 'LICENSE', self.source / 'LICENSE')
        shutil.copytree(ROOT / 'packaging/offline/checks', self.locks / 'checks', ignore=shutil.ignore_patterns('__pycache__'))
        self.locks.joinpath('build-requirements.lock').write_text('')
        self.runtime = self.cache / 'python.tar.gz'
        with tarfile.open(self.runtime, 'w:gz') as archive:
            info = tarfile.TarInfo('python/bin/python3'); info.mode = 0o755; info.size = 4
            archive.addfile(info, io.BytesIO(b'fake'))
        self.wheel = self.root / 'qbox-1.2.3-py3-none-any.whl'
        with zipfile.ZipFile(self.wheel, 'w') as wheel:
            for name in ('qbox/registry.py','qbox/legacy/load.sh','qbox/legacy/entry.sh','qbox/bin/qbox-dopant-pdos.py','qbox/postprocess/effective_mass_vasp.py'):
                wheel.writestr(name, '# fixture\n')
            info = zipfile.ZipInfo('qbox/bin/qbox'); info.external_attr = 0o100755 << 16
            wheel.writestr(info, '#!/bin/bash\n')
            wheel.writestr('qbox-1.2.3.dist-info/METADATA', 'Name: qbox\nVersion: 1.2.3\nProvides-Extra: analysis\nProvides-Extra: structure\n')
            wheel.writestr('qbox-1.2.3.dist-info/licenses/LICENSE', (ROOT/'LICENSE').read_bytes())
        deps = self.cache / 'candidate-wheelhouse'; deps.mkdir()
        dep = deps / 'demo-1.0-py3-none-any.whl'
        with zipfile.ZipFile(dep, 'w') as wheel:
            wheel.writestr('demo-1.0.dist-info/METADATA', 'Name: demo\nVersion: 1.0\n')
        def asset(path):
            return dict(filename=path.name, sha256=sha256_file(path), url='https://example.org/'+path.name)
        self.package = dict(name='demo', version='1.0', filename=dep.name, sha256=sha256_file(dep), size=dep.stat().st_size, source=asset(dep))
        runtime = dict(source=asset(self.runtime), normalized=dict(sha256=sha256_file(self.runtime),size=self.runtime.stat().st_size), implementation='cpython',version='3.12.14',bootstrap_packages=[dict(name='pip',version='26.2.1')])
        dependencies = dict(packages=[self.package], build_packages=[], qbox_resolution_wheel=dict(requires_dist=[]))
        licenses = dict(runtime_sha256=sha256_file(self.runtime), wheels={dep.name:dict(sha256=sha256_file(dep))})
        for name,value in [('runtime',runtime),('dependencies',dependencies),('licenses',licenses)]:
            self.locks.joinpath(name+'.lock.json').write_bytes(canonical_json(value))
        self.locks.joinpath('requirements.lock').write_text(f'demo==1.0 --hash=sha256:{self.package["sha256"]}\n')
        audit = self.cache / 'audit'; (audit/'materials').mkdir(parents=True)
        material = audit / 'materials/license'; material.write_text('Official https://example.org license contact@example.org\n')
        component = dict(id='demo==1.0', licenses=['MIT'], materials=['materials/license'], sources=[], unresolved=[], license_ids=['LicenseRef-demo'])
        runtime_component = dict(component, id='cpython', license_ids=['LicenseRef-python'])
        report = dict(status='passed-static',errors=[],lock_sha256=sha256_file(self.locks/'licenses.lock.json'),payload_inputs=dict(runtime=runtime['normalized'],wheels={dep.name:self.package['sha256']}),components=[component,runtime_component],materials=[dict(path='materials/license',sha256=sha256_file(material),size=material.stat().st_size,source=asset(material),source_member='LICENSE')],license_map={'LicenseRef-demo':['materials/license'],'LicenseRef-python':['materials/license']})
        for name,value in [('licenses',report),('elf',dict(status='passed-static',errors=[],cpu_baseline_verified=False))]:
            (audit/(name+'.json')).write_bytes(canonical_json(value))
        descriptor = {name:dict(path=name+'.json',sha256=sha256_file(audit/(name+'.json')),size=(audit/(name+'.json')).stat().st_size) for name in ('licenses','elf')}
        (audit/'descriptor.json').write_bytes(canonical_json(descriptor))
        subprocess.run(['git','init','-q',str(self.source)],check=True)
        subprocess.run(['git','-C',str(self.source),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.source),'-c','user.name=Fixture','-c','user.email=fixture@example.org','commit','-qm','fixture'],check=True,env={'PATH':'/usr/bin:/bin','GIT_AUTHOR_DATE':'2020-01-01T00:00:00Z','GIT_COMMITTER_DATE':'2020-01-01T00:00:00Z'})
        for name in ('.venv/sentinel','__pycache__/sentinel','calc.out','private.conf'):
            path=self.source/name; path.parent.mkdir(exist_ok=True); path.write_text('PRIVATE_SENTINEL')
        self.addCleanup(patch.stopall)
        patch.object(builder,'ROOT',self.source).start()
        patch.object(builder,'_build_wheel',return_value=self.wheel).start()
        patch('socket.socket',side_effect=AssertionError('network forbidden')).start()
        patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')).start()

    def build(self, name='output'):
        return builder.build(self.cache,self.root/name)

    def test_same_inputs_produce_same_archive(self):
        first=json.loads(self.build('first').read_text()); second=json.loads(self.build('second').read_text())
        self.assertEqual(first['artifact_sha256'],second['artifact_sha256'])
        self.assertEqual(first['release_id'],second['release_id'])
        with tarfile.open(self.root/'first'/first['artifact']) as archive:
            names=archive.getnames()
            self.assertFalse(any(any(x in n for x in ('.git','.venv','__pycache__','calc.out','private.conf')) for n in names))
            manifest=json.load(archive.extractfile('manifest.json')); validate_manifest(manifest)
            lock=archive.extractfile('requirements.lock').read()
            self.assertTrue(lock.startswith(b'qbox[analysis,structure]==1.2.3 --hash=sha256:'))
            self.assertEqual(manifest['identity']['dependencies_lock_sha256'],hashlib.sha256(lock).hexdigest())
            self.assertEqual(archive.extractfile('install.sh').read(),(self.locks/'install.sh').read_bytes())
            self.assertIn(b'https://example.org',archive.extractfile('THIRD_PARTY_LICENSES/materials/license').read())
            self.assertTrue(all(m.uid==m.gid==0 and not m.uname and not m.gname and m.mtime==1577836800 for m in archive))

    def test_missing_or_corrupt_inputs_fail_without_candidate(self):
        for path in (self.cache/'candidate-wheelhouse'/self.package['filename'],self.cache/'audit/materials/license',self.runtime):
            original=path.read_bytes()
            for data in (None, original+b'x'):
                with self.subTest(path=path,data=data is None):
                    if data is None: path.unlink()
                    else: path.write_bytes(data)
                    with self.assertRaises((ValueError,OSError)): self.build()
                    self.assertFalse((self.root/'output/candidate.json').exists())
                    path.write_bytes(original)

    def test_unsafe_cache_path_fails(self):
        descriptor=self.cache/'audit/descriptor.json'; value=json.loads(descriptor.read_text())
        value['licenses']['path']='../../outside.json';descriptor.write_bytes(canonical_json(value))
        with self.assertRaises(ValueError):self.build()
        self.assertFalse((self.root/'output/candidate.json').exists())

    def test_dirty_source_fails(self):
        (self.source/'LICENSE').write_text('modified')
        with self.assertRaisesRegex(ValueError,'clean|uncommitted'):self.build()

    def test_different_payload_cannot_overwrite_output(self):
        candidate=self.build(); before=candidate.read_bytes()
        with patch.object(builder,'_source_identity',return_value=('a'*40,1577836800)):
            with self.assertRaisesRegex(ValueError,'exist|different'):self.build()
        self.assertEqual(candidate.read_bytes(),before)

    def test_changed_metadata_requires_new_resolution(self):
        with zipfile.ZipFile(self.wheel,'a') as wheel:
            wheel.writestr('qbox-1.2.3.dist-info/entry_points.txt','[console_scripts]\nqbox=qbox.cli:main\n')
        # Lock comparison is made from actual wheel metadata, never a source version literal.
        dependencies=json.loads((self.locks/'dependencies.lock.json').read_text())
        dependencies['qbox_resolution_wheel']['requires_dist']=['numpy; extra == "analysis"']
        (self.locks/'dependencies.lock.json').write_bytes(canonical_json(dependencies))
        with patch.object(builder,'_source_identity',return_value=('a'*40,1577836800)):
            with self.assertRaisesRegex(ValueError,'resolve|METADATA'):self.build()

    def test_audit_mismatch_rejected(self):
        path=self.cache/'audit/licenses.json';report=json.loads(path.read_text())
        report['payload_inputs']['wheels'][self.package['filename']]='0'*64
        path.write_bytes(canonical_json(report))
        descriptor=self.cache/'audit/descriptor.json';value=json.loads(descriptor.read_text())
        value['licenses'].update(sha256=sha256_file(path),size=path.stat().st_size)
        descriptor.write_bytes(canonical_json(value))
        with self.assertRaisesRegex(ValueError,'audit does not bind'):self.build()

    def test_license_package_names_are_normalized(self):
        path=self.cache/'audit/licenses.json';report=json.loads(path.read_text())
        report['components'][0]['id']='Demo==1.0'
        path.write_bytes(canonical_json(report))
        descriptor=self.cache/'audit/descriptor.json';value=json.loads(descriptor.read_text())
        value['licenses'].update(sha256=sha256_file(path),size=path.stat().st_size)
        descriptor.write_bytes(canonical_json(value))
        self.assertTrue(self.build().is_file())

    def test_dependency_member_punctuation_preserved_but_traversal_rejected(self):
        path=self.cache/'candidate-wheelhouse'/self.package['filename']
        original=path.read_bytes()
        for member,allowed in [('demo/A#2.json',True),('demo/Li3V2(PO4)3.json',True),('demo/Transparent Busy.ani',True),('../escape',False)]:
            with self.subTest(member=member):
                path.write_bytes(original)
                with zipfile.ZipFile(path,'a') as archive:archive.writestr(member,'data')
                self.package.update(sha256=sha256_file(path),size=path.stat().st_size)
                deps=json.loads((self.locks/'dependencies.lock.json').read_text());deps['packages']=[self.package]
                (self.locks/'dependencies.lock.json').write_bytes(canonical_json(deps))
                (self.locks/'requirements.lock').write_text(f'demo==1.0 --hash=sha256:{self.package["sha256"]}\n')
                # Audit binding is independent of ZIP path policy and covered separately.
                report=json.loads((self.cache/'audit/licenses.json').read_text())
                with patch.object(builder,'_source_identity',return_value=('a'*40,1577836800)),patch.object(builder,'_audit_inputs',return_value=(json.loads((self.cache/'audit/descriptor.json').read_text()),{'licenses':report,'elf':{'auditwheel':[]}})):
                    if allowed:self.assertTrue(self.build(member.replace('/','_')).is_file())
                    else:
                        with self.assertRaises(ValueError):self.build()

    def test_cache_symlink_is_rejected(self):
        path=self.cache/'candidate-wheelhouse'/self.package['filename']
        actual=self.root/'alias.whl';path.rename(actual);path.symlink_to(actual)
        with self.assertRaisesRegex(ValueError,'symlink'):self.build()

    def test_qbox_native_and_private_resources_rejected(self):
        original=self.wheel.read_bytes()
        for name,data in [('qbox/native.so',b'\x7fELFbad'),('qbox/__pycache__/private.pyc',b'bad'),('qbox/secret.py',b'/home/waler/private'),('../escape',b'bad')]:
            with self.subTest(name=name):
                with zipfile.ZipFile(self.wheel,'a') as wheel:wheel.writestr(name,data)
                with self.assertRaises(ValueError):self.build()
                self.assertFalse((self.root/'output/candidate.json').exists())
                self.wheel.write_bytes(original)

    def test_changed_version_is_read_from_metadata(self):
        self.assertEqual(json.loads(self.build().read_text())['artifact'],'qbox-1.2.3-linux-x86_64-offline.tar.gz')

    def test_identical_candidate_can_be_reused(self):
        first=self.build().read_bytes()
        self.assertEqual(self.build().read_bytes(),first)

    def test_source_change_during_build_is_rejected(self):
        with patch.object(builder,'_source_identity',side_effect=[('a'*40,1577836800),('b'*40,1577836800)]):
            with self.assertRaisesRegex(ValueError,'source changed'):self.build()
        self.assertFalse((self.root/'output/candidate.json').exists())

if __name__=='__main__':unittest.main()
