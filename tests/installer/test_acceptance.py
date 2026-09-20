"""Acceptance infrastructure must never turn a failed command into a pass."""
import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


class AcceptanceHarnessTests(unittest.TestCase):
    def load_harness(self):
        path = Path(__file__).with_name('run-acceptance.py')
        self.assertTrue(path.exists(), 'executable acceptance harness is missing')
        spec = importlib.util.spec_from_file_location('qbox_acceptance', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_failed_command_is_recorded_and_rejected(self):
        module = self.load_harness()
        output = io.StringIO()
        runner = module.Recorder(output)
        with self.assertRaises(module.AcceptanceFailure):
            runner.run([sys.executable, '-c', "import sys; print('evidence'); sys.exit(7)"])
        event = json.loads(output.getvalue())
        self.assertEqual(event['returncode'], 7)
        self.assertEqual(event['stdout'], 'evidence\n')

    def test_expected_failure_rejects_success(self):
        module = self.load_harness()
        with self.assertRaises(module.AcceptanceFailure):
            module.Recorder(io.StringIO()).run([sys.executable, '-c', 'pass'], failure=True)

    def test_expected_failure_preserves_stderr(self):
        module = self.load_harness()
        output = io.StringIO()
        result = module.Recorder(output).run(
            [sys.executable, '-c', "import sys; print('diagnostic', file=sys.stderr); sys.exit(2)"], failure=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(output.getvalue())['stderr'], 'diagnostic\n')

    def test_failure_gate_survives_both_optimization_switches(self):
        path = str(Path(__file__).with_name('run-acceptance.py'))
        loader = ("import importlib.util,io,sys; "
                  f"s=importlib.util.spec_from_file_location('acceptance', {path!r}); "
                  "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); ")
        for flags, environment in ((['-O'], {}), ([], {'PYTHONOPTIMIZE': '1'})):
            for code, expected_failure in (("import sys; sys.exit(7)", False), ('pass', True)):
                with self.subTest(flags=flags, environment=environment, code=code):
                    invocation = (loader + f"m.Recorder(io.StringIO()).run([sys.executable, '-c', {code!r}], "
                                  f"failure={expected_failure!r})")
                    result = subprocess.run([sys.executable, *flags, '-c', invocation],
                                            env=dict(os.environ, **environment), text=True, capture_output=True)
                    self.assertNotEqual(result.returncode, 0, 'optimization bypassed the failure gate')
                    self.assertIn('Unexpected exit', result.stderr)

    def test_optimized_outer_gate_rejects_failed_missing_and_duplicate_results(self):
        path = str(Path(__file__).with_name('run-acceptance.py'))
        loader = ("import importlib.util; "
                  f"s=importlib.util.spec_from_file_location('acceptance', {path!r}); "
                  "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); ")
        success = {'status': 'passed'}
        for returncode, results in ((7, [success]), (0, []), (0, [success, success]),
                                    (0, [{'status': 'failed'}])):
            with self.subTest(returncode=returncode, results=results):
                result = subprocess.run([sys.executable, '-O', '-c',
                                         loader + f'm.completed_result({returncode!r}, {results!r})'],
                                        text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Container did not report exactly one successful result', result.stderr)
        self.assertEqual(self.load_harness().completed_result(0, [success]), success)

    def test_no_optimizer_removable_checks_in_harness_or_embedded_python(self):
        source = Path(__file__).with_name('run-acceptance.py').read_text()
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(tree)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                try:
                    embedded = ast.parse(node.value)
                except SyntaxError:
                    continue
                self.assertFalse(any(isinstance(child, ast.Assert) for child in ast.walk(embedded)), node.value)

    def test_profile_example_requires_actual_printed_commands(self):
        module = self.load_harness()
        example = "( set -C; printf '%s\\n' 'export PATH=/opt/test/bin:\"$PATH\"' > /etc/profile.d/qbox.sh ) &&\n  chmod 0644 /etc/profile.d/qbox.sh"
        self.assertEqual(module.profile_example('intro\n' + example + '\nend'), example)
        with self.assertRaises(module.AcceptanceFailure):
            module.profile_example('no profile example')


if __name__ == '__main__':
    unittest.main()
