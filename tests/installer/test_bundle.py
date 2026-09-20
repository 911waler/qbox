"""Build and execute the actual lightweight archive outside the source tree."""
import hashlib
import json
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'tools/build-lightweight-installer.py'


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='qbox-bundle-tests-')
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.base = Path(cls.workspace.name)
        cls.python = Path(os.environ.get('QBOX_TEST_PYTHON', sys.executable)).absolute()
        builder = os.environ.get('QBOX_TEST_BUILD_PYTHON', str(cls.python))
        result = subprocess.run([builder, '-m', 'build', '--wheel', '--no-isolation',
                                 '--outdir', str(cls.base / 'wheel'), str(ROOT)],
                                text=True, capture_output=True)
        (cls.base / 'wheel-build.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.wheel = next((cls.base / 'wheel').glob('*.whl'))
        assert BUILD.is_file(), 'lightweight builder is missing'
        result = subprocess.run([str(cls.python), str(BUILD), '--wheel', str(cls.wheel),
                                 '--output', str(cls.base / 'dist')], text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.archive = next((cls.base / 'dist').glob('*.tar.gz'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        with tarfile.open(self.archive) as archive:
            archive.extractall(self.work, filter='data')
        self.bundle = next(self.work.glob('qbox-*'))
        self.prefix = self.work / "中文 user's app"

    def run_cli(self, *args, env=None):
        return subprocess.run(['/bin/bash', str(self.bundle / 'install.sh'), *args],
                              cwd=self.work, env=env, text=True, capture_output=True)

    def reject(self, *args, message):
        result = self.run_cli(*args)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertFalse(self.prefix.exists())

    def build(self, wheel=None, output=None):
        return subprocess.run([str(self.python), str(BUILD), '--wheel', str(wheel or self.wheel),
                               '--output', str(output or self.work / 'dist')],
                              cwd=self.work, text=True, capture_output=True)

    def test_archive_has_only_allowed_payload_and_valid_digests(self):
        with tarfile.open(self.archive) as archive:
            members = archive.getmembers()
        names = [m.name for m in members]
        self.assertTrue(any(n.endswith('/install.sh') for n in names))
        self.assertEqual(sum(n.endswith('.whl') for n in names), 1)
        self.assertFalse(any('Multiwfn' in n or 'wheelhouse/' in n or 'runtime/' in n or 'third_party/' in n for n in names))
        self.assertEqual(len({n.split('/')[0] for n in names}), 1)
        self.assertTrue(all(m.isfile() and m.mtime == 0 and m.uid == m.gid == 0 for m in members))
        digest, filename = Path(str(self.archive) + '.sha256').read_text().strip().split('  ')
        self.assertEqual(filename, self.archive.name)
        self.assertEqual(digest, hashlib.sha256(self.archive.read_bytes()).hexdigest())
        listed = set()
        for line in (self.bundle / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ')
            listed.add(name)
            self.assertEqual(digest, hashlib.sha256((self.bundle / name).read_bytes()).hexdigest())
        self.assertEqual(listed, {str(p.relative_to(self.bundle)) for p in self.bundle.rglob('*') if p.is_file()} - {'SHA256SUMS'})

    def test_build_is_deterministic_and_does_not_replace_different_output(self):
        self.assertEqual(self.build().returncode, 0)
        built = next((self.work / 'dist').glob('*.tar.gz'))
        self.assertEqual(built.read_bytes(), self.archive.read_bytes())
        self.assertEqual(self.build().returncode, 0)
        built.write_bytes(b'previous archive')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(built.read_bytes(), b'previous archive')

    def test_builder_rejects_wrong_or_duplicate_metadata_and_symlink(self):
        with zipfile.ZipFile(self.wheel) as source:
            original = [(i.filename, source.read(i)) for i in source.infolist()]
        for case in ('wrong-name', 'bad-version', 'duplicate', 'missing'):
            with self.subTest(case=case):
                target_dir = self.work / case
                target_dir.mkdir()
                wheel = target_dir / self.wheel.name
                with zipfile.ZipFile(wheel, 'w') as target:
                    for name, content in original:
                        if name.endswith('.dist-info/METADATA'):
                            if case == 'missing':
                                continue
                            if case == 'wrong-name':
                                content = content.replace(b'Name: qbox', b'Name: unrelated')
                            if case == 'bad-version':
                                content = content.replace(b'Version: 0.1.0', b'Version: ../../bad')
                            if case == 'duplicate':
                                target.writestr('other-1.0.dist-info/METADATA', content)
                        target.writestr(name, content)
                result = self.build(wheel)
                self.assertNotEqual(result.returncode, 0, case)
                self.assertFalse((self.work / 'dist').exists())
        link = self.work / 'link.whl'
        link.symlink_to(self.wheel)
        self.assertNotEqual(self.build(link).returncode, 0)

    def test_help_needs_no_python_and_creates_nothing(self):
        before = sorted(str(p.relative_to(self.work)) for p in self.work.rglob('*'))
        result = self.run_cli('--help', env=dict(os.environ, PATH='/nonexistent'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--system', result.stdout)
        self.assertIn('--user', result.stdout)
        self.assertEqual(before, sorted(str(p.relative_to(self.work)) for p in self.work.rglob('*')))

    def test_argument_errors_are_not_lost(self):
        cases = [(['--unknown'], 'unrecognized'), (['--prefix'], 'requires a value'),
                 (['--python', '--user'], 'requires a value'),
                 (['--prefix', 'one', '--prefix', 'two'], 'only once'),
                 (['--python=' + str(self.python), '--python', str(self.python)], 'only once'),
                 (['--user', '--system'], 'only once'),
                 (['--prefix', ''], 'must not be empty')]
        for args, message in cases:
            with self.subTest(args=args):
                self.reject(*args, message=message)

    def test_wheel_tampering_fails_before_prefix_creation(self):
        wheel = next((self.bundle / 'packages').glob('*.whl'))
        wheel.write_bytes(wheel.read_bytes() + b'tampered')
        self.reject('--user', '--python', str(self.python), '--prefix', str(self.prefix), message='SHA256')

    def test_extra_wheel_and_extra_files_are_rejected_even_when_listed(self):
        for name in ('packages/extra.whl', 'unexpected', 'installer/extra.py'):
            with self.subTest(name=name):
                extra = self.bundle / name
                extra.write_bytes(b'extra')
                sums = self.bundle / 'SHA256SUMS'
                original = sums.read_text()
                sums.write_text(original + hashlib.sha256(b'extra').hexdigest() + '  ' + name + '\n')
                self.reject('--user', '--python', str(self.python), '--prefix', str(self.prefix), message='file list')
                extra.unlink()
                sums.write_text(original)

    def test_duplicate_manifest_and_symlink_payload_are_rejected(self):
        sums = self.bundle / 'SHA256SUMS'
        original = sums.read_text()
        sums.write_text(original + original.splitlines()[0] + '\n')
        self.reject('--user', '--python', str(self.python), '--prefix', str(self.prefix), message='duplicate')
        sums.write_text(original)
        guide = self.bundle / 'README.zh-CN.md'
        outside = self.work / 'guide'
        guide.rename(outside)
        guide.symlink_to(outside)
        self.reject('--user', '--python', str(self.python), '--prefix', str(self.prefix), message='regular file')

    def test_manifest_requires_every_file_and_rejects_unsafe_paths(self):
        sums = self.bundle / 'SHA256SUMS'
        original = sums.read_text()
        for changed in (original.split('\n', 1)[1],
                        original + '0' * 64 + '  ../outside\n',
                        original.replace('  LICENSE', '  ./LICENSE'),
                        original + 'invalid line\n'):
            with self.subTest(manifest=changed[-80:]):
                sums.write_text(changed)
                self.reject('--user', '--python', str(self.python), '--prefix', str(self.prefix), message='SHA256SUMS')
        sums.write_text(original)
        (self.bundle / 'LICENSE').unlink()
        self.reject('--user', '--python', str(self.python), '--prefix', str(self.prefix), message='file list')

    def test_runtime_checks_wheel_identity_even_with_matching_hash(self):
        wheel = next((self.bundle / 'packages').glob('*.whl'))
        with zipfile.ZipFile(wheel) as archive:
            contents = [(item.filename, archive.read(item)) for item in archive.infolist()]
        with zipfile.ZipFile(wheel, 'w') as archive:
            for name, data in contents:
                if name.endswith('.dist-info/METADATA'):
                    data = data.replace(b'Name: qbox', b'Name: unrelated')
                archive.writestr(name, data)
        sums = self.bundle / 'SHA256SUMS'
        lines = sums.read_text().splitlines()
        sums.write_text('\n'.join(hashlib.sha256(wheel.read_bytes()).hexdigest() + '  packages/' + wheel.name
                                  if line.endswith('  packages/' + wheel.name) else line for line in lines) + '\n')
        self.reject('--user', '--python', str(self.python), '--prefix', str(self.prefix), message='METADATA Name')

    def test_system_path_example_quotes_shell_metacharacters_and_does_not_overwrite(self):
        from installer.__main__ import print_path_guidance
        stream = io.StringIO()
        bin_dir = self.work / "中文 user's $literal commands"
        with contextlib.redirect_stdout(stream):
            print_path_guidance(bin_dir / 'qbox', mode='system')
        output = stream.getvalue().splitlines()
        profile = self.work / 'profile.sh'
        start = next(i for i, line in enumerate(output) if line.startswith('( set -C;'))
        command = '\n'.join(output[start:start + 2]).replace('/etc/profile.d/qbox.sh', str(profile))
        result = subprocess.run(['/bin/bash', '-c', command], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(['/bin/bash', '-c', '. "$1"; printf "%s\\n" "$PATH"', '_', str(profile)],
                                env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), str(bin_dir) + ':/usr/bin:/bin')
        profile.write_text('existing profile')
        profile.chmod(0o600)
        result = subprocess.run(['/bin/bash', '-c', command], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(profile.read_text(), 'existing profile')
        self.assertEqual(profile.stat().st_mode & 0o777, 0o600)

    def test_bare_python_name_uses_path_selection_not_cwd(self):
        selected_dir = self.work / "python commands"
        selected_dir.mkdir()
        selected = selected_dir / "chosen-python"
        selected.symlink_to(self.python)
        local = self.work / "chosen-python"
        local.write_text("#!/bin/sh\nexit 91\n")
        local.chmod(0o755)
        result = self.run_cli('--user', '--prefix', str(self.prefix), '--python=chosen-python',
                             env=dict(os.environ, PATH=str(selected_dir) + ':' + os.environ['PATH']))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads((self.prefix / '.qbox-install.json').read_text())
        self.assertEqual(record['python'], str(selected))

    def test_extracted_bundle_installs_with_real_pip_and_preserves_relative_paths(self):
        python_alias = self.work / "python 中文's"
        python_alias.symlink_to(self.python)
        result = self.run_cli('--prefix', self.prefix.name, '--user', '--python', './' + python_alias.name,
                              env=dict(os.environ, QBOX_PYTHON='/nonexistent/obsolete', PYTHONPATH='/nonexistent'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        entry = self.prefix / 'bin/qbox'
        self.assertTrue(entry.is_file())
        record = json.loads((self.prefix / '.qbox-install.json').read_text())
        self.assertEqual(record['wheel_sha256'], hashlib.sha256(self.wheel.read_bytes()).hexdigest())
        self.assertEqual(record['state'], 'ready')
        self.assertFalse((self.bundle / 'installer/__pycache__').exists())
        path_line = next(line for line in result.stdout.splitlines() if line.startswith('export PATH='))
        check = subprocess.run(['/bin/bash', '-c', path_line + '\ncommand -v qbox\nqbox --list'],
                               cwd=self.work, text=True, capture_output=True,
                               env=dict(os.environ, QBOX_PYTHON='/obsolete', PATH='/usr/bin:/bin'))
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(check.stdout.splitlines()[0], str(entry))
        self.assertIn('cif-to-vasp', check.stdout)


if __name__ == '__main__':
    unittest.main()
