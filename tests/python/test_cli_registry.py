"""Public entry and registry contracts, without QE or scientific dependencies."""

import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src"
sys.path.insert(0, str(SOURCE))


class CliRegistryTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="qbox cli offline ")
        self.addCleanup(self.sandbox.cleanup)
        self.release = Path(self.sandbox.name).resolve() / "release with spaces"
        self.python_prefix = self.release / "python"
        self.package_dir = self.python_prefix / "lib/python3.12/site-packages/qbox"
        (self.release / "metadata").mkdir(parents=True)
        (self.python_prefix / "bin").mkdir(parents=True)
        self.package_dir.mkdir(parents=True)
        bundled_python = self.python_prefix / "bin/python3"
        bundled_python.write_text("", encoding="utf-8")
        bundled_python.chmod(0o755)
        identity = {"qbox_version": "0.1.0", "runtime_sha256": "c" * 64}
        identity_bytes = (
            json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        self.release_id = "0.1.0-" + hashlib.sha256(identity_bytes).hexdigest()
        manifest = {
            "schema_version": 1,
            "product": "qbox",
            "qbox_version": "0.1.0",
            "identity": identity,
            "release_id": self.release_id,
        }
        manifest_path = self.release / "metadata/manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        marker = {
            "schema_version": 1,
            "product": "qbox",
            "release_id": self.release_id,
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "state": "verified",
            "inventory_sha256": "b" * 64,
        }
        (self.release / "metadata/installed.json").write_text(
            json.dumps(marker), encoding="utf-8"
        )

    def offline_runtime(self, cli):
        return (
            patch.object(cli, "__file__", str(self.package_dir / "cli.py")),
            patch.object(cli.sys, "prefix", str(self.python_prefix)),
            patch.object(cli.sys, "flags", SimpleNamespace(isolated=1)),
        )

    def run_module(self, module, *args):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SOURCE)
        return subprocess.run(
            [sys.executable, "-S", "-m", module, *args],
            env=env, text=True, capture_output=True, check=False,
        )

    def test_help_works_without_scientific_site_packages(self):
        result = self.run_module("qbox", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--task", result.stdout)
        self.assertIn("QBOX_PYTHON", result.stdout)
        self.assertIn("QBOX_SHARED_ROOT", result.stdout)

    def test_registry_lists_every_legacy_task_once(self):
        registry = importlib.import_module("qbox.registry")
        self.assertEqual([task.id for task in registry.TASKS], list(range(38)))
        self.assertEqual(len({task.slug for task in registry.TASKS}), 38)
        self.assertEqual(len({task.handler for task in registry.TASKS}), 38)
        for selector in ("0", "pw-input"):
            self.assertEqual(registry.get_task(selector).handler, "pwin")
        self.assertEqual(registry.get_task("27").handler, "qbox_nscf_menu")
        self.assertEqual(registry.get_task("37").handler, "qe_action_vasp_to_cif")

    def test_private_registry_menu_matches_legacy_display(self):
        result = self.run_module("qbox.registry", "--menu")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            (ROOT / "tests/fixtures/expected/main_menu.txt").read_text(),
        )

    def test_menu_includes_new_registered_tasks_without_renderer_changes(self):
        registry = importlib.import_module("qbox.registry")
        tasks = (
            *registry.TASKS,
            registry.TaskSpec(38, "new-input", "新增输入任务", "输入文件生成", "new_input"),
            registry.TaskSpec(39, "new-category", "新分类任务", "新增分类", "new_category"),
        )
        menu = registry.render_menu(tasks)
        self.assertEqual(menu.count("38) 新增输入任务"), 1)
        self.assertEqual(menu.count("39) 新分类任务"), 1)
        self.assertLess(menu.index("38) 新增输入任务"), menu.index("执行计算"))
        self.assertIn("新增分类", menu)
        self.assertEqual(menu.count("0) 生成 pw.x 输入文件"), 1)

    def test_private_registry_ids_and_handler_are_safe(self):
        result = self.run_module("qbox.registry", "--ids")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), [str(i) for i in range(38)])
        result = self.run_module("qbox.registry", "--handler", "13")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "qe_action_pdos\n")
        for invalid in ("-1", "38", "00", "pw-input", "pwin; touch bad"):
            result = self.run_module("qbox.registry", "--handler", invalid)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")

    def test_public_list_is_human_readable_and_complete(self):
        result = self.run_module("qbox", "--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 39)
        self.assertIn("pw-input", lines[1])
        self.assertIn("vasp-to-cif", lines[-1])
        self.assertIn("输入文件生成", result.stdout)

    def test_invalid_or_missing_explicit_task_never_runs_legacy(self):
        cli = importlib.import_module("qbox.cli")
        for args in (["--task"], ["--task", "38"], ["--task", "not-a-task"]):
            with patch("qbox.cli.os.execvpe") as execute, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(args), 2)
                execute.assert_not_called()

    def test_legacy_arguments_and_environment_cross_exec_boundary_intact(self):
        cli = importlib.import_module("qbox.cli")
        with patch.dict(os.environ, {
            "PYTHONPATH": "/another/package", "QBOX_PYTHON": "/chosen/python",
            "QBOX_TASK_ID": "31", "QBOX_PSEUDO_ROOT": "/chosen/pseudos",
        }, clear=True), patch("qbox.cli.os.execvpe") as execute:
            self.assertEqual(cli.main(["input with spaces.in", "23", "--unknown"]), 0)
            program, arguments, env = execute.call_args.args
        self.assertEqual(program, "bash")
        self.assertEqual(arguments, [
            "bash", str(SOURCE / "qbox/legacy/entry.sh"),
            "input with spaces.in", "23", "--unknown",
        ])
        self.assertEqual(env["QBOX_PYTHON"], "/chosen/python")
        self.assertEqual(env["QBOX_PSEUDO_ROOT"], "/chosen/pseudos")
        self.assertNotIn("QBOX_TASK_ID", env)
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep), [str(SOURCE), "/another/package"])

    def test_explicit_task_preserves_input_arguments_and_sets_validated_id(self):
        cli = importlib.import_module("qbox.cli")
        for selector in ("0", "pw-input"):
            with patch.dict(os.environ, {}, clear=True), patch("qbox.cli.os.execvpe") as execute:
                self.assertEqual(cli.main(["--task", selector, "input with spaces.cif"]), 0)
                _, arguments, env = execute.call_args.args
            self.assertEqual(arguments[-1], "input with spaces.cif")
            self.assertNotIn(selector, arguments[2:])
            self.assertEqual(env["QBOX_TASK_ID"], "0")
            self.assertEqual(env["QBOX_PYTHON"], sys.executable)

    def test_shared_root_keeps_configured_interpreter_default(self):
        cli = importlib.import_module("qbox.cli")
        with patch.dict(os.environ, {"QBOX_SHARED_ROOT": "/shared/root"}, clear=True), \
                patch("qbox.cli.os.execvpe") as execute:
            cli.main([])
            env = execute.call_args.args[2]
        self.assertEqual(env["QBOX_PYTHON"], "/shared/root/python/bin/python3")

    def test_offline_exec_keeps_external_environment(self):
        cli = importlib.import_module("qbox.cli")
        original = {
            "_QBOX_OFFLINE_ROOT": str(self.release),
            "QBOX_PYTHON": str(self.release / "python/bin/python3"),
            "PYTHONPATH": "/external/python-libs",
            "PYTHONHOME": "/external/python",
            "PATH": "/mpi/bin:/usr/bin:/bin",
            "LD_LIBRARY_PATH": "/mpi/lib",
            "OMPI_MCA_btl": "self,tcp",
            "QBOX_QE_ENV_SCRIPT": "/external/qe.sh",
        }
        runtime = self.offline_runtime(cli)
        with patch.dict(os.environ, original, clear=True), runtime[0], runtime[1], runtime[2], \
                patch("qbox.cli.os.execvpe") as execute:
            self.assertEqual(cli.main(["--task", "6", "input with spaces.in"]), 0)
        forwarded = execute.call_args.args[2]
        for key in (
            "PATH", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME",
            "OMPI_MCA_btl", "QBOX_QE_ENV_SCRIPT",
        ):
            self.assertEqual(forwarded[key], original[key])
        self.assertEqual(forwarded["QBOX_PYTHON"], original["QBOX_PYTHON"])
        self.assertEqual(forwarded["_QBOX_OFFLINE_ROOT"], str(self.release))

    def test_offline_identity_uses_installed_package_branding(self):
        cli = importlib.import_module("qbox.cli")
        runtime = self.offline_runtime(cli)
        environment = {
            "_QBOX_OFFLINE_ROOT": str(self.release),
            "QBOX_PYTHON": str(self.release / "python/bin/python3"),
            "QBOX_NAME": "forged-name",
            "QBOX_VERSION": "forged-version",
        }
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), runtime[0], runtime[1], runtime[2], \
                contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["--version"]), 0)
        self.assertEqual(output.getvalue(), "qbox 0.1.0\n")

    def test_offline_rejects_marker_that_does_not_match_manifest(self):
        cli = importlib.import_module("qbox.cli")
        marker_path = self.release / "metadata/installed.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["manifest_sha256"] = "0" * 64
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        runtime = self.offline_runtime(cli)
        error = io.StringIO()
        environment = {
            "_QBOX_OFFLINE_ROOT": str(self.release),
            "QBOX_PYTHON": str(self.release / "python/bin/python3"),
        }
        with patch.dict(os.environ, environment, clear=True), runtime[0], runtime[1], runtime[2], \
                patch("qbox.cli.os.execvpe") as execute, contextlib.redirect_stderr(error):
            self.assertEqual(cli.main([]), 1)
        execute.assert_not_called()
        self.assertIn("安装标记", error.getvalue())

    def test_offline_rejects_release_id_that_does_not_match_manifest_identity(self):
        cli = importlib.import_module("qbox.cli")
        manifest_path = self.release / "metadata/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["identity"]["runtime_sha256"] = "d" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        marker_path = self.release / "metadata/installed.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        runtime = self.offline_runtime(cli)
        environment = {
            "_QBOX_OFFLINE_ROOT": str(self.release),
            "QBOX_PYTHON": str(self.release / "python/bin/python3"),
        }
        with patch.dict(os.environ, environment, clear=True), runtime[0], runtime[1], runtime[2], \
                patch("qbox.cli.os.execvpe") as execute, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main([]), 1)
        execute.assert_not_called()

    def test_branding_configuration_affects_help_and_version(self):
        cli = importlib.import_module("qbox.cli")
        with patch.dict(os.environ, {"QBOX_NAME": "custom-qbox", "QBOX_VERSION": "test"}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["--version"]), 0)
            self.assertEqual(output.getvalue(), "custom-qbox test\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["--help"]), 0)
            self.assertIn("custom-qbox --task", output.getvalue())

    def test_missing_bash_is_an_actionable_error(self):
        cli = importlib.import_module("qbox.cli")
        error = io.StringIO()
        with patch("qbox.cli.os.execvpe", side_effect=FileNotFoundError("bash")), \
                contextlib.redirect_stderr(error):
            self.assertEqual(cli.main([]), 127)
        self.assertIn("bash", error.getvalue())


if __name__ == "__main__":
    unittest.main()
