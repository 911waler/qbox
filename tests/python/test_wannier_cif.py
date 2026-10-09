"""CIF conversion reuses the SCF wizard without touching existing inputs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_wannier_inputs import SCF


ROOT = Path(__file__).resolve().parents[2]


class CifBridgeTests(unittest.TestCase):
    def setUp(self):
        pseudo_root = tempfile.TemporaryDirectory(prefix='cif test pseudo ')
        self.addCleanup(pseudo_root.cleanup)
        self.pseudo_root = Path(pseudo_root.name)
        self.pseudo_dir = self.pseudo_root / 'QE/SSSP'
        self.pseudo_dir.mkdir(parents=True)
        (self.pseudo_dir / 'Fe.upf').write_text('test pseudo')
        self.scf = SCF.replace("pseudo_dir='../pseudos'", f"pseudo_dir='{self.pseudo_dir}'")
        environment = patch.dict(os.environ, {'QBOX_PSEUDO_ROOT': str(self.pseudo_root)})
        environment.start()
        self.addCleanup(environment.stop)

    def bridge(self):
        self.assertIsNotNone(importlib.util.find_spec('qbox.io.wannier_cif'),
                             'CIF sources need a safe SCF wizard bridge')
        from qbox.io import wannier_cif
        return wannier_cif

    def wizard_result(self, kind='ok', text=None):
        def run(command, **kwargs):
            stage = Path(kwargs['cwd'])
            self.assertNotEqual(stage, stage.parent)
            result = Path(command[-1])
            generated = stage / 'structure.scf.in'
            if kind == 'symlink':
                generated.symlink_to(self.sentinel)
            elif kind == 'outside':
                generated = self.sentinel
            elif kind == 'missing':
                pass
            else:
                generated.write_text(text(stage) if callable(text) else text or self.scf)
            result.write_text('ok\n' + str(generated) + '\n')
            return subprocess.CompletedProcess(command, 0)
        return run

    def test_collision_renames_without_overwriting_existing_or_source(self):
        api = self.bridge()
        with tempfile.TemporaryDirectory(prefix='cif bridge ') as directory:
            root = Path(directory)
            source = root / 'my sample.cif'
            source.write_text('data_original\n')
            old = root / 'my_sample.scf.in'
            old.write_text('existing input')
            before = source.read_bytes()
            with patch.object(api.subprocess, 'run', side_effect=self.wizard_result()):
                result = api.generate_scf_from_cif(source, root,
                                                  input_fn=lambda _: 'other.scf.in', output=lambda _: None)
            self.assertEqual(result, root / 'other.scf.in')
            self.assertEqual(result.read_text(), self.scf)
            self.assertEqual(old.read_text(), 'existing input')
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(list(root.glob('.qbox-wannier-scf-*')))

    def test_collision_can_cancel_and_dangling_symlink_is_never_overwritten(self):
        api = self.bridge()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sample.cif'
            source.write_text('data_original\n')
            target = root / 'sample.scf.in'
            target.symlink_to(root / 'missing')
            with patch.object(api.subprocess, 'run', side_effect=self.wizard_result()):
                self.assertIsNone(api.generate_scf_from_cif(source, root,
                                                            input_fn=lambda _: '', output=lambda _: None))
            self.assertTrue(target.is_symlink())
            self.assertFalse((root / 'missing').exists())
            self.assertFalse(list(root.glob('.qbox-wannier-scf-*')))

    def test_invalid_or_untrusted_wizard_outputs_are_not_published(self):
        api = self.bridge()
        for kind, text in [('symlink', SCF), ('outside', SCF), ('missing', SCF),
                           ('ok', SCF.replace("calculation = 'scf'", "calculation = 'relax'")),
                           ('ok', 'invalid output')]:
            with self.subTest(kind=kind, text=text), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / 'sample.cif'
                source.write_text('data_original\n')
                self.sentinel = root / 'sentinel.in'
                self.sentinel.write_text(SCF)
                with patch.object(api.subprocess, 'run', side_effect=self.wizard_result(kind, text)):
                    with self.assertRaises((ValueError, OSError)):
                        api.generate_scf_from_cif(source, root, output=lambda _: None)
                self.assertFalse((root / 'sample.scf.in').exists())
                self.assertEqual(self.sentinel.read_text(), SCF)
                self.assertFalse(list(root.glob('.qbox-wannier-scf-*')))

    def test_late_output_collision_cannot_clobber_another_writer(self):
        api = self.bridge()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sample.cif'
            source.write_text('data_original\n')
            link = os.link
            def concurrent_link(src, dst, **kwargs):
                Path(dst).write_text('concurrent input')
                return link(src, dst, **kwargs)
            with patch.object(api.subprocess, 'run', side_effect=self.wizard_result()), \
                 patch.object(api.os, 'link', side_effect=concurrent_link):
                self.assertIsNone(api.generate_scf_from_cif(source, root,
                                                            input_fn=lambda _: '', output=lambda _: None))
            self.assertEqual((root / 'sample.scf.in').read_text(), 'concurrent input')

    def test_unconfigured_pseudo_root_prompts_retries_and_only_sets_child_environment(self):
        api = self.bridge()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sample.cif'
            source.write_text('data_original\n')
            answers = iter([str(root / 'missing'), '\0', str(root), os.path.relpath(self.pseudo_root)])
            messages = []
            with patch.dict(os.environ, {'QBOX_PSEUDO_ROOT': ''}), \
                 patch.object(api.subprocess, 'run', side_effect=self.wizard_result()) as run:
                result = api.generate_scf_from_cif(source, root, input_fn=lambda _: next(answers), output=messages.append)
                self.assertEqual(os.environ['QBOX_PSEUDO_ROOT'], '')
            self.assertEqual(run.call_args.kwargs['env']['QBOX_PSEUDO_ROOT'], str(self.pseudo_root))
            self.assertTrue(result.is_file())
            self.assertIn('QE/SSSP', '\n'.join(messages))
            self.assertIn('PWmat/NCPP-SG15-PBE', '\n'.join(messages))
            self.assertGreaterEqual(len(messages), 3)

    def test_unconfigured_pseudo_root_can_cancel_before_starting_wizard(self):
        api = self.bridge()
        for answer in ('', 'b'):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / 'sample.cif'; source.write_text('data_original\n')
                with patch.dict(os.environ, {'QBOX_PSEUDO_ROOT': ''}), \
                     patch.object(api.subprocess, 'run') as run:
                    result = api.generate_scf_from_cif(source, root, input_fn=lambda _: answer, output=lambda _: None)
                self.assertIsNone(result)
                run.assert_not_called()
                self.assertEqual(list(root.iterdir()), [source])

    def test_missing_pseudo_and_paths_inside_stage_are_not_published(self):
        api = self.bridge()
        changes = [lambda stage: self.scf.replace('Fe.upf', 'missing.UPF'),
                   lambda stage: self.scf.replace(str(self.pseudo_dir), str(stage)),
                   lambda stage: self.scf.replace("outdir='./scratch ! / data'", f"outdir='{stage}/tmp'"),
                   lambda stage: self.scf.replace("wfcdir='./wfc'", f"wfcdir='{stage}/wfc'")]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / 'sample.cif'; source.write_text('data_original\n')
                with patch.object(api.subprocess, 'run', side_effect=self.wizard_result(text=change)):
                    with self.assertRaisesRegex(ValueError, '赝势|暂存'):
                        api.generate_scf_from_cif(source, root, output=lambda _: None)
                self.assertFalse(list(root.glob('*.scf.in')))

    def test_python_executable_preserves_bare_commands_and_virtual_environment_links(self):
        api = self.bridge()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sample.cif'; source.write_text('data_original\n')
            interpreter = root / 'venv/bin/python3'
            interpreter.parent.mkdir(parents=True)
            interpreter.symlink_to(sys.executable)
            linked_bin = root / 'linked-bin'
            linked_bin.symlink_to(interpreter.parent, target_is_directory=True)
            for configured, expected in [('python3', 'python3'),
                                         (os.path.relpath(interpreter), str(interpreter))]:
                with self.subTest(configured=configured), \
                     patch.dict(os.environ, {'QBOX_PYTHON': configured, 'PATH': os.path.relpath(linked_bin)}), \
                     patch.object(api.subprocess, 'run', side_effect=self.wizard_result()) as run:
                    published = api.generate_scf_from_cif(source, root, output=lambda _: None)
                    published.unlink()
                    self.assertEqual(run.call_args.kwargs['env']['QBOX_PYTHON'], expected)
                    self.assertEqual(run.call_args.kwargs['env']['PATH'], str(linked_bin))

    def run_real_wizard(self, root, answer, fail=False, relative_environment=False):
        self.bridge()
        source = root / 'my sample.cif'
        source.write_bytes((ROOT / 'tests/fixtures/structures/water.cif').read_bytes())
        tools = root / 'tools'; tools.mkdir()
        multiwfn = tools / 'Multiwfn'
        multiwfn.write_text('#!/usr/bin/env python3\nimport os, pathlib, shutil, sys\n'
                            'lines = sys.stdin.read().splitlines()\n'
                            'if os.environ.get("MOCK_FAIL"): sys.exit(7)\n'
                            'shutil.copyfile(os.environ["STRUCTURE_FIXTURE"], lines[3])\n')
        multiwfn.chmod(0o755)
        for name in ('pw.x', 'pw2wannier90.x', 'wannier90.x'):
            binary = tools / name
            binary.write_text('#!/bin/sh\nprintf executed > "$FORBIDDEN_EXECUTION"\nexit 9\n')
            binary.chmod(0o755)
        pseudo = root / 'pseudo'
        (pseudo / 'QE/SSSP').mkdir(parents=True)
        for name in ('H.UPF', 'O.UPF'):
            (pseudo / 'QE/SSSP' / name).write_text('test pseudo')
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'QBOX_PYTHON': sys.executable,
               'QBOX_MULTIWFN_HOME': str(tools), 'QBOX_PSEUDO_ROOT': str(pseudo),
               'PATH': str(tools) + os.pathsep + os.environ['PATH'],
               'STRUCTURE_FIXTURE': str(ROOT / 'tests/fixtures/qe-inputs/water_QE.tmp'),
               'FORBIDDEN_EXECUTION': str(root / 'ran-calculation'),
               'NONINTERACTIVE_PWIN': '1', 'PRESET_RTASK': 'bands', 'QBOX_INPUT_MENU_TIMEOUT': '1'}
        if fail:
            env['MOCK_FAIL'] = '1'
        else:
            env.pop('MOCK_FAIL', None)
        if relative_environment:
            env['QBOX_MULTIWFN_HOME'] = 'tools'
            env['QBOX_PSEUDO_ROOT'] = 'pseudo'
            env['PATH'] = os.environ['PATH']
        script = ('import json, pathlib, sys\n'
                  'from qbox.io.wannier_cif import generate_scf_from_cif\n'
                  'before = pathlib.Path.cwd()\n'
                  'result = generate_scf_from_cif(sys.argv[1])\n'
                  'print("RESULT=" + json.dumps({"path":str(result) if result else None, '
                  '"same_cwd":before == pathlib.Path.cwd()}))\n')
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        result = subprocess.run([sys.executable, '-c', script, str(source)], cwd=root,
                                env=env, input=answer, capture_output=True, text=True, timeout=20)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertFalse((root / 'ran-calculation').exists())
        self.assertFalse(list(root.glob('.qbox-wannier-scf-*')))
        return result

    def test_real_legacy_wizard_generates_only_scf_in_caller_directory(self):
        from qbox.io.wannier_inputs import parse_qe
        with tempfile.TemporaryDirectory(prefix='cif actual ') as directory:
            root = Path(directory)
            result = self.run_real_wizard(root, '0\n')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith('RESULT=')))
            self.assertTrue(payload['same_cwd'])
            generated = Path(payload['path'])
            self.assertEqual(generated.parent, root)
            qe = parse_qe(generated.read_text())
            self.assertEqual(qe.get('control', 'calculation'), 'scf')
            self.assertEqual(qe.outdir, './tmp')
            self.assertEqual(qe.nat, 3)
            self.assertEqual(len(list(root.glob('*.scf.in'))), 1)

    def test_real_legacy_wizard_cancel_is_none_and_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_real_wizard(root, '14\n')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"path": null', result.stdout)
            self.assertFalse(list(root.glob('*.scf.in')))

    def test_relative_environment_paths_keep_the_callers_meaning(self):
        from qbox.io.wannier_inputs import parse_qe
        with tempfile.TemporaryDirectory(prefix='cif relative ') as directory:
            root = Path(directory)
            result = self.run_real_wizard(root, '0\n', relative_environment=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            qe = parse_qe((root / 'my_sample.scf.in').read_text())
            self.assertEqual(qe.pseudo_dir, str(root / 'pseudo/QE/SSSP'))

    def test_real_legacy_generation_failure_is_an_error_not_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_real_wizard(root, '', fail=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('失败', result.stderr)
            self.assertFalse(list(root.glob('*.scf.in')))


if __name__ == '__main__':
    unittest.main()
