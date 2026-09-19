"""Validate upstream tar members before dereferencing into deterministic runtime tar."""

import gzip
import re
import subprocess
import os
from pathlib import Path, PurePosixPath
import posixpath
import tarfile
import tempfile
import shutil
from contextlib import contextmanager

from .model import canonical_json, safe_payload_path, sha256_file


@contextmanager
def _seekable_tar(path):
    # Decompress once. Sorted output and link dereferences otherwise repeatedly
    # rewind gzip and make normalization quadratic in archive size.
    with Path(path).open("rb") as raw, tempfile.TemporaryFile() as spool:
        signature = raw.read(4)
        raw.seek(0)
        if signature == b"\x28\xb5\x2f\xfd":
            subprocess.run(
                ["zstd", "-dc", "--", str(path)],
                stdout=spool,
                stderr=subprocess.PIPE,
                check=True,
            )
        elif signature[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=raw) as stream:
                shutil.copyfileobj(stream, spool)
        else:
            shutil.copyfileobj(raw, spool)
        spool.seek(0)
        with tarfile.open(fileobj=spool, mode="r:") as archive:
            yield archive


def normalize_runtime(upstream: Path, output: Path) -> dict:
    """Return hashes and file-link map without extracting upstream members.

    Only file aliases are supported. Directory aliases fail closed (the pinned
    upstream has none); changing that contract requires a separately tested update.
    """
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
            origin, member = resolved[name]
            if member.isdir() and origin != name:
                raise ValueError(f"directory links are unsupported: {name}")
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


def preserve_runtime_materials(upstream: Path, output: Path, source: dict) -> dict:
    """Preserve full-archive metadata/licenses verbatim with a deterministic index.

    The index, not an output-directory glob, defines the material set. Validate
    the whole archive and all selected members before publishing any new index.
    Only files are copied to flat safe ASCII names; no tar member is extracted.
    Gzip/plain synthetic archives and the official zstd full archive are supported.
    """
    if sha256_file(upstream) != source["sha256"]:
        raise ValueError("companion archive SHA mismatch")
    output = Path(output)
    if output.is_symlink():
        raise ValueError("material output directory must not be a symlink")
    rows = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        _seekable_tar(upstream) as archive,
        tempfile.TemporaryDirectory(
            dir=output.parent, prefix=".materials-"
        ) as temporary,
    ):
        stage = Path(temporary)
        members = {}
        for member in archive:
            name = member.name.rstrip("/") if member.isdir() else member.name
            if (
                not name
                or name.startswith("/")
                or "\\" in name
                or any(part in ("", ".", "..") for part in name.split("/"))
            ):
                raise ValueError(f"unsafe companion member: {name}")
            if name in members:
                raise ValueError(f"duplicate companion member: {name}")
            if not (
                member.isfile() or member.isdir() or member.issym() or member.islnk()
            ):
                raise ValueError(f"unsupported companion member: {name}")
            members[name] = member
        destinations = set()
        for name in sorted(members):
            if name != "python/PYTHON.json" and not name.startswith("python/licenses/"):
                continue
            member = members[name]
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"companion material must be a regular file: {name}")
            for parent in PurePosixPath(name).parents:
                if str(parent) in members and not members[str(parent)].isdir():
                    raise ValueError(f"non-directory companion ancestor: {parent}")
            filename = re.sub(r"[^A-Za-z0-9._+-]", "_", name)
            safe_payload_path(filename)
            if filename in destinations:
                raise ValueError(f"ambiguous normalized material path: {filename}")
            destinations.add(filename)
            destination = stage / filename
            with archive.extractfile(member) as stream, destination.open("wb") as out:
                shutil.copyfileobj(stream, out)
            rows.append(
                {
                    "source_member": name,
                    "path": filename,
                    "sha256": sha256_file(destination),
                    "size": destination.stat().st_size,
                }
            )
        if not any(row["source_member"] == "python/PYTHON.json" for row in rows):
            raise ValueError("companion archive missing PYTHON.json")
        if not any(row["source_member"].startswith("python/licenses/") for row in rows):
            raise ValueError("companion archive missing license materials")
        index = stage / "index.json"
        index.write_bytes(canonical_json({"source": source, "materials": rows}))
        result = {
            "index": "index.json",
            "index_sha256": sha256_file(index),
            "count": len(rows),
        }
        output.mkdir(exist_ok=True)
        for row in rows:
            os.replace(stage / row["path"], output / row["path"])
        os.replace(index, output / "index.json")
    return result
