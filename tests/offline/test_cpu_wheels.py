"""Pinned maintainer CPU wheels: selection, integrity and build isolation."""
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.offline import cpu_wheels


class CpuWheelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def wheel(self, directory, text=b'baseline'):
        directory.mkdir(parents=True, exist_ok=True)
        p = directory/'numpy-2.5.3-1qboxcpu-cp312-cp312-manylinux_2_28_x86_64.whl'
        files = {'numpy/demo.so':text, 'numpy-2.5.3.dist-info/METADATA':b'Name: numpy\nVersion: 2.5.3\n', 'numpy-2.5.3.dist-info/WHEEL':b'Wheel-Version: 1.0\nTag: cp312-cp312-manylinux_2_28_x86_64\n'}
        rows = []
        for name, data in files.items():
            rows.append([name, 'sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode(),str(len(data))])
        record='numpy-2.5.3.dist-info/RECORD'
        rows.append([record,'',''])
        out=io.StringIO();csv.writer(out,lineterminator='\n').writerows(rows)
        files[record]=out.getvalue().encode()
        with zipfile.ZipFile(p,'w') as z:
            for n,d in files.items():z.writestr(n,d)
        return p

    def test_record_validation_checks_all_content_and_members(self):
        p=self.wheel(self.root/'wheels')
        cpu_wheels.validate_record(p)
        with zipfile.ZipFile(p,'a') as z:z.writestr('unrecorded',b'bad')
        with self.assertRaisesRegex(ValueError,'RECORD'):
            cpu_wheels.validate_record(p)

    def test_cached_selection_fails_closed_and_never_builds_or_downloads(self):
        p=self.wheel(self.root/'cache'/'cpu-wheelhouse')
        record={'name':'numpy','version':'2.5.3','filename':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        lock={'outputs':[record]}
        self.assertEqual(cpu_wheels.select_wheels(lock,self.root/'cache'),[p])
        p.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'hash'):
            cpu_wheels.select_wheels(lock,self.root/'cache')
        p.unlink()
        with self.assertRaisesRegex(ValueError,'explicit.*build'):
            cpu_wheels.select_wheels(lock,self.root/'cache')

    def test_build_contract_rejects_unpinned_image_and_native_flags(self):
        recipe={'image':'quay.io/pypa/manylinux_2_28_x86_64:latest','environment':{'CFLAGS':'-O2 -march=x86-64 -mtune=generic'},'sources':[], 'build_packages':[]}
        with self.assertRaisesRegex(ValueError,'digest'):
            cpu_wheels.validate_recipe(recipe)
        recipe['image']='quay.io/pypa/manylinux_2_28_x86_64@sha256:'+'a'*64
        recipe['environment']['CFLAGS']='-O2 -march=native'
        with self.assertRaisesRegex(ValueError,'native'):
            cpu_wheels.validate_recipe(recipe)

    def test_global_build_flags_cannot_raise_baseline_or_omit_fortran(self):
        flags='-O2 -march=x86-64 -mtune=generic'
        recipe={'image':'image@sha256:'+'a'*64,'environment':{k:flags for k in ('CFLAGS','CXXFLAGS','FFLAGS')},'sources':[],'build_packages':[]}
        cpu_wheels.validate_recipe(recipe)
        recipe['environment']['FFLAGS']=flags+' -mavx2'
        with self.assertRaisesRegex(ValueError,'baseline'):
            cpu_wheels.validate_recipe(recipe)
        del recipe['environment']['FFLAGS']
        with self.assertRaisesRegex(ValueError,'baseline'):
            cpu_wheels.validate_recipe(recipe)

    def test_normalization_sets_build_tag_and_preserves_payload(self):
        p=self.wheel(self.root/'original')
        out=cpu_wheels.normalize_wheel(p,self.root/'out')
        cpu_wheels.validate_record(out)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(z.read('numpy/demo.so'),b'baseline')
            self.assertIn(b'Build: 1qboxcpu',z.read('numpy-2.5.3.dist-info/WHEEL'))
        second=cpu_wheels.normalize_wheel(p,self.root/'second')
        self.assertEqual(out.read_bytes(),second.read_bytes())

    def test_provenance_binds_inputs_source_and_output_identity(self):
        source={'url':'https://example.org/numpy.tar.gz','filename':'numpy.tar.gz','sha256':'a'*64}
        recipe={'recipe':'recipe.sh','image':'image@sha256:'+'b'*64,'sources':[{'name':'numpy','source':source}]}
        raw=json.dumps(recipe).encode()
        package={'name':'numpy','filename':'numpy-2.5.3-1qboxcpu-cp312-cp312-manylinux_2_28_x86_64.whl','sha256':'c'*64,'source':source}
        proof={'kind':'qbox-maintainer-cpu-build','code_commit':'d'*40,'recipe_files':{'recipe.sh':'e'*64,'tools/offline/cpu_wheels.py':'e'*64},'patches':[], 'image':recipe['image'],'input_lock_sha256':hashlib.sha256(raw).hexdigest(),'outputs':[package], 'network':'none','repeat_builds':2}
        proof['compilation_outputs']=[package]
        proof['normalization']={'code_commit':'d'*40,'recipe_files':{path:'e'*64 for path in cpu_wheels.NORMALIZATION_FILES},'image':recipe['image'],'outputs':[package],'network':'none','independent_runs':2,'inputs':[{'run':n,'wheels':{package['filename']:package['sha256']}} for n in (1,2)]}
        proof['sources']=[source]
        cpu_wheels.validate_provenance(proof,raw,[package])
        proof['sources']=[source]
        with self.assertRaisesRegex(ValueError,'source'):
            cpu_wheels.validate_provenance({**proof,'sources':[]},raw,[package])
        changed={**package,'sha256':'f'*64}
        with self.assertRaisesRegex(ValueError,'output'):
            cpu_wheels.validate_provenance(proof,raw,[changed])
        with self.assertRaisesRegex(ValueError,'input'):
            cpu_wheels.validate_provenance(proof,raw+b' ',[package])

    def test_normalization_provenance_must_bind_final_output(self):
        source={'url':'https://example.org/numpy.tar.gz','filename':'numpy.tar.gz','sha256':'a'*64}
        recipe={'recipe':'recipe.sh','image':'image@sha256:'+'b'*64,'sources':[{'name':'numpy','source':source}]}
        raw=json.dumps(recipe).encode()
        package={'name':'numpy','filename':'numpy-2.5.3-1qboxcpu-cp312-cp312-manylinux_2_28_x86_64.whl','sha256':'c'*64,'source':source}
        proof={'kind':'qbox-maintainer-cpu-build','code_commit':'d'*40,'recipe_files':{'recipe.sh':'e'*64,'tools/offline/cpu_wheels.py':'e'*64},'patches':[],'image':recipe['image'],'input_lock_sha256':hashlib.sha256(raw).hexdigest(),'outputs':[package],'network':'none','repeat_builds':2,'normalization':{'code_commit':'d'*40,'recipe_files':{path:'e'*64 for path in cpu_wheels.NORMALIZATION_FILES},'image':recipe['image'],'outputs':[{**package,'sha256':'f'*64}]}}
        proof['sources']=[source]
        with self.assertRaisesRegex(ValueError,'normalization'):
            cpu_wheels.validate_provenance(proof,raw,[package])

    def test_provenance_requires_every_compile_and_normalization_recipe(self):
        import copy
        locks=Path(__file__).resolve().parents[2]/'packaging/offline'
        for prefix in ('cpu-build','cpu-lxml-build'):
            raw=(locks/(prefix+'-inputs.lock.json')).read_bytes()
            recipe=json.loads(raw)
            proof=json.loads((locks/(prefix+'-provenance.json')).read_text())
            cpu_wheels.validate_provenance(proof,raw,proof['outputs'])
            for path in [recipe['recipe'],*recipe.get('helpers',{}),'tools/offline/cpu_wheels.py']:
                with self.subTest(component=prefix,compile_path=path):
                    broken=copy.deepcopy(proof);del broken['recipe_files'][path]
                    with self.assertRaisesRegex(ValueError,'recipe inventory'):
                        cpu_wheels.validate_provenance(broken,raw,proof['outputs'])
            for path in ('tools/offline/recipes/wheel_normalize.py','tools/offline/cpu_wheels.py'):
                with self.subTest(component=prefix,normalization_path=path):
                    broken=copy.deepcopy(proof);del broken['normalization']['recipe_files'][path]
                    with self.assertRaisesRegex(ValueError,'normalization.*inventory'):
                        cpu_wheels.validate_provenance(broken,raw,proof['outputs'])

    def test_components_reject_duplicate_ids_overlapping_and_uncovered_outputs(self):
        from unittest.mock import patch
        a={'id':'scientific','proof':{'outputs':[{'name':'numpy'}]},'input_bytes':b'{}'}
        b={'id':'lxml','proof':{'outputs':[{'name':'lxml'}]},'input_bytes':b'{}'}
        packages=[{'name':n,'build_provenance':'proof.json'} for n in ('numpy','lxml')]
        with patch.object(cpu_wheels._contract,'validate_provenance'):
            cpu_wheels.validate_components([a,b],packages)
            for components in ([a,a],[a,{**b,'proof':a['proof']}],[a]):
                with self.assertRaisesRegex(ValueError,'component|overlap|uncovered'):
                    cpu_wheels.validate_components(components,packages)

    def test_selection_replaces_only_the_built_distribution(self):
        original=self.wheel(self.root/'candidate')
        old=original.with_name(original.name.replace('-1qboxcpu',''))
        original.rename(old)
        other=self.root/'candidate'/'other-1.0-py3-none-any.whl'
        with zipfile.ZipFile(other,'w') as z:
            z.writestr('other-1.0.dist-info/METADATA','Name: other\nVersion: 1.0\n')
        cached=self.wheel(self.root/'cache'/'cpu-wheelhouse')
        proof={'outputs':[{'name':'numpy','version':'2.5.3','filename':cached.name,'sha256':hashlib.sha256(cached.read_bytes()).hexdigest()}]}
        cpu_wheels.apply_selection(self.root/'candidate',proof,self.root/'cache')
        self.assertFalse(old.exists())
        self.assertEqual({p.name for p in (self.root/'candidate').glob('*.whl')},{cached.name,other.name})

    def test_reproducibility_compares_actual_bytes(self):
        a=self.wheel(self.root/'a');b=self.wheel(self.root/'b')
        self.assertEqual(cpu_wheels.compare_builds([a],[b])[a.name],hashlib.sha256(a.read_bytes()).hexdigest())
        b=self.wheel(self.root/'b',b'different')
        with self.assertRaisesRegex(ValueError,'reproduc'):
            cpu_wheels.compare_builds([a],[b])


if __name__=='__main__':unittest.main()
