"""Real root/venv creation probes; runnable only in an explicitly marked container."""
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from installer import transaction
from installer.paths import InstallOptions


@unittest.skipUnless(Path('/.dockerenv').exists()
                     and os.environ.get('QBOX_ACCEPTANCE_CONTAINER') == '1'
                     and os.geteuid() == 0, 'requires isolated root container')
class SystemCreationTests(unittest.TestCase):
    def test_creation_is_safe_before_venv_execution_and_restores_caller_mask(self):
        for caller_mask in (0o000, 0o077):
            with self.subTest(umask=oct(caller_mask)), tempfile.TemporaryDirectory(dir='/opt') as directory:
                parent = Path(directory)
                parent.chmod(0o711)
                wheel = parent / 'unused.whl'
                wheel.write_bytes(b'not reached: stop before pip')
                prefix = parent / 'qbox'
                options = InstallOptions('system', prefix, prefix / 'bin', Path(sys.executable))
                observed = []
                real_run = transaction._run

                def inspect_creation(args, **kwargs):
                    if 'venv' not in args:
                        return real_run(args, **kwargs)
                    mask = os.umask(caller_mask)
                    os.umask(mask)
                    self.assertEqual(mask, 0o022, 'unsafe creation mask before root venv/ensurepip')
                    for path in (prefix, prefix / '.install-lock', prefix / '.install-lock/token',
                                 prefix / '.qbox-install.json'):
                        self.assertFalse(path.stat().st_mode & 0o022, str(path))
                    result = real_run(args, **kwargs)
                    for path in (prefix / 'venv', prefix / 'venv/bin',
                                 prefix / 'venv/pyvenv.cfg', *prefix.glob('venv/lib/python*/site-packages')):
                        mode = stat.S_IMODE(path.stat().st_mode)
                        self.assertFalse(mode & 0o022, str(path))
                        self.assertTrue(mode & 0o004, str(path))
                    observed.append(result)
                    raise RuntimeError('stop after actual venv before pip')

                original_mask = os.umask(caller_mask)
                try:
                    with patch.object(transaction, '_run', side_effect=inspect_creation):
                        with self.assertRaisesRegex(OSError, 'stop after actual venv before pip'):
                            transaction.install(options, wheel=wheel,
                                                wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest())
                    restored = os.umask(caller_mask)
                    self.assertEqual(restored, caller_mask)
                finally:
                    os.umask(original_mask)
                self.assertEqual(len(observed), 1)
                self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o711)
                self.assertFalse((prefix / '.install-lock').exists())


if __name__ == '__main__':
    unittest.main()
