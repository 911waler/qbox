"""Validate upstream tar members before dereferencing into deterministic runtime tar."""

import gzip
import os
from pathlib import Path, PurePosixPath
import posixpath
import tarfile
import tempfile
import shutil
from contextlib import contextmanager

from .model import safe_payload_path, sha256_file


@contextmanager
def _seekable_tar(path):
    # Decompress once. Sorted output and link dereferences otherwise repeatedly
    # rewind gzip and make normalization quadratic in archive size.
    with Path(path).open("rb") as raw, tempfile.TemporaryFile() as spool:
        compressed = raw.read(2) == b"\x1f\x8b"
        raw.seek(0)
        if compressed:
            with gzip.GzipFile(fileobj=raw) as stream:
                shutil.copyfileobj(stream, spool)
        else:
            shutil.copyfileobj(raw, spool)
        spool.seek(0)
        with tarfile.open(fileobj=spool, mode="r:") as archive:
            yield archive


def normalize_runtime(upstream: Path, output: Path) -> dict:
    """Return hashes and link map; no upstream member is extracted onto the host."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    links = []
    with _seekable_tar(upstream) as source:
        members = {}
        for member in source:
            name = member.name.rstrip("/") if member.isdir() else member.name
            safe_payload_path(name)
            if name != "python" and not name.startswith("python/"):
                raise ValueError(f"outside Python install tree: {name}")
            if name in members:
                raise ValueError(f"duplicate tar member: {name}")
            if not (
                member.isfile() or member.isdir() or member.issym() or member.islnk()
            ):
                raise ValueError(f"unsupported tar member: {name}")
            members[name] = member

        def dereference(name, visited=()):
            if name in visited:
                raise ValueError(f"cyclic tar link: {name}")
            if name not in members:
                raise ValueError(f"missing tar link target: {name}")
            member = members[name]
            if not (member.issym() or member.islnk()):
                return name, member
            if member.linkname.startswith("/") or "\\" in member.linkname:
                raise ValueError(f"unsafe tar link: {name}")
            target = posixpath.normpath(
                posixpath.join(posixpath.dirname(name), member.linkname)
                if member.issym()
                else member.linkname
            )
            safe_payload_path(target)
            if not target.startswith("python/"):
                raise ValueError(f"escaping tar link: {name}")
            return dereference(target, (*visited, name))

        # Validate even omitted cache entries and ancestor paths before writing anything.
        resolved = {}
        for name in members:
            for parent in PurePosixPath(name).parents:
                if str(parent) in members and not members[str(parent)].isdir():
                    raise ValueError(f"non-directory tar ancestor: {parent}")
            resolved[name] = dereference(name)
        fd, temporary = tempfile.mkstemp(dir=output.parent, prefix=".runtime-")
        try:
            with (
                os.fdopen(fd, "wb") as raw,
                gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz,
                tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as target,
            ):
                for name in sorted(members):
                    if "__pycache__" in PurePosixPath(name).parts or name.endswith(
                        (".pyc", ".pyo")
                    ):
                        continue
                    origin, member = resolved[name]
                    if member.isdir() and origin != name:
                        raise ValueError(f"directory links are unsupported: {name}")
                    info = tarfile.TarInfo(name)
                    info.type = tarfile.DIRTYPE if member.isdir() else tarfile.REGTYPE
                    info.mode = member.mode & 0o777
                    info.size = 0 if member.isdir() else member.size
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    target.addfile(
                        info, None if member.isdir() else source.extractfile(member)
                    )
                    if origin != name:
                        links.append(
                            {"path": name, "target": origin, "mode": info.mode}
                        )
            os.replace(temporary, output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {
        "sha256": sha256_file(output),
        "size": output.stat().st_size,
        "links": links,
        "normalization": {
            "format": "tar.gz",
            "mtime": 0,
            "uid": 0,
            "gid": 0,
            "links": "dereferenced",
            "bytecode": "removed",
        },
    }
