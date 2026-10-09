"""Lightweight public entry point and legacy process boundary.

The compatibility process replaces this process rather than being piped through
it: terminal input, exit status, signal delivery and existing shell traps remain
owned by the calculation workflow. Help and task discovery need only stdlib.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .registry import get_task, render_list


_INSTALL_MARKER_FIELDS = {
    "schema_version",
    "product",
    "release_id",
    "manifest_sha256",
    "state",
    "inventory_sha256",
}
_SHA256 = re.compile(r"[0-9a-f]{64}")


class _OfflineRuntimeError(ValueError):
    """Raised when a private offline marker does not describe this runtime."""


def _read_json_object(path, description):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _OfflineRuntimeError(f"无法读取{description}") from error
    if not isinstance(value, dict):
        raise _OfflineRuntimeError(f"{description}必须是 JSON 对象")
    return value


def _validate_offline_runtime(root_value, package_dir):
    root = Path(root_value)
    if not root.is_absolute() or root.resolve() != root:
        raise _OfflineRuntimeError("_QBOX_OFFLINE_ROOT 不是规范绝对路径")

    python_prefix = (root / "python").resolve()
    expected_python = (python_prefix / "bin/python3").resolve()
    configured_python = os.environ.get("QBOX_PYTHON")
    if not configured_python or Path(configured_python).resolve() != expected_python:
        raise _OfflineRuntimeError("QBOX_PYTHON 未指向本版本解释器")
    if Path(sys.prefix).resolve() != python_prefix:
        raise _OfflineRuntimeError("当前 Python 前缀不属于本版本")
    if not Path(package_dir).resolve().is_relative_to(python_prefix):
        raise _OfflineRuntimeError("qbox 包不属于本版本 Python")
    if not sys.flags.isolated:
        raise _OfflineRuntimeError("本版本 Python 未以隔离模式启动")

    metadata = root / "metadata"
    marker = _read_json_object(metadata / "installed.json", "安装标记")
    if set(marker) != _INSTALL_MARKER_FIELDS:
        raise _OfflineRuntimeError("安装标记字段不完整")
    if marker["schema_version"] != 1 or marker["product"] != "qbox":
        raise _OfflineRuntimeError("安装标记产品或版本无效")
    if marker["state"] not in ("prepared", "verified"):
        raise _OfflineRuntimeError("安装标记状态无效")
    for field in ("manifest_sha256", "inventory_sha256"):
        if not isinstance(marker[field], str) or _SHA256.fullmatch(marker[field]) is None:
            raise _OfflineRuntimeError(f"安装标记 {field} 无效")

    manifest_path = metadata / "manifest.json"
    manifest = _read_json_object(manifest_path, "发行清单")
    try:
        manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except OSError as error:
        raise _OfflineRuntimeError("无法读取发行清单") from error
    if marker["manifest_sha256"] != manifest_digest:
        raise _OfflineRuntimeError("安装标记中的清单摘要不匹配")
    if manifest.get("schema_version") != 1 or manifest.get("product") != "qbox":
        raise _OfflineRuntimeError("发行清单产品或版本无效")
    if not isinstance(marker["release_id"], str) or not marker["release_id"]:
        raise _OfflineRuntimeError("安装标记 release_id 无效")
    if manifest.get("release_id") != marker["release_id"]:
        raise _OfflineRuntimeError("安装标记与发行清单的 release_id 不匹配")
    if manifest.get("qbox_version") != __version__:
        raise _OfflineRuntimeError("发行清单版本与已安装 qbox 不匹配")
    identity = manifest.get("identity")
    if not isinstance(identity, dict):
        raise _OfflineRuntimeError("发行清单 identity 无效")
    canonical_identity = (
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    expected_release_id = f"{__version__}-{hashlib.sha256(canonical_identity).hexdigest()}"
    if marker["release_id"] != expected_release_id:
        raise _OfflineRuntimeError("release_id 与发行清单 identity 不匹配")


def _help(name):
    return f"""{name} - Quantum ESPRESSO workflow utilities

Usage:
  {name} [ACTION ...]
  {name} --task ID_OR_NAME [INPUT ...]
  {name} --list
  {name} kmesh NX NY NZ --format qe|wannier
  {name} --task wannier-input [CIF_OR_SCF_INPUT_OR_WIN]
  {name} --task wannier-input --config JSON --conflict cancel|backup
  {name} --help
  {name} --version

Task 11 generates Wannier90 inputs in the current directory.
Old task IDs 11–37 are now 12–38; IDs 0–10 and PW presets are unchanged.
Use --list to discover task IDs and names. --task selects a task explicitly;
arguments after its ID/name are passed to that task's existing workflow.

Configuration:
  QBOX_SHARED_ROOT        Shared dependency root for default Python/Multiwfn paths
  QBOX_PYTHON             Python executable for plots and analysis
  QBOX_MULTIWFN_HOME      Directory containing Multiwfn
  QBOX_PSEUDO_ROOT        Root directory of pseudopotential libraries
  QBOX_QE_ENV_SCRIPT      Optional QE environment script
  QBOX_ONEAPI_ENV_SCRIPT  Optional compiler/MPI environment script

QE, MPI, Multiwfn and pseudopotentials are external dependencies, not bundled.
"""


def main(argv=None):
    """Parse entry-only options; forward legacy workflow arguments unchanged."""
    args = list(sys.argv[1:] if argv is None else argv)
    offline_root = os.environ.get("_QBOX_OFFLINE_ROOT")
    package_dir = Path(__file__).resolve().parent
    if offline_root:
        try:
            _validate_offline_runtime(offline_root, package_dir)
        except _OfflineRuntimeError as error:
            print(f"qbox：离线安装标记无效：{error}。", file=sys.stderr)
            return 1
    name = "qbox" if offline_root else (os.environ.get("QBOX_NAME") or "qbox")
    if args and args[0] in ("--help", "-h"):
        print(_help(name), end="")
        return 0
    if args and args[0] in ("--version", "-V"):
        version = (
            __version__
            if offline_root
            else (os.environ.get("QBOX_VERSION") or __version__)
        )
        print(f"{name} {version}")
        return 0
    if args and args[0] == "--list":
        print(render_list(), end="")
        return 0

    if args and args[0] == "kmesh":
        from .io.kmesh import main as kmesh_main
        return kmesh_main(args[1:])

    env = os.environ.copy()
    env.pop("QBOX_TASK_ID", None)
    if args and args[0] == "--task":
        if len(args) < 2:
            print(f"{name}: --task requires a task ID or name; see --list", file=sys.stderr)
            return 2
        try:
            task = get_task(args[1])
        except ValueError as error:
            print(f"{name}: {error}; see --list", file=sys.stderr)
            return 2
        if task.slug == "wannier-input":
            from .io.wannier_menu import main as wannier_main
            return wannier_main(args[2:])
        env["QBOX_TASK_ID"] = str(task.id)
        args = args[2:]

    if not offline_root:
        package_parent = str(package_dir.parent)
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = package_parent + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    if not offline_root and not env.get("QBOX_PYTHON"):
        shared_root = env.get("QBOX_SHARED_ROOT")
        env["QBOX_PYTHON"] = str(Path(shared_root) / "python/bin/python3") if shared_root else sys.executable

    try:
        os.execvpe("bash", ["bash", str(package_dir / "legacy/entry.sh"), *args], env)
    except FileNotFoundError:
        print(f"{name}: bash is required to run the compatibility workflows", file=sys.stderr)
        return 127
    except OSError as error:
        print(f"{name}: cannot start bash workflow: {error}", file=sys.stderr)
        return 126
    return 0
