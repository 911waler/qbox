"""Interpret and validate paths for the lightweight qbox installer.

Option parsing deliberately keeps the selected Python path lexical. A virtual
environment's ``bin/python`` is commonly a symlink, but the launcher must keep
using that environment instead of the base interpreter to which it resolves.
Filesystem validation resolves paths separately when reasoning about overlap
or system-wide access.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import stat


@dataclass(frozen=True)
class InstallOptions:
    """Fully interpreted installer options."""

    mode: str
    prefix: Path
    bin_dir: Path
    python: Path


class _ModeAction(argparse.Action):
    """Argparse action that rejects a repeated selection of the same mode."""

    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            parser.error("installation mode may be selected only once")
        setattr(namespace, self.dest, self.const)


def _path_argument(value: str | os.PathLike[str], *, option: str) -> Path:
    text = os.fspath(value)
    if not text or not text.strip():
        raise ValueError(f"{option} path must not be empty")
    if "\n" in text or "\r" in text:
        raise ValueError(f"{option} path must not contain a line break")
    path = Path(text).expanduser().absolute()
    if path == Path("/"):
        raise ValueError(f"{option} path must not be the root directory")
    return path


def parse_options(
    argv: list[str], *, uid: int, home: Path, default_python: Path
) -> InstallOptions:
    """Parse mode and paths without reading or changing the filesystem."""

    parser = argparse.ArgumentParser(prog="qbox-installer", allow_abbrev=False)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--user", dest="mode", action=_ModeAction, nargs=0, const="user"
    )
    modes.add_argument(
        "--system", dest="mode", action=_ModeAction, nargs=0, const="system"
    )
    parser.add_argument("--prefix")
    parser.add_argument("--bin-dir")
    parser.add_argument("--python")
    args = parser.parse_args(argv)

    if args.mode == "user" and uid == 0:
        raise ValueError("root must not use --user; use a normal account or --system")
    if args.mode == "system" and uid != 0:
        raise ValueError("--system requires effective UID 0")

    if args.prefix is not None:
        prefix = _path_argument(args.prefix, option="--prefix")
    elif args.mode == "user":
        prefix = _path_argument(home / ".local/share/qbox", option="default prefix")
    else:
        prefix = Path("/opt/qbox")

    bin_dir = (
        _path_argument(args.bin_dir, option="--bin-dir")
        if args.bin_dir is not None
        else prefix / "bin"
    )
    python = _path_argument(
        args.python if args.python is not None else default_python,
        option="--python",
    )
    return InstallOptions(args.mode, prefix, bin_dir, python)


def _stat_path(path: Path, *, follow_symlinks: bool = True):
    """Small stat seam used by focused permission-policy tests."""

    return os.stat(path, follow_symlinks=follow_symlinks)


def _canonical(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise OSError(f"cannot resolve installer path {path}: {error}") from error


def _is_within(path: Path, parent: Path) -> bool:
    """Return whether *path* is equal to or below *parent* by components."""

    return path == parent or parent in path.parents


def _validate_overlap(prefix: Path, bin_dir: Path) -> None:
    canonical_prefix = _canonical(prefix)
    canonical_bin = _canonical(bin_dir)
    entry = _canonical(bin_dir / "qbox")

    if _is_within(canonical_prefix, canonical_bin):
        raise ValueError(
            f"unsafe path overlap: prefix {prefix} is inside command directory "
            f"{bin_dir}"
        )

    for name in ("venv", "releases", "current", ".install-lock", ".qbox-install.json"):
        reserved = _canonical(prefix / name)
        if _is_within(entry, reserved):
            raise ValueError(
                f"command entry {bin_dir / 'qbox'} is inside reserved {name} path "
                f"{prefix / name}"
            )


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path
    while True:
        try:
            info = _stat_path(candidate, follow_symlinks=True)
        except (FileNotFoundError, NotADirectoryError):
            if candidate.is_symlink():
                raise ValueError(f"path contains dangling symlink: {candidate}")
            parent = candidate.parent
            if parent == candidate:
                raise OSError(f"no existing ancestor for path {path}")
            candidate = parent
            continue
        except OSError as error:
            raise OSError(f"cannot inspect path ancestor {candidate}: {error}") from error
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"path ancestor is not a directory: {candidate}")
        return candidate


def _validate_user_destination(path: Path) -> None:
    ancestor = _nearest_existing_directory(path)
    if not os.access(ancestor, os.W_OK | os.X_OK):
        raise OSError(
            f"path ancestor must be writable and traversable: {ancestor}"
        )


def _system_mode_error(path: Path, mode: int, reason: str) -> OSError:
    return OSError(
        f"system path ancestor {path} has unsafe mode "
        f"{stat.S_IMODE(mode):04o}: {reason}"
    )


def _validate_system_chain(
    path: Path, *, require_leaf: bool = False, directory_leaf: bool = False,
    python_leaf: bool = False
) -> None:
    """Validate every component, including each intermediate symlink expansion.

    Resolve one component at a time: collapsing a link target with resolve() or
    normpath() would hide writable intermediate directories (including before ..).
    Keep this traversal separate from the selected interpreter's lexical identity.
    """

    pending = deque(path.parts[1:])
    component = Path(path.anchor)
    saw_leaf = False
    links = 0
    while True:
        try:
            info = _stat_path(component, follow_symlinks=False)
        except FileNotFoundError:
            break
        except OSError as error:
            raise OSError(f"cannot inspect system path {component}: {error}") from error

        leaf = not pending
        mode = info.st_mode
        if info.st_uid != 0:
            raise OSError(
                f"system path ancestor {component} is owned by uid {info.st_uid}; "
                "expected uid 0"
            )
        if stat.S_ISLNK(mode):
            links += 1
            if links > 40:
                raise OSError(f"too many symlink expansions in system path: {path}")
            target = Path(os.readlink(component))
            pending.extendleft(reversed(target.parts[1:] if target.is_absolute() else target.parts))
            component = Path(target.anchor) if target.is_absolute() else component.parent
            continue
        if leaf and directory_leaf and not stat.S_ISDIR(mode):
            raise ValueError(f"system destination must be a directory: {component}")
        if not leaf and not stat.S_ISDIR(mode):
            raise ValueError(f"system path ancestor is not a directory: {component}")
        if mode & stat.S_IWGRP:
            raise _system_mode_error(component, mode, "group-writable")
        if mode & stat.S_IWOTH:
            raise _system_mode_error(component, mode, "other-writable")
        if stat.S_ISDIR(mode):
            if not mode & stat.S_IXOTH:
                raise _system_mode_error(
                    component, mode, "other users cannot traverse this directory"
                )
        elif python_leaf:
            if not mode & stat.S_IXOTH:
                raise OSError(
                    f"Python interpreter resolved target {component} must be "
                    "executable by other users"
                )

        if leaf:
            saw_leaf = True
            break
        part = pending.popleft()
        component = component.parent if part == ".." else component / part

    if require_leaf and not saw_leaf:
        raise ValueError(f"required system path does not exist: {path}")


def _validate_python(path: Path) -> Path:
    try:
        info = _stat_path(path, follow_symlinks=True)
    except FileNotFoundError as error:
        raise ValueError(f"Python interpreter does not exist: {path}") from error
    except OSError as error:
        raise OSError(f"cannot inspect Python interpreter {path}: {error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Python interpreter must be a regular file: {path}")
    if not os.access(path, os.X_OK):
        raise OSError(f"Python interpreter is not executable: {path}")
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise OSError(f"cannot resolve Python interpreter {path}: {error}") from error


def _validate_option_path(path: Path, *, label: str) -> None:
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path: {path}")
    text = os.fspath(path)
    if "\n" in text or "\r" in text:
        raise ValueError(f"{label} must not contain a line break")
    if path == Path("/"):
        raise ValueError(f"{label} must not be the root directory")


def validate_paths(options: InstallOptions) -> None:
    """Validate overlap and current filesystem policy without changing it."""

    if options.mode not in {"user", "system"}:
        raise ValueError(f"unknown installation mode: {options.mode}")
    _validate_option_path(options.prefix, label="prefix")
    _validate_option_path(options.bin_dir, label="bin directory")
    _validate_option_path(options.python, label="Python interpreter")
    _validate_overlap(options.prefix, options.bin_dir)
    _validate_python(options.python)

    if options.mode == "user":
        _validate_user_destination(options.prefix)
        _validate_user_destination(options.bin_dir)
        return

    for destination in (options.prefix, options.bin_dir):
        _validate_system_chain(destination, directory_leaf=True)
    _validate_system_chain(options.python, require_leaf=True, python_leaf=True)
