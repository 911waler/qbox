#!/usr/bin/env python3
"""Build the deterministic installer using an explicit first-party allowlist."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
from pathlib import Path
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging/lightweight'))
from installer.__main__ import PAYLOAD_FILES, regular_file, wheel_metadata


def publish(path: Path, content: bytes) -> None:
    """Never overwrite an older artifact, even if another builder races us."""
    try:
        with path.open('xb') as stream:
            stream.write(content)
    except FileExistsError:
        regular_file(path)
        if path.read_bytes() != content:
            raise ValueError(f'output already exists with different content: {path}')


def build(wheel: Path, output: Path) -> Path:
    version = wheel_metadata(wheel)
    name = f'qbox-{version}-linux-installer'
    payload = {}
    for relative in PAYLOAD_FILES:
        source = ROOT / 'LICENSE' if relative == 'LICENSE' else ROOT / 'packaging/lightweight' / relative
        # Reject symlinks throughout the selected source path, not just its leaf.
        for path in (source, *source.relative_to(ROOT).parents):
            path = path if path.is_absolute() else ROOT / path
            if path.is_symlink():
                raise ValueError(f'source must not be a symlink: {path}')
        regular_file(source)
        payload[relative] = source.read_bytes()
    payload[f'packages/{wheel.name}'] = wheel.read_bytes()
    payload['SHA256SUMS'] = ''.join(f'{hashlib.sha256(data).hexdigest()}  {relative}\n'
                                  for relative, data in sorted(payload.items())).encode('utf-8')
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for relative, data in sorted(payload.items()):
                member = tarfile.TarInfo(f'{name}/{relative}')
                member.size = len(data)
                member.mode = 0o755 if relative == 'install.sh' else 0o644
                member.mtime = member.uid = member.gid = 0
                archive.addfile(member, io.BytesIO(data))
    content = buffer.getvalue()
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'{name}.tar.gz'
    checksum = f'{hashlib.sha256(content).hexdigest()}  {target.name}\n'.encode('ascii')
    # Check both existing destinations before adding either artifact.
    for path, expected in ((target, content), (Path(str(target) + '.sha256'), checksum)):
        if path.exists() or path.is_symlink():
            regular_file(path)
            if path.read_bytes() != expected:
                raise ValueError(f'output already exists with different content: {path}')
    publish(target, content)
    publish(Path(str(target) + '.sha256'), checksum)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build(args.wheel.absolute(), args.output.absolute()))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f'build-lightweight-installer: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
