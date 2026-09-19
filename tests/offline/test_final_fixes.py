"""Final review regressions at the public maintainer and documented shell boundaries."""
import hashlib
import io
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

def cli(args):
    from tools.offline.__main__ import main
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(args)

class RollbackOwnershipTests(unittest.TestCase):
    def test_actual_documented_transaction_preserves_foreign_objects(self):
        block = re.findall(r'```bash\n(.*?)```', (ROOT/'packaging/offline/README.zh-CN.md').read_text(), re.S)[3]
        modes = ('success','current_file','current_dir','current_unmanaged','current_replaced','lock_replaced','token_replaced','root_replaced','temp_file','temp_dir','temp_symlink_dir','temp_dangling','temp_replaced','temp_retargeted')
        for mode in modes:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                home=Path(tmp); prefix=home/'.local/share/qbox'
                for name in ('old','active'):
                    release=prefix/'releases'/name
                    (release/'metadata').mkdir(parents=True)
                    (release/'metadata/installed.json').write_text('{}')
                release=prefix/'releases/old'; (release/'python/bin').mkdir(parents=True)
                exe=release/'python/bin/python3'
                exe.write_text('#!/bin/sh\ncase "$*" in *smoke.py*) [ -z "${DISPLAY+x}" ] || exit 98;; esac\nexit 0\n'); exe.chmod(0o755)
                marker=prefix/'.qbox-root'; marker.write_text(f'schema_version=1\nuid={os.getuid()}\nprefix={prefix}\n')
                foreign=home/'foreign'; foreign.mkdir(); (foreign/'sentinel').write_text('untouched')
                current=prefix/'current'
                if mode=='current_file':current.write_text('untouched')
                elif mode=='current_dir':current.mkdir(); (current/'sentinel').write_text('untouched')
                else:current.symlink_to(str(foreign) if mode=='current_unmanaged' else 'releases/active')
                code=block.replace("release_id='填写 releases 中保留的完整版本名'", "release_id='old'")
                creation=next(line for line in code.splitlines() if line.startswith('ln -s'))
                before={
                    'current_replaced':'mv "$prefix/current" "$prefix/saved-current"; ln -s releases/active "$prefix/current"',
                    'lock_replaced':'mv "$lock" "$prefix/saved-lock"; mkdir "$lock"; printf foreign > "$lock/owner"',
                    'token_replaced':'printf foreign > "$lock/owner"',
                    'root_replaced':'mv "$prefix/.qbox-root" "$prefix/saved-root"; cp "$prefix/saved-root" "$prefix/.qbox-root"',
                    'temp_file':'printf untouched > "$link"',
                    'temp_dir':'mkdir "$link"; printf untouched > "$link/sentinel"',
                    'temp_symlink_dir':'ln -s "$HOME/foreign" "$link"',
                    'temp_dangling':'ln -s "$HOME/missing" "$link"',
                }.get(mode,'')
                if before:code=code.replace(creation,before+'\n'+creation)
                if mode=='temp_replaced':code=code.replace('link_owned=1','link_owned=1\nmv "$link" "$prefix/saved-temp"; ln -s "releases/$release_id" "$link"')
                if mode=='temp_retargeted':code=code.replace('link_owned=1','link_owned=1\nrm "$link"; ln -s "$HOME/foreign" "$link"')
                env={k:v for k,v in os.environ.items() if not k.startswith('BASH_FUNC_')}; env.update(HOME=str(home),DISPLAY=':0')
                result=subprocess.run(['/bin/bash','--noprofile','--norc','-c',code],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode==0,mode=='success',result.stderr)
                self.assertEqual((foreign/'sentinel').read_text(),'untouched'); self.assertEqual(sorted(p.name for p in foreign.iterdir()),['sentinel'])
                if current.is_symlink():self.assertEqual(os.readlink(current), 'releases/old' if mode=='success' else str(foreign) if mode=='current_unmanaged' else 'releases/active')
                elif current.is_dir():self.assertEqual((current/'sentinel').read_text(),'untouched')
                else:self.assertEqual(current.read_text(),'untouched')
                if mode in ('lock_replaced','token_replaced'):self.assertEqual((prefix/'.install-lock/owner').read_text(),'foreign')
                residues=list(prefix.glob('.rollback.*'))
                if mode.startswith('temp_'):
                    self.assertEqual(len(residues),1)
                    if mode=='temp_file':self.assertEqual(residues[0].read_text(),'untouched')
                    if mode=='temp_dir':self.assertEqual((residues[0]/'sentinel').read_text(),'untouched')

    def test_direct_selfcheck_scopes_display(self):
        block=re.findall(r'```bash\n(.*?)```',(ROOT/'packaging/offline/README.zh-CN.md').read_text(),re.S)[2]
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);release=home/'.local/share/qbox/releases/old';(release/'python/bin').mkdir(parents=True)
            (release.parent.parent/'current').symlink_to('releases/old')
            exe=release/'python/bin/python3';exe.write_text('#!/bin/sh\ncase "$*" in *smoke.py*) [ -z "${DISPLAY+x}" ] || exit 98;; esac\n');exe.chmod(0o755)
            result=subprocess.run(['/bin/bash','--noprofile','--norc','-ec',block],env={'PATH':'/usr/bin:/bin','HOME':str(home),'DISPLAY':':0'},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

class MaterialHandoffTests(unittest.TestCase):
    def test_missing_audit_material_never_acquires(self):
        from tools.offline.audit import _supplemental_materials
        with tempfile.TemporaryDirectory() as tmp, patch('tools.offline.resolve.cache_asset',side_effect=AssertionError('network forbidden')):
            source=dict(name='notice',version='1',source=dict(filename='notice',sha256='a'*64,url='https://example.invalid/notice'))
            with self.assertRaisesRegex(ValueError,'missing.*resolve'):_supplemental_materials(Path(tmp),Path(tmp)/'out',[source])

    def test_explicit_resolution_acquisition_uses_reviewed_hash_and_cache(self):
        from tools.offline import resolve
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'notice';source.write_bytes(b'notice');digest=hashlib.sha256(source.read_bytes()).hexdigest()
            lock=root/'licenses.lock.json';lock.write_text(json.dumps({'sources':[dict(name='notice',source=dict(filename='notice',sha256=digest,url='https://example.invalid/notice'))]}))
            with patch.object(resolve,'urlopen',return_value=io.BytesIO(b'notice')):
                result=resolve.acquire_locked_materials(root/'cache',lock)
            self.assertEqual((root/'cache/sha256'/digest).read_bytes(),b'notice')
            with patch.object(resolve,'urlopen',side_effect=AssertionError('network forbidden')):self.assertEqual(resolve.acquire_locked_materials(root/'cache',lock),result)

    def test_public_promotion_then_real_builder_and_conflicts(self):
        from test_build import BuildTests
        from tools.offline.__main__ import main
        helper=BuildTests(methodName='runTest');helper.setUp()
        try:
            raw=helper.root/'raw-audit';(helper.cache/'audit').rename(raw);(raw/'descriptor.json').unlink()
            self.assertEqual(cli(['audit-promote','--audit',str(raw),'--cache',str(helper.cache)]),0)
            descriptor=json.loads((helper.cache/'audit/descriptor.json').read_text())
            self.assertTrue(all(set(r)=={'path','size','sha256'} for r in descriptor['files'].values()))
            self.assertTrue(helper.build().exists())
            # Existing destinations are never silently overwritten, even identical ones.
            self.assertEqual(cli(['audit-promote','--audit',str(raw),'--cache',str(helper.cache)]),1)
            shutil.rmtree(helper.cache/'audit');(raw/'materials/license').unlink();(raw/'materials/license').symlink_to(helper.source/'LICENSE')
            self.assertEqual(cli(['audit-promote','--audit',str(raw),'--cache',str(helper.cache)]),1)
            self.assertFalse((helper.cache/'audit').exists())
        finally:helper.doCleanups()

class MatrixExitTests(unittest.TestCase):
    def test_failed_platforms_keep_all_reports_and_cli_returns_nonzero(self):
        from tools.offline import matrix
        from tools.offline.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'archive';archive.write_bytes(b'fixture');out=root/'out'
            identity=dict(artifact_sha256='a'*64,manifest_sha256='b'*64,source_commit='c'*40)
            def output(command,**kwargs):
                if command[0]=='git':return 'c'*40 if command[1]=='rev-parse' else (ROOT/'tests/offline/run-target.sh').read_bytes()
                if command[1]=='inspect':return json.dumps([{'HostConfig':{'NetworkMode':'none'}}])
                if command[1]=='image':return '[{}]'
                return 'fixture-container'
            with patch.object(matrix,'verify_candidate',return_value=(identity,archive,None)),patch.object(matrix.subprocess,'check_output',side_effect=output),patch.object(matrix.subprocess,'run',return_value=subprocess.CompletedProcess([],1)):
                self.assertEqual(cli(['matrix','--candidate',str(root/'candidate'),'--output',str(out)]),1)
            self.assertEqual(len(list(out.glob('*/report.json'))),5)

class RuntimeMarkerTests(unittest.TestCase):
    def test_build_closure_uses_actual_patch_for_python_and_implementation(self):
        from test_resolve import ResolveTests
        from tools.offline import resolve
        helper=ResolveTests(methodName='runTest');helper.setUp()
        try:
            root=helper.wheel('builder',requires=['old; python_full_version < "3.12.15"', 'new; implementation_version >= "3.12.15"'])
            old=helper.wheel('old');new=helper.wheel('new')
            for version,wanted in [('3.12.14','old'),('3.12.15','new')]:
                env=resolve.runtime_marker_environment(version)
                packages=resolve.wheel_closure([root,old,new],['builder'],env)
                self.assertEqual({p['name'] for p in packages},{'builder',wanted})
            # This is the production acquisition call site, before packaging exists.
            import inspect
            self.assertIn('runtime_marker_environment(probes["runtime"]["version"])',inspect.getsource(resolve.resolve))
        finally:helper.doCleanups()

class PromotionSafetyTests(unittest.TestCase):
    def test_corrupt_traversal_existing_symlink_and_interrupted_publication(self):
        from test_build import BuildTests
        from tools.offline import build
        for mode in ('corrupt','traversal','destination_symlink','interrupted'):
            with self.subTest(mode=mode):
                helper=BuildTests(methodName='runTest');helper.setUp()
                try:
                    raw=helper.root/'raw';(helper.cache/'audit').rename(raw);(raw/'descriptor.json').unlink()
                    if mode=='corrupt':(raw/'materials/license').write_text('changed')
                    if mode=='traversal':
                        path=raw/'licenses.json';value=json.loads(path.read_text());value['materials'][0]['path']='../outside';path.write_text(json.dumps(value))
                    if mode=='destination_symlink':(helper.cache/'audit').symlink_to(raw)
                    if mode=='interrupted':
                        with patch.object(build.os,'link',side_effect=OSError('interrupted before commit')):
                            self.assertEqual(cli(['audit-promote','--audit',str(raw),'--cache',str(helper.cache)]),1)
                        self.assertTrue((helper.cache/'audit').is_dir())
                        self.assertFalse((helper.cache/'audit/descriptor.json').exists())
                        with self.assertRaises(ValueError):helper.build()
                    else:
                        self.assertEqual(cli(['audit-promote','--audit',str(raw),'--cache',str(helper.cache)]),1)
                        if mode=='destination_symlink':self.assertEqual((helper.cache/'audit').resolve(),raw)
                        else:self.assertFalse((helper.cache/'audit').exists())
                finally:helper.doCleanups()

class PortableTransactionTests(unittest.TestCase):
    def test_transaction_uses_selected_interpreter_even_with_spaces(self):
        import importlib.util
        import sys
        with tempfile.TemporaryDirectory(prefix='qbox interpreter ') as tmp:
            interpreter=Path(tmp)/'chosen python';receipt=Path(tmp)/'invoked'
            import shlex
            interpreter.write_text('#!/bin/sh\nprintf called >> '+shlex.quote(str(receipt))+'\nexec '+shlex.quote(sys.executable)+' "$@"\n');interpreter.chmod(0o755)
            spec=importlib.util.spec_from_file_location('portable_transaction_fixture',ROOT/'tests/offline/test_transaction.py')
            module=importlib.util.module_from_spec(spec)
            with patch.object(sys,'executable',str(interpreter)):spec.loader.exec_module(module)
            helper=module.TransactionTests(methodName='runTest');helper.setUp()
            try:
                result=helper.run_transaction()
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertTrue(receipt.exists(),'transaction ignored selected development interpreter')
            finally:helper.doCleanups()
