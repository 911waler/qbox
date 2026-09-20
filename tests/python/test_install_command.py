"""Exercise persistent commands in a real, inactive Python virtual environment."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv

ROOT = Path(__file__).resolve().parents[2]


class InstallCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="qbox 中文 ' install ")
        cls.base = Path(cls.temp.name)
        cls.venv = cls.base / "python environment"
        venv.EnvBuilder(with_pip=False, symlinks=True).create(cls.venv)
        cls.python = cls.venv / 'bin/python'
        site = subprocess.check_output([str(cls.python), '-c',
                                      'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True).strip()
        shutil.copytree(ROOT / 'src/qbox', Path(site) / 'qbox',
                        ignore=shutil.ignore_patterns('__pycache__'))
        cls.env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('QBOX_', 'BASH_FUNC_', '_QBOX_'))
                   and k not in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX')}
        cls.env['PATH'] = '/usr/bin:/bin'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_install(self, directory):
        return subprocess.run([str(self.python), '-m', 'qbox.install', '--bin-dir', str(directory)],
                              cwd=self.base, env=self.env, text=True, capture_output=True)

    def test_command_runs_without_activation_and_pins_venv(self):
        directory = self.base / 'user bin'
        result = self.run_install(directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        env = dict(self.env, PATH=str(directory)+':/usr/bin:/bin',
                   QBOX_PYTHON='/missing/old-python', QBOX_SHARED_ROOT='/missing/shared')
        result = subprocess.run(['qbox', '--list'], cwd=self.base, env=env,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('cif-to-vasp', result.stdout)
        # Resolving the interpreter symlink would lose this venv's installed qbox.
        self.assertNotEqual(self.python, self.python.resolve())

    def test_repeat_install_keeps_same_file(self):
        directory = self.base / 'repeat'
        first = self.run_install(directory)
        self.assertEqual(first.returncode, 0, first.stderr)
        inode = (directory/'qbox').stat().st_ino
        second = self.run_install(directory)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual((directory/'qbox').stat().st_ino, inode)

    def test_no_reuse_preserves_even_identical_existing_command(self):
        directory = self.base / 'exclusive'
        self.assertEqual(self.run_install(directory).returncode, 0)
        entry = directory / 'qbox'
        content, inode = entry.read_bytes(), entry.stat().st_ino
        result = subprocess.run([str(self.python), '-m', 'qbox.install',
                                 '--bin-dir', str(directory), '--no-reuse'],
                                cwd=self.base, env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exists', result.stderr)
        self.assertEqual(entry.read_bytes(), content)
        self.assertEqual(entry.stat().st_ino, inode)

    def test_foreign_file_and_symlinks_are_preserved(self):
        for kind in ('file', 'symlink', 'dangling', 'directory'):
            with self.subTest(kind=kind):
                directory=self.base / kind
                directory.mkdir()
                target=directory/'qbox'
                foreign=directory/'foreign'
                foreign.write_text('sentinel')
                if kind=='file':target.write_text('existing command')
                elif kind=='directory':target.mkdir()
                else:target.symlink_to(foreign if kind=='symlink' else directory/'missing')
                inode=target.lstat().st_ino
                result=self.run_install(directory)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('already exists', result.stderr)
                self.assertEqual(target.lstat().st_ino, inode)
                self.assertEqual(foreign.read_text(), 'sentinel')

    def test_missing_environment_has_actionable_error(self):
        directory=self.base/'missing-environment'
        result=self.run_install(directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        hidden=self.python.with_name('python.hidden')
        self.python.rename(hidden)
        try:
            result=subprocess.run([str(directory/'qbox'), '--help'], env=self.env,
                                  text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Python environment is unavailable', result.stderr)
        finally:hidden.rename(self.python)
