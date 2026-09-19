"""Host-Python-free bootstrap contract; Python here only drives the developer tests."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

INSTALL = Path(__file__).resolve().parents[2] / 'packaging/offline/install.sh'
ENV = {k: v for k, v in os.environ.items() if not k.startswith('BASH_FUNC_')}


def shell(code, *args, cwd=None, env=None):
    return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                           'source "$1" || exit; shift; ' + code,
                           'bootstrap-test', str(INSTALL), *map(str, args)],
                          cwd=cwd, env=ENV if env is None else env,
                          text=True, capture_output=True)


class PreflightTests(unittest.TestCase):
    def test_source_has_no_writes_or_shell_option_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            result = shell('printf "%s" "$-"', cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertEqual(result.stdout, 'hBc')

    def test_invalid_options_do_not_write(self):
        cases = [(['--prefix'], '缺少'), (['--bin-dir'], '缺少'),
                 (['--prefix', '/tmp/a', '--prefix', '/tmp/b'], '重复'),
                 (['--bin-dir', '/tmp/a', '--bin-dir', '/tmp/b'], '重复'),
                 (['--bad'], '未知'), (['--prefix', ''], '空'),
                 (['--prefix', 'relative'], '绝对路径'),
                 (['--prefix', '/'], '根目录'),
                 (['--bin-dir', 'relative'], '绝对路径'),
                 (['--prefix', '/tmp/a\nb'], '控制字符')]
        for args, diagnostic in cases:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(['/bin/bash', str(INSTALL), *args], cwd=directory,
                                        env=ENV, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_default_and_unicode_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            result = shell('HOME="$1"; parse_options && preflight_paths && printf "%s\\n%s\\n" "$QBOX_PREFIX" "$QBOX_BIN_DIR"', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [directory+'/.local/share/qbox', directory+'/.local/bin'])
            result = shell('parse_options --prefix "$1/中文 空格" --bin-dir "$1/bin 空格" && preflight_paths && printf "%s" "$QBOX_PREFIX"', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, directory+'/中文 空格')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_glibc_numeric_and_platform_constraints(self):
        for version, success in [('2.27', False), ('2.28', True), ('2.31', True), ('2.9', False), ('3.0', True), ('garbage', False)]:
            with self.subTest(version=version):
                result = shell('probe_glibc() { printf "%s\\n" "$1"; }; V="$1"; probe_glibc() { printf "%s\\n" "$V"; }; preflight_platform', version)
                self.assertEqual(result.returncode == 0, success, result.stderr)
        for override, message in [('uname() { printf "aarch64\\n"; }', 'Linux x86_64'),
                                  ('probe_bash_version() { printf "4.3\\n"; }', 'Bash 4.4'),
                                  ('command() { if [[ "$*" == "-v gzip" ]]; then return 1; fi; builtin command "$@"; }', 'gzip')]:
            with self.subTest(override=override):
                result = shell(override + '; preflight_platform')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_glibc_loader_formats(self):
        for text, expected in [('ld.so (Ubuntu GLIBC 2.31-0ubuntu9.18) stable release version 2.31.\nCopyright', '2.31'),
                               ('ld.so (GNU libc) stable release version 2.28.\nCopyright', '2.28')]:
            result = shell('parse_loader_glibc "$1"', text)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), expected)
        self.assertNotEqual(shell('parse_loader_glibc "glibc maybe 2.40"').returncode, 0)

    def test_prefix_ownership_marker_and_non_qbox_content(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)/'prefix'
            prefix.mkdir()
            (prefix/'foreign').write_text('untouched')
            code = 'parse_options --prefix "$1" --bin-dir "$2/bin" && preflight_paths'
            self.assertNotEqual(shell(code, prefix, directory).returncode, 0)
            valid = f'schema_version=1\nuid={os.geteuid()}\nprefix={prefix}\n'
            marker = prefix/'.qbox-root'
            for content, success in [(valid, True), (valid.rstrip('\n'), False), (valid+'extra\n', False),
                                     (valid.replace(f'uid={os.geteuid()}', 'uid=999999'), False),
                                     (valid.replace(str(prefix), '/other'), False)]:
                marker.write_text(content)
                result = shell(code, prefix, directory)
                self.assertEqual(result.returncode == 0, success, (content, result.stderr))
            marker.unlink()
            target = Path(directory)/'marker'
            target.write_text(valid)
            marker.symlink_to(target)
            self.assertNotEqual(shell(code, prefix, directory).returncode, 0)
            self.assertEqual((prefix/'foreign').read_text(), 'untouched')

    def test_overlap_uses_canonical_parent_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'actual').mkdir()
            (root/'alias').symlink_to(root/'actual', target_is_directory=True)
            for prefix, bindir in [('actual', 'alias/releases/bin'), ('actual', 'alias/current'),
                                   ('actual', 'alias/.stage.x/bin'), ('actual', 'actual'),
                                   ('actual/child', 'alias')]:
                result = shell('parse_options --prefix "$1" --bin-dir "$2" && preflight_paths', root/prefix, root/bindir)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('重叠', result.stderr)


def make_archive(path, entries, format=tarfile.USTAR_FORMAT):
    # Never truncate fixture inputs that alias cache or evidence artifacts.
    if path.is_symlink() or (path.exists() and path.stat().st_nlink != 1):
        raise ValueError('fixture destination must be an independent regular file')
    with tarfile.open(path, 'w:gz', format=format) as output:
        for name, kind, value in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = value
            elif kind == tarfile.REGTYPE:
                member.size = len(value)
            output.addfile(member, io.BytesIO(value) if kind == tarfile.REGTYPE else None)


def make_bundle(root, entries=None, format=tarfile.USTAR_FORMAT):
    root.mkdir(exist_ok=True)
    for folder in ('runtime', 'checks', 'packages', 'wheelhouse', 'THIRD_PARTY_LICENSES'):
        (root/folder).mkdir(exist_ok=True)
    for name in ('install.sh', 'manifest.json', 'requirements.lock', 'README.zh-CN.md', 'LICENSE'):
        (root/name).write_text('fixture\n')
    make_archive(root/'runtime/python.tar.gz', entries or [('python/lib/file', tarfile.REGTYPE, b'good')], format)
    hash_bundle(root)


def hash_bundle(root):
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
    (root/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}\n' for p in files))


class ArchiveTests(unittest.TestCase):
    def test_present_nonexecutable_interpreter_reports_execution_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bundle=root/'bundle';stage=root/'stage';stage.mkdir()
            entries=[('python',tarfile.DIRTYPE,b''),('python/bin',tarfile.DIRTYPE,b''),
                     ('python/bin/python3',tarfile.REGTYPE,b'#!/bin/sh\nexit 0\n'),
                     ('python/bin/python3.12',tarfile.REGTYPE,b'#!/bin/sh\nexit 0\n')]
            make_bundle(bundle,entries)
            result=shell('verify_bundle_files "$1" && extract_runtime "$1/runtime/python.tar.gz" "$2"',bundle,stage)
            self.assertNotEqual(result.returncode,0)
            self.assertTrue((stage/'python/bin/python3').is_file())
            self.assertIn('不可执行',result.stderr)
            self.assertIn('noexec',result.stderr)

    def test_safe_runtime_inspection_and_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'bundle'
            make_bundle(root, [('python', tarfile.DIRTYPE, b''), ('python/lib/', tarfile.DIRTYPE, b''),
                               ('python/lib/file+@=-.txt', tarfile.REGTYPE, b'good')])
            result = shell('verify_bundle_files "$1" && inspect_runtime_archive "$1/runtime/python.tar.gz" && printf "%s\\n%s\\n" "$QBOX_RUNTIME_SHA256" "$QBOX_VERIFIED_BUNDLE"', root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [hashlib.sha256((root/'runtime/python.tar.gz').read_bytes()).hexdigest(), str(root)])

    def test_malicious_members_fail_with_fresh_hash_without_outside_writes(self):
        cases = [ [('..//outside', tarfile.REGTYPE, b'x')], [('../outside', tarfile.REGTYPE, b'x')],
                  [('/absolute', tarfile.REGTYPE, b'x')], [('python/../x', tarfile.REGTYPE, b'x')],
                  [('python//x', tarfile.REGTYPE, b'x')], [('python/./x', tarfile.REGTYPE, b'x')],
                  [('python/a\nb', tarfile.REGTYPE, b'x')], [('python/a\\nb', tarfile.REGTYPE, b'x')],
                  [('python/a b', tarfile.REGTYPE, b'x')], [('python/a', tarfile.SYMTYPE, 'b')],
                  [('python/a', tarfile.SYMTYPE, '../../outside')], [('python/a', tarfile.LNKTYPE, 'python/b')],
                  [('python/a', tarfile.FIFOTYPE, b'')], [('python/a', tarfile.CHRTYPE, b'')],
                  [('python/a', tarfile.REGTYPE, b'x'), ('python/a', tarfile.REGTYPE, b'y')],
                  [('python/a', tarfile.REGTYPE, b'x'), ('python/a/b', tarfile.REGTYPE, b'y')],
                  [('python/a/b', tarfile.REGTYPE, b'x'), ('python/a', tarfile.REGTYPE, b'y')],
                  [('python', tarfile.REGTYPE, b'x')], [('python/a/', tarfile.REGTYPE, b'x')],
                  [('python/a//', tarfile.DIRTYPE, b'')], [('other/file', tarfile.REGTYPE, b'x')]]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                make_bundle(root/'bundle', entries)
                (root/'outside').write_bytes(b'sentinel')
                (root/'stage').mkdir()
                result = shell('verify_bundle_files "$1" || exit; printf "verified\\n"; extract_runtime "$1/runtime/python.tar.gz" "$2"', root/'bundle', root/'stage')
                self.assertEqual(result.stdout, 'verified\n', result.stderr)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('归档', result.stderr)
                self.assertEqual((root/'outside').read_bytes(), b'sentinel')
                self.assertTrue((root/'stage').is_dir())
                self.assertEqual(list((root/'stage').iterdir()), [])

    def test_gnu_and_pax_effective_names_are_validated(self):
        for format in (tarfile.GNU_FORMAT, tarfile.PAX_FORMAT):
            for name, accepted in [('python/' + 'a'*140, True), ('python/' + 'a'*110+'/../x', False)]:
                with self.subTest(format=format, name=name), tempfile.TemporaryDirectory() as directory:
                    archive = Path(directory)/'runtime.tar.gz'
                    make_archive(archive, [(name, tarfile.REGTYPE, b'x')], format)
                    result = shell('inspect_runtime_archive "$1"', archive)
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_non_normalized_owner_and_special_modes_are_rejected(self):
        for uid, mode in [(1, 0o644), (0, 0o4755), (0, 0o2755), (0, 0o1755)]:
            with self.subTest(uid=uid, mode=mode), tempfile.TemporaryDirectory() as directory:
                archive = Path(directory)/'runtime.tar.gz'
                with tarfile.open(archive, 'w:gz') as output:
                    member = tarfile.TarInfo('python/a')
                    member.uid, member.mode = uid, mode
                    output.addfile(member)
                self.assertNotEqual(shell('inspect_runtime_archive "$1"', archive).returncode, 0)

    def test_listing_rejects_stderr_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'runtime.tar.gz'
            make_archive(archive, [('python/a', tarfile.REGTYPE, b'x')])
            for suffix in ('printf "warning\\n" >&2', 'return 2'):
                result = shell('tar() { command tar "$@"; '+suffix+'; }; inspect_runtime_archive "$1"', archive)
                self.assertNotEqual(result.returncode, 0)

    def test_bundle_rejects_extra_missing_links_special_files_and_bad_checksums(self):
        changes = ['extra', 'missing', 'symlink', 'fifo', 'directory', 'upper', 'single-space', 'duplicate', 'traversal', 'no-newline', 'self', 'bad-hash']
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)/'bundle'
                make_bundle(root)
                sums = root/'SHA256SUMS'
                content = sums.read_text()
                if change == 'extra': (root/'checks/extra').write_text('extra')
                elif change == 'missing': (root/'LICENSE').unlink()
                elif change == 'symlink': (root/'checks/link').symlink_to(root/'LICENSE')
                elif change == 'fifo': os.mkfifo(root/'checks/fifo')
                elif change == 'directory': (root/'unexpected').mkdir()
                elif change == 'upper': sums.write_text(content.upper())
                elif change == 'single-space': sums.write_text(content.replace('  ', ' '))
                elif change == 'duplicate': sums.write_text(content+content.splitlines()[0]+'\n')
                elif change == 'traversal': sums.write_text(content+'0'*64+'  ../outside\n')
                elif change == 'no-newline': sums.write_text(content.rstrip('\n'))
                elif change == 'self': sums.write_text(content+'0'*64+'  SHA256SUMS\n')
                elif change == 'bad-hash': (root/'LICENSE').write_text('bad')
                result = shell('QBOX_RUNTIME_SHA256=stale; QBOX_VERIFIED_BUNDLE=stale; verify_bundle_files "$1"; status=$?; printf "%s|%s" "${QBOX_RUNTIME_SHA256-}" "${QBOX_VERIFIED_BUNDLE-}"; exit "$status"', root)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '|')

    def test_extract_refuses_unverified_changed_archive_or_nonempty_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_bundle(root/'bundle')
            stage = root/'stage'
            stage.mkdir()
            archive = root/'bundle/runtime/python.tar.gz'
            result = shell('extract_runtime "$1" "$2"', archive, stage)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(stage.iterdir()), [])
            result = shell('verify_bundle_files "$1" && printf changed >> "$1/runtime/python.tar.gz"; extract_runtime "$1/runtime/python.tar.gz" "$2"', root/'bundle', stage)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(stage.iterdir()), [])
            make_bundle(root/'bundle')
            (stage/'python').mkdir()
            (stage/'python/sentinel').write_text('keep')
            result = shell('verify_bundle_files "$1" && extract_runtime "$1/runtime/python.tar.gz" "$2"', root/'bundle', stage)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((stage/'python/sentinel').read_text(), 'keep')

    def test_normalizer_rejects_non_directory_root(self):
        from tools.offline.archive import normalize_runtime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_archive(root/'bad.tar.gz', [('python', tarfile.REGTYPE, b'x')])
            with self.assertRaises(ValueError):
                normalize_runtime(root/'bad.tar.gz', root/'normalized.tar.gz')
            self.assertFalse((root/'normalized.tar.gz').exists())


class AdditionalBoundaryTests(unittest.TestCase):
    def test_safe_nested_bin_dirs_and_reserved_component_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)/'prefix'
            for tail in ('bin', 'custom/commands', 'releases-extra', '.stage-other', 'current-extra'):
                result = shell('parse_options --prefix "$1" --bin-dir "$2" && preflight_paths', prefix, prefix/tail)
                self.assertEqual(result.returncode, 0, (tail, result.stderr))
            for tail in ('releases', 'releases/bin', 'current', '.install-lock', '.install-lock/bin', '.stage.abc/bin', '.qbox-root'):
                result = shell('parse_options --prefix "$1" --bin-dir "$2" && preflight_paths', prefix, prefix/tail)
                self.assertNotEqual(result.returncode, 0, tail)

    def test_current_alias_is_rejected_even_when_pointing_outside_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root/'prefix'
            prefix.mkdir()
            (prefix/'.qbox-root').write_text(f'schema_version=1\nuid={os.geteuid()}\nprefix={prefix}\n')
            (prefix/'current').symlink_to(root/'external')
            result = shell('parse_options --prefix "$1" --bin-dir "$1/current/bin" && preflight_paths', prefix)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('重叠', result.stderr)

    def test_existing_file_ancestor_is_rejected_without_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'file').write_text('keep')
            result = shell('parse_options --prefix "$1/file/child" --bin-dir "$1/bin" && preflight_paths', root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['file'])

    def test_checksum_nul_cannot_be_silently_ignored_by_bash_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'bundle'
            make_bundle(root)
            path=root/'SHA256SUMS'
            path.write_bytes(path.read_bytes().replace(b'  LICENSE', b'\x00  LICENSE'))
            self.assertNotEqual(shell('verify_bundle_files "$1"', root).returncode, 0)

    def test_tar_environment_options_cannot_change_the_checked_member_set(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'runtime.tar.gz'
            make_archive(archive, [('python/good', tarfile.REGTYPE, b'ok'), ('python/bad', tarfile.SYMTYPE, '../../outside')])
            result = shell('inspect_runtime_archive "$1"', archive, env={**ENV, 'TAR_OPTIONS': '--exclude=python/bad'})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('归档', result.stderr)

    def test_glibc_fallback_works_without_getconf(self):
        result = shell('command() { [[ "$*" != "-v getconf" ]] && builtin command "$@"; }; probe_glibc')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r'^\d+\.\d+\n$')

    def test_unreliable_glibc_probes_fail_explicitly(self):
        result = shell('command() { [[ "$*" != "-v getconf" ]] && builtin command "$@"; }; parse_loader_glibc() { return 1; }; probe_glibc')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('无法可靠识别', result.stderr)

    def test_failed_extraction_never_deletes_callers_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_bundle(root/'bundle')
            stage = root/'stage'
            stage.mkdir()
            result = shell('verify_bundle_files "$1" && extract_runtime "$1/runtime/python.tar.gz" "$2"', root/'bundle', stage)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('缺少必需解释器', result.stderr)
            self.assertEqual((stage/'python/lib/file').read_bytes(), b'good')
            self.assertEqual([p for p in stage.iterdir() if p.name.startswith('.runtime-input.')], [])

    def test_effective_pax_path_overrides_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'runtime.tar.gz'
            with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT) as output:
                member = tarfile.TarInfo('python/safe')
                member.pax_headers = {'path': '../outside'}
                output.addfile(member)
            result = shell('inspect_runtime_archive "$1"', archive)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('归档', result.stderr)

    def test_fixture_writer_refuses_to_truncate_shared_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root/'cache'
            original.write_bytes(b'cached')
            alias = root/'archive'
            os.link(original, alias)
            with self.assertRaises(ValueError):
                make_archive(alias, [('python/x', tarfile.REGTYPE, b'x')])
            self.assertEqual(original.read_bytes(), b'cached')


    def test_unreadable_bundle_directory_cannot_hide_unlisted_files(self):
        if os.geteuid() == 0:
            self.skipTest('permission test needs ordinary user')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'bundle'
            make_bundle(root)
            hidden = root/'checks/hidden'
            hidden.mkdir()
            (hidden/'extra').write_text('unlisted')
            hidden.chmod(0)
            try:
                result = shell('verify_bundle_files "$1"', root)
                self.assertNotEqual(result.returncode, 0)
            finally:
                hidden.chmod(0o700)


    def test_unreadable_owned_directory_is_not_assumed_empty(self):
        if os.geteuid() == 0:
            self.skipTest('permission test needs ordinary user')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root/'prefix'
            prefix.mkdir()
            (prefix/'foreign').write_text('keep')
            prefix.chmod(0o300)
            try:
                result = shell('parse_options --prefix "$1" --bin-dir "$2/bin" && preflight_paths', prefix, root)
                self.assertNotEqual(result.returncode, 0)
            finally:
                prefix.chmod(0o700)
            self.assertEqual((prefix/'foreign').read_text(), 'keep')


    def test_actual_target_tar_listing_fixtures_and_strict_columns(self):
        fixtures = json.loads((Path(__file__).parent/'fixtures/bootstrap-platforms.json').read_text())['platforms']
        self.assertEqual(len(fixtures), 5)
        for fixture in fixtures:
            with self.subTest(platform=fixture['tag']), tempfile.TemporaryDirectory() as directory:
                listing = Path(directory)/'listing'
                listing.write_text(fixture['listing'])
                result = shell('validate_runtime_listing "$1"', listing)
                self.assertEqual(result.returncode, 0, result.stderr)
                for old, new in [('0/0', '1/0'), ('drwxr-xr-x', 'drwsr-xr-x'),
                                 ('python/lib/sample+@=-.txt', 'python/lib/sample name.txt'),
                                 ('python/lib/', 'python/lib//')]:
                    listing.write_text(fixture['listing'].replace(old, new))
                    self.assertNotEqual(shell('validate_runtime_listing "$1"', listing).returncode, 0, (old, new))


    def test_checksums_preserve_literal_backslashes_in_host_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root/'中文 空格\\bundle'
            make_bundle(bundle)
            result = shell('verify_bundle_files "$1"', bundle)
            self.assertEqual(result.returncode, 0, result.stderr)
            stage = root/'stage\\literal'
            stage.mkdir()
            result = shell('verify_bundle_files "$1" && extract_runtime "$1/runtime/python.tar.gz" "$2"', bundle, stage)
            self.assertIn('缺少必需解释器', result.stderr)
            prefix = root/'prefix\\literal'
            prefix.mkdir()
            (prefix/'.qbox-root').write_text(f'schema_version=1\nuid={os.geteuid()}\nprefix={prefix}\n')
            result = shell('validate_root_marker "$1"', prefix)
            self.assertEqual(result.returncode, 0, result.stderr)


    def test_globignore_cannot_hide_payload_or_existing_stage_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_bundle(root/'bundle')
            (root/'bundle/checks/extra').write_text('unlisted')
            result = shell('GLOBIGNORE="*"; verify_bundle_files "$1"', root/'bundle')
            self.assertNotEqual(result.returncode, 0)
            stage = root/'stage'
            stage.mkdir()
            (stage/'existing').write_text('keep')
            result = shell('GLOBIGNORE="*"; directory_is_empty "$1"', stage)
            self.assertNotEqual(result.returncode, 0)


class ReviewRegressionTests(unittest.TestCase):
    def test_approved_third_party_license_layout_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'bundle'
            make_bundle(root)
            licenses = root/'THIRD_PARTY_LICENSES'
            (licenses/'runtime.txt').write_text('Actual third-party license fixture\n')
            hash_bundle(root)
            result = shell('verify_bundle_files "$1" && printf "%s" "$QBOX_VERIFIED_BUNDLE"', root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, str(root))

    def test_unreadable_bundle_root_rejects_hidden_extra_and_clears_state(self):
        if os.geteuid() == 0:
            self.skipTest('permission test needs ordinary user')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'bundle'
            make_bundle(root)
            (root/'unlisted-extra').write_text('must not evade inventory')
            root.chmod(0o300)
            try:
                result = shell('QBOX_RUNTIME_SHA256=stale; QBOX_VERIFIED_BUNDLE=stale; verify_bundle_files "$1"; status=$?; printf "%s|%s" "${QBOX_RUNTIME_SHA256-}" "${QBOX_VERIFIED_BUNDLE-}"; exit "$status"', root)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '|')
                self.assertIn('无法完整枚举', result.stderr)
            finally:
                root.chmod(0o700)


class BundleIdentityTests(unittest.TestCase):
    """Identity must bind delivered bytes before either new install or reuse."""
    def test_identity_rejects_rehashed_incomplete_or_changed_payload(self):
        import copy
        import sys
        from test_model import complete_manifest
        from tools.offline.model import canonical_json, release_id, validate_manifest
        for mutation in ['valid','missing-wheel','changed-byte','changed-size','extra-file']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);bundle=root/'bundle';bundle.mkdir()
                manifest=complete_manifest()
                record=copy.deepcopy(manifest['files'][0])
                record.update(path='checks/manifest.py')
                manifest['files'].append(record)
                for item in manifest['files']:
                    path=bundle/item['path'];path.parent.mkdir(parents=True,exist_ok=True)
                    content=((INSTALL.parent/'checks/manifest.py').read_bytes()
                             if item['path']=='checks/manifest.py' else item['path'].encode())
                    path.write_bytes(content)
                    item.update(size=len(content),sha256=hashlib.sha256(content).hexdigest())
                records={item['path']:item for item in manifest['files']}
                for item in [manifest['runtime'],*manifest['wheels']]:item.update(records[item['path']])
                identity=manifest['identity']
                identity.update(runtime_sha256=manifest['runtime']['sha256'],
                    qbox_wheel_sha256=manifest['wheels'][0]['sha256'],
                    dependencies_lock_sha256=records['requirements.lock']['sha256'],
                    build_requirements_lock_sha256=records['checks/build-requirements.lock']['sha256'],
                    installer_template_sha256=records['install.sh']['sha256'],
                    launcher_template_sha256=records['checks/qbox-launcher.sh']['sha256'],
                    checks={p:r['sha256'] for p,r in records.items() if p.startswith('checks/') and p!='checks/qbox-launcher.sh'},
                    licenses={p:records[p]['sha256'] for paths in manifest['licenses'].values() for p in paths})
                manifest['release_id']=release_id(manifest['qbox_version'],identity)
                validate_manifest(manifest)
                (bundle/'manifest.json').write_bytes(canonical_json(manifest))
                wheel=bundle/manifest['wheels'][1]['path']
                if mutation=='missing-wheel':wheel.unlink()
                elif mutation=='changed-byte':wheel.write_bytes(b'X'+wheel.read_bytes()[1:])
                elif mutation=='changed-size':wheel.write_bytes(b'short')
                elif mutation=='extra-file':(bundle/'checks/unlisted.txt').write_text('not in manifest')
                hash_bundle(bundle)
                stage=root/'stage';(stage/'python/bin').mkdir(parents=True)
                (stage/'python/bin/python3').symlink_to(sys.executable)
                result=shell('bundle=$1; stage=$2; verify_bundle_files "$bundle" || exit; printf "checksums-ok\\n"; read_bundle_identity',bundle,stage)
                self.assertIn('checksums-ok',result.stdout)
                if mutation=='valid':self.assertEqual(result.returncode,0,result.stderr)
                else:
                    self.assertNotEqual(result.returncode,0,result.stderr)
                    self.assertIn('manifest 身份校验失败',result.stderr)


if __name__ == '__main__':
    unittest.main()
