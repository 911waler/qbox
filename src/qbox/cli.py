"""Lightweight public entry point and legacy process boundary.

The compatibility process replaces this process rather than being piped through
it: terminal input, exit status, signal delivery and existing shell traps remain
owned by the calculation workflow. Help and task discovery need only stdlib.
"""

import os
from pathlib import Path
import sys

from . import __version__
from .registry import get_task, render_list


def _help(name):
    return f"""{name} - Quantum ESPRESSO workflow utilities

Usage:
  {name} [ACTION ...]
  {name} --task ID_OR_NAME [INPUT ...]
  {name} --list
  {name} --help
  {name} --version

Existing interactive menus and numeric invocations are preserved.
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
    name = os.environ.get("QBOX_NAME") or "qbox"
    if args and args[0] in ("--help", "-h"):
        print(_help(name), end="")
        return 0
    if args and args[0] in ("--version", "-V"):
        print(f"{name} {os.environ.get('QBOX_VERSION') or __version__}")
        return 0
    if args and args[0] == "--list":
        print(render_list(), end="")
        return 0

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
        env["QBOX_TASK_ID"] = str(task.id)
        args = args[2:]

    package_dir = Path(__file__).resolve().parent
    package_parent = str(package_dir.parent)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = package_parent + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    if not env.get("QBOX_PYTHON"):
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
