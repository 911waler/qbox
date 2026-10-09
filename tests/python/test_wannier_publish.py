"""Current-directory publication must never consume a source or an old result."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock


class PublishTests(unittest.TestCase):
    def setUp(self):
        from qbox.io import wannier_publish
        self.api = wannier_publish
        self.tmp = tempfile.TemporaryDirectory(prefix='qbox 中文 space ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_cancel_and_backup_preserve_old_input_and_result(self):
        old = self.root / 'si.win'
        old.write_text('old')
        (self.root / 'si.chk').write_bytes(b'checkpoint')
        files = {'si.win': 'new', 'si.pw2wan': 'interface'}
        expected = self.api.snapshot(files, self.root)
        with self.assertRaises(FileExistsError):
            self.api.publish(files, self.root, expected=expected)
        self.assertEqual(old.read_text(), 'old')
        (self.root / 'si.win.bak').write_text('legacy backup')
        (self.root / 'bak').mkdir()
        (self.root / 'bak/si.win.bak').write_text('older')
        written = self.api.publish(files, self.root, conflict='backup', expected=expected)
        self.assertEqual(len(written), 2)
        self.assertEqual(old.read_text(), 'new')
        self.assertEqual((self.root / 'si.win.bak').read_text(), 'legacy backup')
        self.assertEqual((self.root / 'bak/si.win.bak').read_text(), 'older')
        self.assertTrue((self.root / 'bak/si.win.bak.1').is_file())
        self.assertEqual((self.root / 'bak/si.win.bak.1').read_text(), 'old')
        self.api.publish({'si.win': 'newest'}, self.root, conflict='backup')
        self.assertEqual((self.root / 'bak/si.win.bak.2').read_text(), 'new')
        self.assertFalse((self.root / 'si.win.bak.1').exists())
        self.assertEqual((self.root / 'si.chk').read_bytes(), b'checkpoint')

    def test_first_backup_creates_bak_only_when_overwriting(self):
        self.api.publish({'si.win': 'first'}, self.root, conflict='backup')
        self.assertFalse((self.root / 'bak').exists())
        self.api.publish({'si.win': 'second'}, self.root, conflict='backup')
        self.assertTrue((self.root / 'bak/si.win.bak').is_file())
        self.assertEqual((self.root / 'bak/si.win.bak').read_text(), 'first')
        self.assertFalse((self.root / 'si.win.bak').exists())

    def test_bak_file_or_symlink_is_rejected_without_touching_external_files(self):
        for kind in ('file', 'symlink', 'dangling'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'si.win').write_text('old')
                with tempfile.TemporaryDirectory() as external:
                    outside = Path(external)
                    (outside / 'sentinel').write_text('untouched')
                    backup = root / 'bak'
                    if kind == 'file':
                        backup.write_text('not a directory')
                    else:
                        backup.symlink_to(outside if kind == 'symlink' else outside / 'absent')
                    with self.assertRaisesRegex(ValueError, 'bak'):
                        self.api.publish({'si.pw2wan': 'new', 'si.win': 'replacement'}, root, conflict='backup')
                    self.assertEqual((root / 'si.win').read_text(), 'old')
                    self.assertFalse((root / 'si.pw2wan').exists())
                    self.assertEqual(list(outside.iterdir()), [outside / 'sentinel'])
                    self.assertEqual((outside / 'sentinel').read_text(), 'untouched')

    def test_backup_filename_symlink_is_not_followed_or_overwritten(self):
        (self.root / 'si.win').write_text('old')
        (self.root / 'bak').mkdir()
        external = self.root / 'keep.txt'
        external.write_text('untouched')
        (self.root / 'bak/si.win.bak').symlink_to(external)
        self.api.publish({'si.win': 'new'}, self.root, conflict='backup')
        self.assertTrue((self.root / 'bak/si.win.bak').is_symlink())
        self.assertTrue((self.root / 'bak/si.win.bak.1').is_file())
        self.assertEqual((self.root / 'bak/si.win.bak.1').read_text(), 'old')
        self.assertEqual(external.read_text(), 'untouched')

    def test_bak_replaced_during_backup_never_writes_through_external_symlink(self):
        (self.root / 'si.win').write_text('old')
        backup = self.root / 'bak'
        backup.mkdir()
        original_open = self.api.os.open
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external)
            replaced = False
            def replace_directory(path, flags, *args, **kwargs):
                nonlocal replaced
                if str(path).endswith('si.win.bak') and not replaced:
                    replaced = True
                    backup.rename(self.root / 'saved-bak')
                    backup.symlink_to(outside)
                return original_open(path, flags, *args, **kwargs)
            with mock.patch.object(self.api.os, 'open', side_effect=replace_directory):
                with self.assertRaisesRegex(ValueError, 'bak.*变化'):
                    self.api.publish({'si.win': 'new'}, self.root, conflict='backup')
            self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual((self.root / 'si.win').read_text(), 'old')

    def test_detects_edits_after_preview_without_touching_any_target(self):
        (self.root / 'si.win').write_text('old')
        files = {'si.win': 'new', 'si.pw2wan': 'interface'}
        expected = self.api.snapshot(files, self.root)
        (self.root / 'si.win').write_text('other user change')
        with self.assertRaisesRegex(ValueError, 'changed|改动|变化'):
            self.api.publish(files, self.root, conflict='backup', expected=expected)
        self.assertFalse((self.root / 'si.pw2wan').exists())
        self.assertEqual((self.root / 'si.win').read_text(), 'other user change')

    def test_symlink_nonregular_source_and_result_protection(self):
        source = self.root / 'scf.in'
        source.write_text('source')
        (self.root / 'si.win').symlink_to(source)
        with self.assertRaises(ValueError):
            self.api.publish({'si.win': 'new'}, self.root, conflict='backup')
        with self.assertRaises(ValueError):
            self.api.publish({'scf.in': 'new'}, self.root, protected=[source])
        with self.assertRaises(ValueError):
            self.api.publish({'si.chk': 'new'}, self.root)
        with self.assertRaises(ValueError):
            self.api.publish({'../si.win': 'new'}, self.root)
        self.assertEqual(source.read_text(), 'source')

    def test_failure_rolls_back_replaced_and_created_files(self):
        (self.root / 'si.win').write_text('old')
        files = {'si.pw2wan': 'new interface', 'si.win': 'new', 'si.nscf.in': 'new nscf'}
        original = self.api.os.link
        def fail_once(src, dst):
            if Path(dst).name == 'si.nscf.in':
                raise OSError('injected disk failure')
            return original(src, dst)
        with mock.patch.object(self.api.os, 'link', side_effect=fail_once):
            with self.assertRaises(OSError):
                self.api.publish(files, self.root, conflict='backup')
        self.assertEqual((self.root / 'si.win').read_text(), 'old')
        self.assertFalse((self.root / 'si.pw2wan').exists())
        self.assertFalse((self.root / 'si.nscf.in').exists())
        self.assertTrue((self.root / 'bak/si.win.bak').is_file())
        self.assertEqual((self.root / 'bak/si.win.bak').read_text(), 'old')

    def test_crash_manifest_allows_explicit_recovery(self):
        (self.root / 'si.win').write_text('old')
        original = self.api.os.replace
        def crash(src, dst):
            result = original(src, dst)
            if Path(dst).name == 'si.win':
                raise SystemExit('simulated process termination')
            return result
        with mock.patch.object(self.api.os, 'replace', side_effect=crash):
            with self.assertRaises(SystemExit):
                self.api.publish({'si.win': 'new'}, self.root, conflict='backup')
        manifests = list(self.root.glob('.qbox-wannier-*/transaction.json'))
        self.assertEqual(len(manifests), 1)
        record = json.loads(manifests[0].read_text())
        self.assertEqual(record['entries'][0]['backup'], 'bak/si.win.bak')
        self.assertEqual((self.root / 'bak/si.win.bak').read_text(), 'old')
        (self.root / '.qbox-wannier.lock').write_text('999999999\n')
        self.api.recover(manifests[0])
        self.assertEqual((self.root / 'si.win').read_text(), 'old')
        self.assertFalse((self.root / '.qbox-wannier.lock').exists())
        self.assertEqual((self.root / 'bak/si.win.bak').read_text(), 'old')


if __name__ == '__main__':
    unittest.main()
