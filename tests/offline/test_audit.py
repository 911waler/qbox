"""Offline audit uses fixed readelf text and synthetic wheel bytes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.offline.audit import (glibc_allowed, parse_readelf, inspect_elf,
    validate_elf, resolve_needed, validate_license_inventory, wheel_inventory)

FIXTURE = '''ELF Header:
  Class:                             ELF64
  Machine:                           Advanced Micro Devices X86-64
Dynamic section at offset 0x100:
 0x0000000000000001 (NEEDED) Shared library: [libblas.so]
 0x000000000000000f (RPATH) Library rpath: [$ORIGIN/../demo.libs]
Version definition section '.gnu.version_d' contains 2 entries:
  0x001c: Rev: 1 Flags: none Index: 2 Cnt: 1 Name: GLIBC_2.38
Version needs section '.gnu.version_r' contains 2 entries:
  0x0010: Name: GLIBC_2.28  Flags: none  Version: 2
  0x0020: Name: GLIBCXX_3.4.25 Flags: none Version: 3
  0x0030: Name: CXXABI_1.3.11 Flags: none Version: 4
Displaying notes found in: .note.gnu.property
      Properties: x86 ISA needed: x86-64-baseline
'''


class AuditTests(unittest.TestCase):
    def test_glibc_comparison_is_numeric(self):
        self.assertTrue(glibc_allowed('GLIBC_2.9', (2, 28)))
        self.assertFalse(glibc_allowed('GLIBC_2.29', (2, 28)))
        self.assertFalse(glibc_allowed('GLIBC_PRIVATE', (2, 28)))

    def test_only_version_needs_not_definitions(self):
        parsed = parse_readelf(FIXTURE)
        self.assertEqual(parsed['version_needs'], ['CXXABI_1.3.11','GLIBCXX_3.4.25','GLIBC_2.28'])
        self.assertEqual(parsed['needed'], ['libblas.so'])
        self.assertEqual(parsed['rpath'], ['$ORIGIN/../demo.libs'])
        self.assertEqual(parsed['isa'], ['x86-64-baseline'])

    def test_readelf_invocation_uses_safe_fixed_arguments(self):
        with patch('tools.offline.audit.subprocess.run') as run:
            run.return_value.stdout = FIXTURE
            self.assertEqual(inspect_elf(Path('demo.so'))['needed'], ['libblas.so'])
            self.assertEqual(run.call_args.args[0], ['/usr/bin/readelf', '-h', '-d', '--version-info', '-n', 'demo.so'])

    def test_rejects_glibc_229_and_required_v2(self):
        for text, problem in [(FIXTURE.replace('GLIBC_2.28','GLIBC_2.29'),'GLIBC_2.29'),
                              (FIXTURE.replace('x86-64-baseline','x86-64-v2'),'ISA'),
                              (FIXTURE.replace('$ORIGIN/../demo.libs','/opt/conda/lib'),'RPATH')]:
            with self.subTest(problem=problem), self.assertRaisesRegex(ValueError, problem):
                validate_elf(parse_readelf(text))

    def test_runpath_and_other_architecture_rejected(self):
        with self.assertRaisesRegex(ValueError, 'RUNPATH'):
            validate_elf(parse_readelf(FIXTURE.replace('(RPATH)', '(RUNPATH)').replace('$ORIGIN/../demo.libs','relative/lib')))
        with self.assertRaisesRegex(ValueError, 'machine'):
            validate_elf(parse_readelf(FIXTURE.replace('Advanced Micro Devices X86-64','AArch64')))

    def test_resolve_needed_requires_loader_search_path(self):
        record = parse_readelf(FIXTURE)
        files = {'site/demo/module.so','site/demo.libs/libblas.so'}
        self.assertEqual(resolve_needed('site/demo/module.so',record,files,{}), {'libblas.so':'site/demo.libs/libblas.so'})
        record['rpath'] = []
        with self.assertRaisesRegex(ValueError, 'unresolved.*libblas'):
            resolve_needed('site/demo/module.so',record,files,{})

    def test_missing_native_license_is_not_hidden_by_package_license(self):
        report = {'components':[{'id':'demo','licenses':['MIT'],'materials':['LICENSE']},
                                {'id':'demo/.libs/libblas.so','licenses':[],'materials':[]}]}
        with self.assertRaisesRegex(ValueError, 'libblas'):
            validate_license_inventory(report)

    def test_spdx_does_not_replace_body_or_source_obligation(self):
        for component in [{'id':'demo','licenses':['MIT'],'materials':[]},
                          {'id':'db','licenses':['Sleepycat'],'materials':['LICENSE'],'unresolved':['source delivery']}]:
            with self.assertRaises(ValueError):
                validate_license_inventory({'components':[component]})

    def test_synthetic_wheel_native_is_separate_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'demo-1.0-py3-none-any.whl'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('demo-1.0.dist-info/METADATA','Name: demo\nVersion: 1.0\nLicense-Expression: MIT\n')
                z.writestr('demo-1.0.dist-info/licenses/LICENSE','Permission is hereby granted '+ 'x'*100)
                z.writestr('demo/.libs/libopenblas.so',b'\x7fELFnot-a-real-elf')
            report=wheel_inventory(path,Path(tmp)/'materials',{})
            self.assertIn('demo/.libs/libopenblas.so',[c['member'] for c in report['components'] if 'member' in c])
            with self.assertRaisesRegex(ValueError,'libopenblas'):
                validate_license_inventory(report)

    def test_duplicate_component_ids_cannot_overwrite_material_map(self):
        component={'id':'duplicate','licenses':['MIT'],'materials':['LICENSE']}
        with self.assertRaisesRegex(ValueError,'duplicate component'):
            validate_license_inventory({'components':[component,component]})

    def test_empty_license_body_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'demo-1.0-py3-none-any.whl'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('demo-1.0.dist-info/METADATA','Name: demo\nVersion: 1.0\n')
                z.writestr('demo-1.0.dist-info/LICENSE','')
            report=wheel_inventory(path,Path(tmp)/'materials',{})
            with self.assertRaises(ValueError):
                validate_license_inventory(report)


class NativeRepairTests(unittest.TestCase):
    @staticmethod
    def newc(name, data, mode=0o100644):
        fields=[0,mode,0,0,1,0,len(data),0,0,0,0,len(name)+1,0]
        header=b'070701'+b''.join(f'{v:08x}'.encode() for v in fields)
        entry=header+name.encode()+b'\0'
        entry+=b'\0'*(-len(entry)%4)
        return entry+data+b'\0'*(-len(data)%4)

    def test_cpio_extracts_regular_files_and_rejects_traversal(self):
        from tools.offline.archive import read_newc
        blob=self.newc('./usr/lib64/libz.so.1.2.11',b'ELF')+self.newc('TRAILER!!!',b'')
        self.assertEqual(read_newc(blob)['usr/lib64/libz.so.1.2.11'],b'ELF')
        with self.assertRaises(ValueError):
            read_newc(self.newc('../../escape',b'x'))

    def test_cpio_truncation_and_duplicate_rejected(self):
        from tools.offline.archive import read_newc
        for data in [b'070701',self.newc('x',b'x')+self.newc('x',b'y')]:
            with self.assertRaises(ValueError):
                read_newc(data)

class AdditionalAuditTests(unittest.TestCase):
    def test_relative_needed_origin_and_inherited_interpreter_rpath(self):
        r=parse_readelf(FIXTURE)
        r['needed']=['$ORIGIN/../lib/libpython.so','libz.so.1']
        r['rpath']=[]
        found=resolve_needed('runtime/python/bin/python',r,{'runtime/python/lib/libpython.so','runtime/python/lib/libz.so.1'}, {}, ('runtime/python/lib',))
        self.assertEqual(found['libz.so.1'],'runtime/python/lib/libz.so.1')
        r['needed']=['$ORIGIN/../../../../etc/passwd']
        with self.assertRaises(ValueError):resolve_needed('runtime/python/bin/python',r,set(),{})

    def test_elf32_is_not_x86_64_abi(self):
        with self.assertRaisesRegex(ValueError,'class'):
            validate_elf(parse_readelf(FIXTURE.replace('ELF64','ELF32')))

    def test_missing_corresponding_sources_fails(self):
        from tools.offline.audit import _component
        c=_component('lgpl-library',{'licenses':['LGPL-2.1-or-later'],'materials':['LICENSE'],'sources':['sources/exact-source.tar.gz']}, {'LICENSE':{'path':'materials/license'}})
        with self.assertRaisesRegex(ValueError,'source material'):
            validate_license_inventory({'components':[c]})


class SupplementalMaterialTests(unittest.TestCase):
    def test_locked_fetch_extracts_exact_body_without_delivering_tool_archive(self):
        import hashlib
        import io
        import tarfile
        from unittest.mock import patch
        from tools.offline.audit import _supplemental_materials
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w:gz') as tar:
            for name,body in [('tool/COPYRIGHT-library.html',b'complete original library notice'),('tool/bin/compiler',b'not delivered')]:
                item=tarfile.TarInfo(name);item.size=len(body);tar.addfile(item,io.BytesIO(body))
        archive=data.getvalue();digest=hashlib.sha256(archive).hexdigest()
        source={'name':'tool-library','version':'exact','source':{'url':'https://official.example/tool.tar.gz','filename':'tool.tar.gz','sha256':digest},'deliver_archive':False,'license_members':['tool/COPYRIGHT-library.html']}
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'cache';output=Path(tmp)/'materials'
            def fetch(url,sha,target):
                self.assertEqual(url,source['source']['url']);self.assertEqual(sha,digest)
                target.mkdir(parents=True);(target/sha).write_bytes(archive)
            with patch('tools.offline.resolve.cache_asset',side_effect=fetch) as download:
                materials=_supplemental_materials(cache,output,[source]);download.assert_called_once()
            self.assertEqual(list(materials),['source-licenses/tool-library/tool/COPYRIGHT-library.html'])
            self.assertEqual(next(output.iterdir()).read_bytes(),b'complete original library notice')
            (cache/'sha256'/digest).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                _supplemental_materials(cache,output,[source])


class SymbolProviderTests(unittest.TestCase):
    def test_cxx_and_glibc_versions_must_be_supplied_by_actual_provider(self):
        from tools.offline.audit import validate_symbol_versions
        record={'version_files':{'libstdc++.so.6':['GLIBCXX_3.4.25','CXXABI_1.3.11']}}
        validate_symbol_versions(record,{'libstdc++.so.6':['GLIBCXX_3.4.25','CXXABI_1.3.11']})
        for versions in [['GLIBCXX_3.4.24','CXXABI_1.3.11'],['GLIBCXX_3.4.25','CXXABI_1.3.10']]:
            with self.assertRaisesRegex(ValueError,'missing'):
                validate_symbol_versions(record,{'libstdc++.so.6':versions})


if __name__ == "__main__":
    unittest.main()
