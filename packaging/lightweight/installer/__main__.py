"""Verify a lightweight distribution and dispatch its managed installation."""
from __future__ import annotations

import email.parser
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import sys
import zipfile

# This explicit list is shared with the builder; arbitrary repository contents
# (including dependency caches and third-party downloads) cannot enter a bundle.
PAYLOAD_FILES = (
    'LICENSE', 'README.zh-CN.md', 'install.sh', 'installer/__init__.py',
    'installer/__main__.py', 'installer/paths.py', 'installer/transaction.py',
)
_VERSION = re.compile(r'(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?'
                      r'(?:\.post[0-9]+)?(?:\.dev[0-9]+)?(?:\+[a-z0-9]+(?:[.-][a-z0-9]+)*)?')


def regular_file(path: Path) -> None:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f'bundle payload must be a regular file, not a link: {path}')


def wheel_metadata(wheel: Path) -> str:
    """Read identity from METADATA, rejecting ambiguous or unsafe wheel input."""
    regular_file(wheel)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate wheel archive entries')
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name:
                raise ValueError(f'unsafe wheel path: {name}')
        metadata = [name for name in names if name.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise ValueError('wheel must contain exactly one METADATA file')
        message = email.parser.BytesParser().parsebytes(archive.read(metadata[0]))
        if message.get_all('Name') != ['qbox']:
            raise ValueError('wheel METADATA Name must be qbox')
        versions = message.get_all('Version', [])
        if len(versions) != 1 or not _VERSION.fullmatch(versions[0]):
            raise ValueError('wheel METADATA Version is missing or invalid')
        version = versions[0]
        if metadata[0] != f'qbox-{version}.dist-info/METADATA':
            raise ValueError('wheel METADATA directory does not match its identity')
        # Check the wheel name against metadata, never derive release identity
        # from an unverified filename supplied by the caller.
        parts = wheel.name.removesuffix('.whl').split('-')
        if not wheel.name.endswith('.whl') or len(parts) not in (5, 6) or parts[:2] != ['qbox', version]:
            raise ValueError('wheel filename does not match METADATA identity')
        return version


def verify_bundle(root: Path) -> tuple[Path, str, str]:
    actual = set()
    for path in root.rglob('*'):
        relative = path.relative_to(root).as_posix()
        if relative in {'installer', 'packages'} and stat.S_ISDIR(path.lstat().st_mode):
            continue
        regular_file(path)
        actual.add(relative)
    wheels = {name for name in actual if name.startswith('packages/') and name.endswith('.whl') and name.count('/') == 1}
    expected = set(PAYLOAD_FILES) | wheels
    if len(wheels) != 1 or actual != expected | {'SHA256SUMS'}:
        raise ValueError('bundle file list must contain only the documented payload and exactly one wheel')
    manifest = {}
    for line in (root / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match:
            raise ValueError('invalid SHA256SUMS line')
        digest, name = match.groups()
        if name in manifest:
            raise ValueError(f'duplicate SHA256SUMS entry: {name}')
        manifest[name] = digest
    if set(manifest) != expected:
        raise ValueError('SHA256SUMS file list does not match the required payload')
    for name, digest in manifest.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'bundle SHA256 mismatch: {name}')
    wheel_name = next(iter(wheels))
    wheel = root / wheel_name
    version = wheel_metadata(wheel)
    return wheel, manifest[wheel_name], version


def print_path_guidance(entry: Path, *, mode: str) -> None:
    line = f'export PATH={shlex.quote(str(entry.parent))}:"$PATH"'
    print(f'qbox command: {entry}')
    print('Add this line once to your shell configuration, or run it in this shell:')
    print(line)
    print('hash -r\ncommand -v qbox\nqbox --help')
    print('Check aliases and earlier qbox commands if command -v selects another installation.')
    if mode == 'system':
        print('Administrator login-shell example (inspect any existing file first):')
        print('( set -C; printf \'%s\\n\' ' + shlex.quote(line) + ' > /etc/profile.d/qbox.sh ) &&')
        print('  chmod 0644 /etc/profile.d/qbox.sh')
    print('Batch jobs may call the absolute command path. No shell files were modified.')


def main(argv: list[str] | None = None) -> int:
    try:
        # Version preflight in install.sh precedes importing this module.
        if sys.version_info < (3, 10):
            raise ValueError('Python 3.10+ is required')
        root = Path(__file__).resolve().parent.parent
        wheel, digest, version = verify_bundle(root)
        caller = os.environ.pop('QBOX_INSTALL_CALLER_CWD', None)
        if caller:
            os.chdir(caller)
        from .paths import parse_options
        from .transaction import install
        options = parse_options(sys.argv[1:] if argv is None else argv, uid=os.geteuid(),
                                home=Path.home(), default_python=Path(sys.executable))
        print(f'Installing qbox {version} from verified local wheel (SHA256 {digest}).', flush=True)
        entry = install(options, wheel=wheel, wheel_sha256=digest)
        print_path_guidance(entry, mode=options.mode)
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f'qbox-installer: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
