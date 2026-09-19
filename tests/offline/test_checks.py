"""Failure-oriented contracts for the standalone installed-release checks."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('offline_verify', ROOT/'packaging/offline/checks/verify.py')
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class DependencyTests(unittest.TestCase):
    def test_missing_structure_extra_fails(self):
        with self.assertRaisesRegex(ValueError, 'ase'):
            verify.verify_dependency_edges([{'parent':'qbox','extra':'structure','name':'ase','specifier':'>=3'}], {'qbox':'0.1.0','numpy':'2.0.0'})

    def test_missing_analysis_extra_fails(self):
        edges=verify.resolve_edges({'qbox':['matplotlib; extra == "analysis"'],'matplotlib':[]},{'qbox':{'analysis','structure'}})
        with self.assertRaisesRegex(ValueError,'matplotlib'):
            verify.verify_dependency_edges(edges,{'qbox':'0.1.0'})

    def test_version_constraint(self):
        with self.assertRaisesRegex(ValueError, 'numpy'):
            verify.verify_dependency_edges([{'parent':'qbox','name':'numpy','specifier':'>=2'}], {'numpy':'1.0'})

    def test_marker_branch(self):
        verify.verify_dependency_edges([{'parent':'qbox','name':'missing','specifier':'','marker':'sys_platform == "win32"'}], {})
        with self.assertRaisesRegex(ValueError, 'missing'):
            verify.verify_dependency_edges([{'parent':'qbox','name':'missing','specifier':'','marker':'sys_platform == "linux"'}], {})

    def test_bad_marker_is_not_ignored(self):
        with self.assertRaises(ValueError):
            verify.verify_dependency_edges([{'parent':'qbox','name':'numpy','specifier':'','marker':'nonsense?'}], {'numpy':'2'})

    def test_extras_fixed_point_and_inactive_branch(self):
        records = {'qbox':['a[feature]>=1; extra == "structure"'], 'a':['b>=2; extra == "feature"', 'unavailable; sys_platform == "win32"'], 'b':[]}
        edges = verify.resolve_edges(records, {'qbox':{'analysis','structure'}})
        self.assertEqual({e['name'] for e in edges}, {'a','b'})
        with self.assertRaisesRegex(ValueError, 'b'):
            verify.verify_dependency_edges(edges, {'a':'1','b':'1'})

    def test_url_requirement_rejected(self):
        with self.assertRaisesRegex(ValueError, 'URL'):
            verify.resolve_edges({'qbox':['ase @ https://example.invalid/a.whl']}, {'qbox':set()})


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root/'python').mkdir()
        (self.root/'python/data').write_text('original')
        (self.root/'metadata').mkdir()

    def test_bytes_modes_extra_and_missing_files(self):
        inventory = verify.inventory(self.root)
        for kind in ('bytes','mode','extra','missing'):
            with self.subTest(kind=kind):
                p = self.root/'python/data'
                if kind == 'bytes': p.write_text('changed')
                if kind == 'mode': p.chmod(0o755)
                if kind == 'extra': (self.root/'python/extra').write_text('extra')
                if kind == 'missing': p.unlink()
                with self.assertRaisesRegex(ValueError, 'inventory'):
                    verify.compare_inventory(self.root, inventory)
                p.write_text('original'); p.chmod(0o644)
                (self.root/'python/extra').unlink(missing_ok=True)

    def test_metadata_exclusions_are_exact(self):
        before = verify.inventory(self.root)
        (self.root/'metadata/installed.json').write_text('{}')
        (self.root/'metadata/installed-files.json').write_text('{}')
        verify.compare_inventory(self.root,before)
        (self.root/'metadata/unknown.json').write_text('{}')
        with self.assertRaises(ValueError): verify.compare_inventory(self.root,before)

    def test_escaping_symlink_rejected(self):
        (self.root/'python/link').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'escape'): verify.inventory(self.root)

    def test_internal_symlink_target_and_mode_bound(self):
        (self.root/'python/link').symlink_to('data')
        before = verify.inventory(self.root)
        (self.root/'python/link').unlink()
        (self.root/'python/link').symlink_to('../python/data')
        with self.assertRaises(ValueError): verify.compare_inventory(self.root,before)

    def test_prepared_cannot_replace_inventory(self):
        verify.check_inventory(self.root,'prepared', '0'*64)
        digest = verify.sha256(self.root/'metadata/installed-files.json')
        verify.check_inventory(self.root,'final',digest)
        (self.root/'python/data').write_text('bad')
        with self.assertRaises(ValueError): verify.check_inventory(self.root,'prepared',digest)

    def test_deleted_sealed_inventory_cannot_be_recreated(self):
        verify.check_inventory(self.root,'prepared','0'*64)
        digest=verify.sha256(self.root/'metadata/installed-files.json')
        (self.root/'metadata/installed-files.json').unlink()
        (self.root/'python/data').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'missing sealed'):
            verify.check_inventory(self.root,'prepared',digest)

    def test_bad_inventory_digest_rejected(self):
        verify.check_inventory(self.root,'prepared','0'*64)
        with self.assertRaisesRegex(ValueError,'digest'): verify.check_inventory(self.root,'reuse','0'*64)


class ResourceTests(unittest.TestCase):
    def test_required_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for rel in ('bin/qbox','python/lib/python3.12/site-packages/qbox/legacy/entry.sh'):
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('test');p.chmod(0o755)
            package=root/'python/lib/python3.12/site-packages/qbox'
            verify.verify_resources(root, package)
            for rel in ('bin/qbox','python/lib/python3.12/site-packages/qbox/legacy/entry.sh'):
                p=root/rel;p.unlink()
                with self.assertRaisesRegex(ValueError,p.name): verify.verify_resources(root,package)
                p.write_text('test');p.chmod(0o755)


class ArtifactTests(unittest.TestCase):
    def test_runtime_tar_checks_installed_bytes(self):
        import io,tarfile
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'python').mkdir();(root/'python/demo').write_bytes(b'bad')
            archive=root/'runtime.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                entry=tarfile.TarInfo('python/demo');entry.size=4;tar.addfile(entry,io.BytesIO(b'good'))
            with self.assertRaisesRegex(ValueError,'runtime file'):
                verify.verify_runtime_files(root,archive)
            (root/'python/demo').write_bytes(b'good')
            verify.verify_runtime_files(root,archive)

    def test_wheel_checks_missing_resource_even_if_record_omitted_it(self):
        import zipfile
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'python/lib/python3.12/site-packages/demo').mkdir(parents=True)
            archive=root/'demo.whl'
            with zipfile.ZipFile(archive,'w') as wheel: wheel.writestr('demo/resource.py','original')
            with self.assertRaisesRegex(ValueError,'wheel file'):
                verify.verify_wheel_files(root,archive)
            (root/'python/lib/python3.12/site-packages/demo/resource.py').write_text('original')
            verify.verify_wheel_files(root,archive)

    def test_excluded_report_cannot_be_external_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'metadata').mkdir()
            (root/'metadata/smoke.json').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError): verify.inventory(root)

    def test_installed_record_corruption_and_missing_file(self):
        import base64,hashlib
        from importlib.metadata import PathDistribution
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);info=root/'demo-1.dist-info';info.mkdir()
            (info/'METADATA').write_text('Name: demo\nVersion: 1\n')
            digest=base64.urlsafe_b64encode(hashlib.sha256(b'good').digest()).rstrip(b'=').decode()
            (info/'RECORD').write_text('demo.py,sha256='+digest+',4\n')
            (root/'demo.py').write_bytes(b'bad!')
            with self.assertRaisesRegex(ValueError,'corrupt installed'): verify.verify_record(PathDistribution(info),root)
            (root/'demo.py').unlink()
            with self.assertRaisesRegex(ValueError,'missing installed'): verify.verify_record(PathDistribution(info),root)


class ProvenanceTests(unittest.TestCase):
    def test_future_build_and_normalize_track_shared_contracts(self):
        from tools.offline import cpu_wheels
        from unittest.mock import patch
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)
            with patch.object(subprocess,'run') as run, patch.object(subprocess,'check_output',return_value='a'*40):
                with self.assertRaisesRegex(ValueError,'missing pinned build input'):
                    cpu_wheels.build_wheels(ROOT/'packaging/offline/cpu-build-inputs.lock.json',base/'cache',base/'build')
                self.assertTrue(cpu_wheels.SHARED_CONTRACT_FILES <= set(run.call_args.args[0]))
            with patch.object(subprocess,'run') as run, patch.object(subprocess,'check_output',return_value='a'*40):
                with self.assertRaisesRegex(ValueError,'normalization input differs'):
                    cpu_wheels.finalize_wheels(ROOT/'packaging/offline/cpu-build-provenance.json',base/'cache',base/'final')
                self.assertTrue(cpu_wheels.SHARED_CONTRACT_FILES <= set(run.call_args.args[0]))

    def test_target_and_maintainer_use_same_validator(self):
        from tools.offline import cpu_wheels
        standalone=verify.sibling('provenance')
        for prefix in ('cpu-build','cpu-lxml-build'):
            raw=(ROOT/('packaging/offline/'+prefix+'-inputs.lock.json')).read_bytes()
            proof=json.loads((ROOT/('packaging/offline/'+prefix+'-provenance.json')).read_bytes())
            standalone.validate_provenance(proof,raw,proof['outputs'])
            cpu_wheels.validate_provenance(proof,raw,proof['outputs'])
            # Rebind input bytes so this exercises the immutable-image rule,
            # rather than merely tripping the independent input hash check.
            recipe=json.loads(raw);recipe['image']='mutable:latest';proof['image']='mutable:latest'
            proof['normalization']['image']='mutable:latest'
            raw=verify.canonical(recipe);proof['input_lock_sha256']=__import__('hashlib').sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError,'immutable'):
                standalone.validate_provenance(proof,raw,proof['outputs'])


class RetainedProofTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.checks=self.root/'metadata/checks';self.checks.mkdir(parents=True)
        self.lock=json.loads((ROOT/'packaging/offline/dependencies.lock.json').read_bytes())
        runtime=json.loads((ROOT/'packaging/offline/runtime.lock.json').read_bytes())
        import shutil,subprocess
        for name in ('dependencies.lock.json','runtime.lock.json','cpu-build-inputs.lock.json','cpu-build-provenance.json','cpu-lxml-build-inputs.lock.json','cpu-lxml-build-provenance.json'):
            shutil.copyfile(ROOT/'packaging/offline'/name,self.checks/name)
        for name in ('verify.py','manifest.py','provenance.py','smoke.py'):
            shutil.copyfile(ROOT/'packaging/offline/checks'/name,self.checks/name)
        shutil.copyfile(ROOT/'packaging/offline/qbox-launcher.sh',self.checks/'qbox-launcher.sh')
        (self.root/'bin').mkdir();shutil.copyfile(self.checks/'qbox-launcher.sh',self.root/'bin/qbox')
        for item in self.lock['cpu_build']:
            proof=json.loads((self.checks/item['provenance']).read_bytes())
            for stage,record in (('compile',proof),('normalize',proof['normalization'])):
                for name,digest in record['recipe_files'].items():
                    dest=self.checks/'cpu-build'/stage/item['id']/name;dest.parent.mkdir(parents=True,exist_ok=True)
                    # Exact historical recipe bytes, never current working copy.
                    dest.write_bytes(subprocess.check_output(['git','show',record['code_commit']+':'+name],cwd=ROOT))
        files=[{'path':'checks/'+p.relative_to(self.checks).as_posix(),'sha256':verify.sha256(p),'size':p.stat().st_size} for p in self.checks.rglob('*') if p.is_file()]
        self.manifest={'files':files,'identity':{'checks':{p['path']:p['sha256'] for p in files if p['path']!='checks/qbox-launcher.sh'}},'runtime':{'version':runtime['version'],'sha256':runtime['normalized']['sha256']},'bootstrap_packages':runtime['bootstrap_packages'],'extras':['analysis','structure'],'wheels':[{**p,'path':'wheelhouse/'+p['filename']} for p in self.lock['packages']]}

    def test_both_components_and_recipe_bytes(self):
        verify.verify_payload(self.root,self.manifest)
        item=self.lock['cpu_build'][0]
        proof=json.loads((self.checks/item['provenance']).read_bytes())
        path=self.checks/'cpu-build/compile'/item['id']/next(iter(proof['recipe_files']))
        path.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'retained evidence'):
            verify.verify_payload(self.root,self.manifest)

    def test_output_sha_crosslink_rejects_manifest_change(self):
        self.manifest['wheels'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'wheel differs from lock'):
            verify.verify_payload(self.root,self.manifest)

    def test_component_proof_must_be_bound_by_identity(self):
        del self.manifest['identity']['checks']['checks/cpu-build-provenance.json']
        with self.assertRaisesRegex(ValueError,'proof/input digest'):
            verify.verify_payload(self.root,self.manifest)

    def test_required_standalone_check_cannot_be_omitted(self):
        del self.manifest['identity']['checks']['checks/manifest.py']
        with self.assertRaisesRegex(ValueError,'required check missing'):
            verify.verify_payload(self.root,self.manifest)


class IdentityTests(unittest.TestCase):
    def test_wrong_manifest_and_release_identity(self):
        spec=importlib.util.spec_from_file_location('model_tests',ROOT/'tests/offline/test_model.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        manifest=helper.complete_manifest()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'metadata').mkdir();path=root/'metadata/manifest.json'
            path.write_text(json.dumps(manifest))
            verify.verify_manifest(root,path,manifest)
            manifest['release_id']='0.1.0-'+'0'*64
            with self.assertRaisesRegex(ValueError,'release_id'): verify.verify_manifest(root,path,manifest)

    def test_marker_phase_state_and_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'metadata').mkdir();path=root/'metadata/installed.json'
            marker={'schema_version':1,'product':'qbox','release_id':'release','manifest_sha256':'a'*64,'inventory_sha256':'b'*64,'state':'prepared'}
            path.write_text(json.dumps(marker));manifest={'release_id':'release'}
            verify.verify_marker(root,manifest,'prepared','a'*64)
            verify.verify_marker(root,manifest,'final','a'*64)
            with self.assertRaisesRegex(ValueError,'state'):verify.verify_marker(root,manifest,'reuse','a'*64)
            with self.assertRaisesRegex(ValueError,'identity'):verify.verify_marker(root,manifest,'final','c'*64)
            marker['state']='verified';path.write_text(json.dumps(marker))
            verify.verify_marker(root,manifest,'reuse','a'*64)


if __name__ == '__main__': unittest.main()
