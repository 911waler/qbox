"""Acceptance infrastructure must never turn a failed command into a pass."""
import importlib.util
import io
import json
from pathlib import Path
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
        with self.assertRaises(AssertionError):
            runner.run([sys.executable, '-c', "import sys; print('evidence'); sys.exit(7)"])
        event = json.loads(output.getvalue())
        self.assertEqual(event['returncode'], 7)
        self.assertEqual(event['stdout'], 'evidence\n')

    def test_expected_failure_rejects_success(self):
        module = self.load_harness()
        with self.assertRaises(AssertionError):
            module.Recorder(io.StringIO()).run([sys.executable, '-c', 'pass'], failure=True)

    def test_expected_failure_preserves_stderr(self):
        module = self.load_harness()
        output = io.StringIO()
        result = module.Recorder(output).run(
            [sys.executable, '-c', "import sys; print('diagnostic', file=sys.stderr); sys.exit(2)"], failure=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(output.getvalue())['stderr'], 'diagnostic\n')

    def test_profile_example_requires_actual_printed_commands(self):
        module = self.load_harness()
        example = "( set -C; printf '%s\\n' 'export PATH=/opt/test/bin:\"$PATH\"' > /etc/profile.d/qbox.sh ) &&\n  chmod 0644 /etc/profile.d/qbox.sh"
        self.assertEqual(module.profile_example('intro\n' + example + '\nend'), example)
        with self.assertRaises(AssertionError):
            module.profile_example('no profile example')


if __name__ == '__main__':
    unittest.main()
