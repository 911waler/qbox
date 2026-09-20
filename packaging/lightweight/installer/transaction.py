"""Create a fixed-path environment, then publish its command without replacement.

Failed transactions deliberately retain their preparing record and environment.
Only this transaction's proven lock is removed; interrupted installations require
manual inspection rather than recursive deletion or automatic lock stealing.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import threading
import uuid

from .paths import InstallOptions, validate_paths


def _environment() -> dict[str, str]:
    removed = {"PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIP_ROOT"}
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("QBOX_", "_QBOX_", "PYTHON")) and key not in removed}


def _pip_environment(python: Path, env: dict[str, str]) -> dict[str, str]:
    """Snapshot pip's transport configuration, disabling all write destinations.

    Let pip discover global/user/site/explicit files with its own precedence.
    Read only its Configuration object: running ``pip config list`` would also
    activate global CLI settings such as an externally directed log file.
    Subsequent pip commands use no config files and only transport options.
    """
    settings = json.loads(_run([str(python), "-I", "-c",
        "import json; from pip._internal.configuration import Configuration; "
        "config=Configuration(isolated=False); config.load(); "
        "print(json.dumps(dict(config.items())))"], env=env))
    transport = {
        "index-url", "extra-index-url", "no-index", "find-links",
        "trusted-host", "proxy", "cert", "client-cert", "timeout", "retries",
        "keyring-provider",
    }
    controlled = {key: value for key, value in env.items()
                  if not key.startswith("PIP_")}
    for section in ("global", "install", ":env:"):
        for name in transport:
            value = settings.get(f"{section}.{name}")
            if value:
                controlled["PIP_" + name.upper().replace("-", "_")] = value
    controlled["PIP_CONFIG_FILE"] = os.devnull
    controlled["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return controlled


def _run(args: list[str], *, env: dict[str, str], cwd: Path | str = "/") -> str:
    process = subprocess.Popen(args, env=env, cwd=cwd, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate()
    except BaseException:
        # pip can have build children; do not leave them writing after interruption.
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, args, stdout, stderr)
    return stdout


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def _inode(path: Path) -> tuple[int, int]:
    info = path.lstat()
    return info.st_dev, info.st_ino


def _regular_owned(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError(f"not an owned regular file: {path}")


def _identity(options: InstallOptions, wheel_sha256: str) -> dict:
    return {"schema_version": 1, "mode": options.mode, "uid": os.geteuid(),
            "prefix": str(options.prefix.resolve()),
            "bin_dir": str(options.bin_dir.resolve()),
            # Preserve a supplied venv Python's lexical identity.
            "python": str(options.python.absolute()), "wheel_sha256": wheel_sha256,
            "venv_python": str(options.prefix.resolve() / "venv/bin/python")}


def _read_record(path: Path) -> dict:
    _regular_owned(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"damaged installation record {path}; inspect manually") from error
    if not isinstance(record, dict):
        raise ValueError(f"damaged installation record {path}; inspect manually")
    return record


def _write_record(path: Path, record: dict, *, previous: dict | None = None) -> None:
    content = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if previous is None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return
    old_inode = _inode(path)
    if _read_record(path) != previous:
        raise ValueError(f"installation record changed during transaction: {path}")
    fd, name = tempfile.mkstemp(prefix=".qbox-record-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        if _inode(path) != old_inode or _read_record(path) != previous:
            raise ValueError(f"installation record changed during transaction: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _interrupts():
    previous = {}
    def interrupted(number, frame):
        # selectors/communicate retry InterruptedError; use a distinct exception
        # so an actual signal reaches _run's process-group cleanup.
        raise RuntimeError(f"installation interrupted by signal {number}")
    if threading.current_thread() is threading.main_thread():
        for number in (signal.SIGINT, signal.SIGTERM):
            previous[number] = signal.signal(number, interrupted)
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextmanager
def _lock(prefix: Path):
    lock = prefix / ".install-lock"
    token = uuid.uuid4().hex
    try:
        lock.mkdir(mode=0o755)
    except FileExistsError as error:
        raise FileExistsError(f"installation lock already exists: {lock}; do not remove an active lock; inspect manually") from error
    identity = _inode(lock)
    token_path = lock / "token"
    # If creating the token fails, retain the unproven lock conservatively.
    with token_path.open("x", encoding="ascii") as stream:
        stream.write(token)
    try:
        yield token
    finally:
        try:
            _regular_owned(token_path)
            if _inode(lock) == identity and token_path.read_text(encoding="ascii") == token:
                token_path.unlink()
                lock.rmdir()
            else:
                raise ValueError("lock ownership changed")
        except (OSError, ValueError) as error:
            raise OSError(f"lock retained at {lock}: ownership changed or unexpected contents; inspect manually") from error


def _mkdir(path: Path, *, shared: bool) -> None:
    """Only adjust permissions of directories this invocation actually creates."""
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"not a directory: {path}")
        return
    _mkdir(path.parent, shared=shared)
    try:
        path.mkdir(mode=0o755)
    except FileExistsError:
        if not path.is_dir():
            raise
    else:
        if shared:
            path.chmod(0o755)


def _share_new_venv(venv: Path) -> None:
    for directory, dirs, files in os.walk(venv, followlinks=False):
        Path(directory).chmod(0o755)
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                mode = path.stat().st_mode
                path.chmod(0o755 if mode & 0o111 else 0o644)


def _versions(python: Path, env: dict[str, str]) -> dict[str, str]:
    return json.loads(_run([str(python), "-I", "-c",
        "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions()}))"], env=env))


_CIF = """data_silicon
_cell_length_a 5.43
_cell_length_b 5.43
_cell_length_c 5.43
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0 0 0
Si2 Si 0.25 0.25 0.25
"""


def _smoke(options: InstallOptions, env: dict[str, str], *, entry: Path | None = None) -> None:
    python = options.prefix / "venv/bin/python"
    with tempfile.TemporaryDirectory(prefix="qbox-install-check-") as temporary:
        work = Path(temporary)
        check_env = dict(env, MPLCONFIGDIR=str(work / "matplotlib"),
                         XDG_CACHE_HOME=str(work / "cache"))
        _run([str(python), "-I", "-c",
              "import sys,numpy,scipy,matplotlib,seekpath,pymatgen.core,ase; "
              "from pathlib import Path; "
              "assert Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve()",
              str(options.prefix / "venv")], env=check_env, cwd=work)
        _run([str(python), "-I", "-m", "pip", "check"], env=check_env, cwd=work)
        command = [str(entry)] if entry else [str(python), "-I", "-m", "qbox"]
        _run(command + ["--help"], env=check_env, cwd=work)
        listing = _run(command + ["--list"], env=check_env, cwd=work)
        if "cif-to-vasp" not in listing:
            raise ValueError("qbox task listing is incomplete")
        (work / "silicon.cif").write_text(_CIF, encoding="ascii")
        _run([str(python), "-I", "-m", "qbox.io.convert_basic", "cif2vasp",
              "silicon.cif", "POSCAR"], env=check_env, cwd=work)
        output = (work / "POSCAR").read_text()
        if "Si" not in output or "0.250000000000" not in output:
            raise ValueError("CIF conversion smoke test produced unexpected output")


def _check_identity(options: InstallOptions, record: dict, wheel_sha256: str) -> None:
    for key, value in _identity(options, wheel_sha256).items():
        if record.get(key) != value:
            raise ValueError(f"installation identity mismatch ({key}); use a new prefix/bin-dir")
    if record.get("state") != "ready":
        raise ValueError(f"installation is {record.get('state')!r} at {options.prefix}; inspect retained files and entry manually before recovery; use a new prefix/bin-dir")


def verify_install(options: InstallOptions, *, wheel_sha256: str) -> None:
    """Verify matching ownership, distribution versions, entry hash and workflows."""
    _validate(options)
    record = _read_record(options.prefix / ".qbox-install.json")
    _check_identity(options, record, wheel_sha256)
    entry = options.bin_dir / "qbox"
    _regular_owned(entry)
    if not os.access(entry, os.X_OK) or _digest(entry) != record.get("entry_sha256"):
        raise ValueError(f"damaged command entry: {entry}; inspect manually")
    venv = options.prefix / "venv"
    if venv.is_symlink() or not venv.is_dir() or venv.stat().st_uid != os.geteuid():
        raise ValueError(f"not an owned environment: {venv}")
    env = _pip_environment(venv / "bin/python", _environment())
    if _versions(venv / "bin/python", env) != record.get("distributions"):
        raise ValueError(f"installed distribution versions changed: {venv}")
    _smoke(options, env, entry=entry)


def _validate(options: InstallOptions) -> None:
    if (options.mode == "user" and os.geteuid() == 0) or (options.mode == "system" and os.geteuid() != 0):
        raise ValueError("--user requires a normal account; --system requires effective UID 0")
    validate_paths(options)
    if options.prefix.is_symlink():
        raise ValueError(f"installation prefix must not be a symlink: {options.prefix}")
    if options.prefix.exists() and options.prefix.stat().st_uid != os.geteuid():
        raise ValueError(f"installation prefix has a different owner: {options.prefix}")


def install(options: InstallOptions, *, wheel: Path, wheel_sha256: str) -> Path:
    """Install a local wheel with scientific extras and return its ready command.

    The CLI owns this process: constrain all system transaction creation, including
    inherited venv/ensurepip/pip subprocesses, before any files or commands exist.
    Restore the caller's mask on reuse, failure and interruption as well as success.
    """
    if options.mode != "system":
        return _install(options, wheel=wheel, wheel_sha256=wheel_sha256)
    previous_mask = os.umask(0o022)
    try:
        return _install(options, wheel=wheel, wheel_sha256=wheel_sha256)
    finally:
        os.umask(previous_mask)


def _install(options: InstallOptions, *, wheel: Path, wheel_sha256: str) -> Path:
    _validate(options)
    if _digest(wheel) != wheel_sha256:
        raise ValueError(f"wheel SHA256 digest mismatch: {wheel}")
    prefix, entry = options.prefix, options.bin_dir / "qbox"
    marker = prefix / ".qbox-install.json"
    if os.path.lexists(entry) and not os.path.lexists(marker):
        raise FileExistsError(f"command entry already exists: {entry}; choose another bin-dir")
    if prefix.exists() and not os.path.lexists(marker):
        if any(prefix.iterdir()):
            raise ValueError(f"unmarked nonempty prefix {prefix}; existing files retained; inspect manually")
    env = _environment()
    try:
        _run([str(options.python), "-I", "-c",
              "import sys,venv,ensurepip; assert sys.version_info >= (3,10), 'Python 3.10+ is required'"], env=env)
    except subprocess.CalledProcessError as error:
        raise ValueError(f"Python 3.10+ with venv/pip (ensurepip) support is required: {options.python}\n{error.stderr}") from error
    _mkdir(prefix, shared=options.mode == "system")
    prefix_inode = _inode(prefix)
    with _interrupts(), _lock(prefix) as token:
        if os.path.lexists(marker):
            verify_install(options, wheel_sha256=wheel_sha256)
            return entry
        if set(path.name for path in prefix.iterdir()) != {".install-lock"}:
            raise ValueError(f"prefix changed during installation: {prefix}; inspect manually")
        record = dict(_identity(options, wheel_sha256), state="preparing",
                      transaction_token=token, distributions={}, entry_sha256=None)
        try:
            _write_record(marker, record)
            python = prefix / "venv/bin/python"
            _run([str(options.python), "-I", "-m", "venv", str(prefix / "venv")], env=env)
            env = _pip_environment(python, env)
            _run([str(python), "-I", "-m", "pip", "install", "--no-cache-dir", "--no-user",
                  str(wheel.absolute()) + "[analysis,structure]"], env=env)
            if options.mode == "system":
                _share_new_venv(prefix / "venv")
            _smoke(options, env)
            distributions = _versions(python, env)
            if _inode(prefix) != prefix_inode or _read_record(marker) != record:
                raise ValueError("installation ownership changed before command publication")
            _mkdir(options.bin_dir, shared=options.mode == "system")
            validate_paths(options)
            # Existing qbox.install publishes with an atomic no-overwrite hard link.
            _run([str(python), "-I", "-m", "qbox.install", "--bin-dir", str(options.bin_dir), "--no-reuse"], env=env)
            _regular_owned(entry)
            _smoke(options, env, entry=entry)
            ready = dict(record, state="ready", distributions=distributions,
                         entry_sha256=_digest(entry))
            _write_record(marker, ready, previous=record)
            return entry
        except BaseException as error:
            detail = error.stderr[-4000:] if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
            raise OSError(f"installation failed: {detail}\nFiles retained at {prefix}; any command at {entry} is retained. Inspect the preparing record, environment and command manually; retry with a new prefix/bin-dir. No automatic cleanup or lock stealing is performed.") from error
