from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from installer.paths import InstallOptions, parse_options, validate_paths


class ParseOptionsTests(unittest.TestCase):
    def setUp(self):
        self.home = Path("/tmp/home")
        self.python = Path("/usr/bin/python3")

    def parse(self, argv, *, uid=1000):
        return parse_options(
            argv, uid=uid, home=self.home, default_python=self.python
        )

    def test_prefix_implies_command_directory(self):
        options = self.parse(["--user", "--prefix", "/tmp/qbox 中文"])
        self.assertEqual(options.bin_dir, Path("/tmp/qbox 中文/bin"))

    def test_prefix_order_does_not_change_derived_command_directory(self):
        before = self.parse(["--prefix", "/tmp/qbox", "--user"])
        after = self.parse(["--user", "--prefix", "/tmp/qbox"])
        self.assertEqual(before, after)
        self.assertEqual(before.bin_dir, Path("/tmp/qbox/bin"))

    def test_explicit_command_directory_overrides_prefix_default_in_any_order(self):
        expected = Path("/tmp/qbox commands")
        for argv in (
            ["--bin-dir", str(expected), "--user", "--prefix", "/tmp/qbox"],
            ["--prefix", "/tmp/qbox", "--bin-dir", str(expected), "--user"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(argv).bin_dir, expected)

    def test_mode_is_required_and_cannot_be_repeated_or_conflicted(self):
        for argv in ([], ["--user", "--user"], ["--system", "--system"],
                     ["--user", "--system"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                self.parse(argv, uid=0 if "--system" in argv else 1000)

    def test_mode_must_match_effective_uid(self):
        with self.assertRaisesRegex(ValueError, "root.*--user"):
            self.parse(["--user"], uid=0)
        with self.assertRaisesRegex(ValueError, "--system.*UID 0"):
            self.parse(["--system"], uid=1000)

    def test_mode_defaults_are_distinct_and_python_is_lexical(self):
        user = self.parse(["--user"])
        system = self.parse(["--system"], uid=0)
        self.assertEqual(user.prefix, Path("/tmp/home/.local/share/qbox"))
        self.assertEqual(user.bin_dir, user.prefix / "bin")
        self.assertEqual(system.prefix, Path("/opt/qbox"))
        self.assertEqual(system.bin_dir, Path("/opt/qbox/bin"))

        lexical = self.parse(
            ["--user", "--python", "/tmp/venv/bin/../bin/python"]
        )
        self.assertEqual(
            lexical.python, Path("/tmp/venv/bin/../bin/python").absolute()
        )

    def test_paths_are_absolute_and_expand_user(self):
        options = self.parse(
            ["--user", "--prefix", "~/qbox", "--bin-dir", "~/commands"]
        )
        self.assertEqual(options.prefix, Path("~/qbox").expanduser().absolute())
        self.assertEqual(
            options.bin_dir, Path("~/commands").expanduser().absolute()
        )

    def test_empty_root_and_line_break_paths_are_rejected(self):
        for flag, value in (
            ("--prefix", ""),
            ("--bin-dir", "   "),
            ("--python", ""),
            ("--prefix", "/"),
            ("--bin-dir", "/"),
            ("--prefix", "/tmp/qbox\nforged"),
            ("--bin-dir", "/tmp/qbox\rforged"),
            ("--python", "/tmp/python\nforged"),
        ):
            with self.subTest(flag=flag, value=value), self.assertRaisesRegex(
                ValueError, "empty|root|line break"
            ):
                self.parse(["--user", flag, value])

    def test_options_are_frozen(self):
        options = self.parse(["--user"])
        with self.assertRaises((AttributeError, TypeError)):
            options.prefix = Path("/tmp/replaced")


class ValidatePathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qbox path validation ")
        self.base = Path(self.temp.name)
        self.python = Path(sys.executable)

    def tearDown(self):
        self.temp.cleanup()

    def options(self, prefix, bin_dir=None, *, mode="user", python=None):
        prefix = Path(prefix)
        return InstallOptions(
            mode=mode,
            prefix=prefix,
            bin_dir=Path(bin_dir) if bin_dir is not None else prefix / "bin",
            python=Path(python) if python is not None else self.python,
        )

    def test_default_bin_is_allowed_but_dangerous_nesting_is_rejected(self):
        validate_paths(self.options(self.base / "qbox"))
        cases = (
            (self.base / "commands/qbox", self.base / "commands"),
            (self.base / "qbox", self.base / "qbox/venv/bin"),
            (self.base / "qbox", self.base / "qbox/releases/v1/bin"),
            (self.base / "qbox", self.base / "qbox/current/bin"),
        )
        for prefix, bin_dir in cases:
            with self.subTest(prefix=prefix, bin_dir=bin_dir), self.assertRaisesRegex(
                ValueError, "overlap|reserved"
            ):
                validate_paths(self.options(prefix, bin_dir))

    def test_metadata_and_lock_command_directories_are_reserved(self):
        for name in (".install-lock", ".install-lock/nested", ".qbox-install.json",
                     ".qbox-install.json/nested"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "reserved"):
                validate_paths(self.options(self.base / "qbox", self.base / "qbox" / name))
        self.assertFalse((self.base / "qbox").exists())

    def test_system_checks_every_symlink_expansion(self):
        safe, bridge, target = (self.base / name for name in ("safe", "bridge", "target"))
        for directory in (safe, bridge, target):
            directory.mkdir()
            directory.chmod(0o755)
        (safe / "alias").symlink_to("../bridge/hop")
        (bridge / "hop").symlink_to("../target")
        (target / "python").symlink_to("/usr/bin/python3")
        real_stat = os.stat

        def root_stat(path, *, follow_symlinks=True):
            path = Path(path)
            info = real_stat(path, follow_symlinks=follow_symlinks)
            mode = stat.S_IFDIR | 0o755 if path in (Path("/tmp"), self.base) else info.st_mode
            return SimpleNamespace(st_uid=0, st_mode=mode)

        variants = (
            self.options(safe / "alias/qbox", mode="system", python="/usr/bin/python3"),
            self.options(target / "qbox", safe / "alias/commands", mode="system", python="/usr/bin/python3"),
            self.options(target / "qbox", mode="system", python=safe / "alias/python"),
        )
        with mock.patch("installer.paths._stat_path", side_effect=root_stat):
            for options in variants:
                with self.subTest(options=options):
                    bridge.chmod(0o777)
                    with self.assertRaisesRegex(OSError, "bridge.*writable"):
                        validate_paths(options)
                    bridge.chmod(0o755)
                    validate_paths(options)
                    self.assertEqual(options.python, options.python.absolute())
            (bridge / "hop").unlink()
            (bridge / "hop").symlink_to("../safe/alias")
            with self.assertRaises((OSError, ValueError)):
                validate_paths(variants[0])

    def test_overlap_uses_components_instead_of_string_prefixes(self):
        validate_paths(
            self.options(self.base / "qbox", self.base / "qbox-other/bin")
        )

    def test_existing_parent_symlink_is_canonicalized_for_overlap(self):
        prefix = self.base / "real-prefix"
        prefix.mkdir()
        alias = self.base / "alias"
        alias.symlink_to(prefix, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "reserved"):
            validate_paths(self.options(alias, prefix / "venv/bin"))

    def test_reserved_symlink_target_is_canonicalized_for_overlap(self):
        prefix = self.base / "prefix"
        prefix.mkdir()
        environment = self.base / "environment"
        environment.mkdir()
        (prefix / "venv").symlink_to(environment, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "reserved"):
            validate_paths(self.options(prefix, environment / "bin"))

    def test_existing_file_ancestor_is_rejected(self):
        blocker = self.base / "not-a-directory"
        blocker.write_text("sentinel", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not a directory"):
            validate_paths(self.options(blocker / "qbox"))

    def test_python_must_exist_be_regular_and_executable(self):
        missing = self.base / "missing-python"
        directory = self.base / "python-directory"
        directory.mkdir()
        inert = self.base / "python-inert"
        inert.write_text("#!/bin/sh\n", encoding="utf-8")
        inert.chmod(0o644)
        for python, message in (
            (missing, "does not exist"),
            (directory, "regular file"),
            (inert, "executable"),
        ):
            with self.subTest(python=python), self.assertRaisesRegex(
                (ValueError, OSError), message
            ):
                validate_paths(self.options(self.base / "qbox", python=python))

    def test_revalidation_rejects_new_unsafe_directory_without_mutation(self):
        prefix = self.base / "new-prefix"
        options = self.options(prefix)
        validate_paths(options)
        prefix.mkdir()
        sentinel = prefix / "sentinel"
        sentinel.write_text("unchanged", encoding="utf-8")
        prefix.chmod(0o500)
        before = (prefix.stat().st_ino, stat.S_IMODE(prefix.stat().st_mode),
                  sentinel.read_text(encoding="utf-8"))
        try:
            with self.assertRaisesRegex(OSError, "writable"):
                validate_paths(options)
            after = (prefix.stat().st_ino, stat.S_IMODE(prefix.stat().st_mode),
                     sentinel.read_text(encoding="utf-8"))
            self.assertEqual(after, before)
        finally:
            prefix.chmod(0o700)

    def test_system_paths_accept_safe_shared_host_paths(self):
        options = InstallOptions(
            mode="system",
            prefix=Path("/opt/qbox-path-test-does-not-exist"),
            bin_dir=Path("/opt/qbox-path-test-does-not-exist/bin"),
            python=Path("/usr/bin/python3"),
        )
        real_stat = os.stat

        def root_owned_stat(path, *, follow_symlinks=True):
            path = Path(path)
            info = real_stat(path, follow_symlinks=follow_symlinks)
            mode = info.st_mode
            if (path == Path("/tmp") or path == self.base
                    or self.base in path.parents) and stat.S_ISDIR(mode):
                mode = stat.S_IFDIR | 0o755
            return SimpleNamespace(st_uid=0, st_mode=mode)

        with mock.patch("installer.paths._stat_path", side_effect=root_owned_stat):
            validate_paths(options)

    def test_system_destination_must_be_a_directory_if_it_exists(self):
        prefix = self.base / "existing-file"
        prefix.write_text("sentinel", encoding="utf-8")
        options = InstallOptions(
            mode="system",
            prefix=prefix,
            bin_dir=prefix / "bin",
            python=Path("/usr/bin/python3"),
        )
        real_stat = os.stat

        def root_owned_stat(path, *, follow_symlinks=True):
            path = Path(path)
            info = real_stat(path, follow_symlinks=follow_symlinks)
            mode = info.st_mode
            if (path == Path("/tmp") or path == self.base
                    or self.base in path.parents) and stat.S_ISDIR(mode):
                mode = stat.S_IFDIR | 0o755
            return SimpleNamespace(st_uid=0, st_mode=mode)

        with mock.patch("installer.paths._stat_path", side_effect=root_owned_stat):
            with self.assertRaisesRegex(ValueError, "must be a directory"):
                validate_paths(options)

    def test_system_destination_rechecks_resolved_symlink_target(self):
        target = self.base / "resolved-target"
        target.mkdir()
        prefix = self.base / "prefix-link"
        prefix.symlink_to(target, target_is_directory=True)
        options = InstallOptions(
            mode="system",
            prefix=prefix,
            bin_dir=prefix / "bin",
            python=Path("/usr/bin/python3"),
        )
        real_stat = os.stat

        def fake_stat(path, *, follow_symlinks=True):
            path = Path(path)
            info = real_stat(path, follow_symlinks=follow_symlinks)
            mode = info.st_mode
            if path == target:
                mode = stat.S_IFDIR | 0o775
            elif (path == Path("/tmp") or path == self.base
                  or self.base in path.parents) and stat.S_ISDIR(mode):
                mode = stat.S_IFDIR | 0o755
            return SimpleNamespace(st_uid=0, st_mode=mode)

        with mock.patch("installer.paths._stat_path", side_effect=fake_stat):
            with self.assertRaisesRegex(
                OSError, rf"{target}.*0775.*group-writable"
            ):
                validate_paths(options)

    def test_system_ancestor_diagnostics_name_path_uid_and_mode_problem(self):
        options = InstallOptions(
            mode="system",
            prefix=Path("/opt/qbox"),
            bin_dir=Path("/opt/qbox/bin"),
            python=Path("/usr/bin/python3"),
        )
        real_stat = os.stat

        def run_with(fake_uid, fake_mode, expected):
            def fake_stat(path, *, follow_symlinks=True):
                path = Path(path)
                if path == Path("/opt"):
                    return SimpleNamespace(st_uid=fake_uid, st_mode=fake_mode)
                info = real_stat(path, follow_symlinks=follow_symlinks)
                return SimpleNamespace(st_uid=0, st_mode=info.st_mode)

            with mock.patch("installer.paths._stat_path", side_effect=fake_stat):
                with self.assertRaisesRegex(OSError, expected):
                    validate_paths(options)

        cases = (
            (1000, stat.S_IFDIR | 0o755, r"/opt.*uid 1000.*uid 0"),
            (0, stat.S_IFDIR | 0o775, r"/opt.*0775.*group-writable"),
            (0, stat.S_IFDIR | 0o757, r"/opt.*0757.*other-writable"),
            (0, stat.S_IFDIR | 0o750, r"/opt.*0750.*other users.*traverse"),
        )
        for uid, mode, expected in cases:
            with self.subTest(uid=uid, mode=oct(mode)):
                run_with(uid, mode, expected)

    def test_system_ancestor_may_be_traversable_without_directory_listing(self):
        options = InstallOptions(
            mode="system",
            prefix=Path("/opt/qbox"),
            bin_dir=Path("/opt/qbox/bin"),
            python=Path("/usr/bin/python3"),
        )
        real_stat = os.stat

        def fake_stat(path, *, follow_symlinks=True):
            path = Path(path)
            info = real_stat(path, follow_symlinks=follow_symlinks)
            mode = stat.S_IFDIR | 0o711 if path == Path("/opt") else info.st_mode
            return SimpleNamespace(st_uid=0, st_mode=mode)

        with mock.patch("installer.paths._stat_path", side_effect=fake_stat):
            validate_paths(options)

    def test_system_python_checks_resolved_target_for_other_execute(self):
        link = self.base / "selected-python"
        link.symlink_to("/usr/bin/python3")
        target = link.resolve()
        options = InstallOptions(
            mode="system",
            prefix=Path("/opt/qbox"),
            bin_dir=Path("/opt/qbox/bin"),
            python=link,
        )
        real_stat = os.stat

        def fake_stat(path, *, follow_symlinks=True):
            path = Path(path)
            if path == target:
                return SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o744)
            if path == link and not follow_symlinks:
                return SimpleNamespace(st_uid=0, st_mode=stat.S_IFLNK | 0o777)
            info = real_stat(path, follow_symlinks=follow_symlinks)
            mode = info.st_mode
            if path == Path("/tmp") or path == self.base or self.base in path.parents:
                if stat.S_ISDIR(mode):
                    mode = stat.S_IFDIR | 0o755
            return SimpleNamespace(st_uid=0, st_mode=mode)

        with mock.patch("installer.paths._stat_path", side_effect=fake_stat):
            with self.assertRaisesRegex(
                OSError, r"Python interpreter.*resolved target.*executable by other users"
            ):
                validate_paths(options)
        self.assertEqual(options.python, link)


if __name__ == "__main__":
    unittest.main()
