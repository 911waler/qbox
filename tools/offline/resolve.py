"""Maintainer resolver. Candidate locks are reviewed before copying into packaging/offline.

Public helpers consume wheel paths, explicit marker environments and verified upstream
sources. Locks are maintainer inputs, not manifest objects: builder must add license
IDs and payload paths after Task 3 audits and bind actual shipped lock bytes.
"""

from collections import deque
from datetime import date, datetime, timezone
import difflib
from email.parser import BytesParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import zipfile

from packaging.requirements import Requirement
from packaging.tags import cpython_tags, compatible_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from .archive import normalize_runtime, preserve_runtime_materials, read_newc, repair_runtime
from .model import canonical_json, sha256_file


def target_tags():
    platforms = [f"manylinux_2_{minor}_x86_64" for minor in range(5, 29)]
    platforms += ["manylinux1_x86_64", "manylinux2010_x86_64", "manylinux2014_x86_64"]
    return set(cpython_tags((3, 12), abis=["cp312"], platforms=platforms)) | set(
        compatible_tags((3, 12), interpreter="cp312", platforms=platforms)
    )


def allowed_wheel(filename, target_tags):
    try:
        return bool(parse_wheel_filename(filename)[3] & target_tags)
    except ValueError:
        return False


def wheel_metadata(path):
    path = Path(path)
    if not allowed_wheel(path.name, target_tags()):
        raise ValueError(f"incompatible or non-wheel asset: {path.name}")
    parsed_name, parsed_version, _, tags = parse_wheel_filename(path.name)
    with zipfile.ZipFile(path) as wheel:
        names = [
            n
            for n in wheel.namelist()
            if n.count("/") == 1 and n.endswith(".dist-info/METADATA")
        ]
        if len(names) != 1:
            raise ValueError(f"wheel must contain one METADATA: {path.name}")
        metadata = BytesParser().parsebytes(wheel.read(names[0]))
    name = canonicalize_name(metadata["Name"] or "")
    version = metadata["Version"]
    if name != parsed_name or Version(version) != parsed_version:
        raise ValueError(f"wheel filename/METADATA mismatch: {path.name}")
    requires = metadata.get_all("Requires-Dist", [])
    for requirement in requires:
        if Requirement(requirement).url:
            raise ValueError(f"direct URL dependency forbidden: {requirement}")
    return {
        "name": name,
        "version": version,
        "filename": path.name,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "tags": sorted(map(str, tags)),
        "requires_dist": requires,
    }


def wheel_closure(wheels, roots, environment):
    packages = {}
    for path in wheels:
        package = wheel_metadata(path)
        if package["name"] in packages:
            raise ValueError(f'duplicate normalized package: {package["name"]}')
        packages[package["name"]] = package
    env = dict(environment)
    # Explicit deterministic target defaults, never maintainer sys_tags/markers.
    defaults = {
        "implementation_name": "cpython",
        "implementation_version": "3.12.14",
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": "Linux",
        "platform_version": "",
        "python_full_version": "3.12.14",
        "python_version": "3.12",
        "sys_platform": "linux",
    }
    defaults.update(env)
    env = defaults
    queue = deque(Requirement(root) for root in roots)
    expanded = set()
    selected = set()
    while queue:
        req = queue.popleft()
        if req.url:
            raise ValueError(f"direct URL forbidden: {req}")
        name = canonicalize_name(req.name)
        if name not in packages:
            raise ValueError(f"missing wheel: {name}")
        package = packages[name]
        if not req.specifier.contains(package["version"], prereleases=True):
            raise ValueError(f'version mismatch: {req}, got {package["version"]}')
        selected.add(name)
        for extra in {""} | set(req.extras):
            if (name, extra) in expanded:
                continue
            expanded.add((name, extra))
            for text in package["requires_dist"]:
                child = Requirement(text)
                if child.marker is None or child.marker.evaluate(
                    {**env, "extra": extra}
                ):
                    queue.append(child)
    return [packages[name] for name in sorted(selected)]


def cache_asset(url, sha256, cache, *, local=None):
    if not re.fullmatch("[0-9a-f]{64}", sha256):
        raise ValueError("missing verified SHA-256")
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / sha256
    if target.exists():
        if sha256_file(target) != sha256:
            raise ValueError(f"cached SHA mismatch: {target}")
        return target
    fd, temporary = tempfile.mkstemp(dir=cache, prefix=".download-")
    try:
        with os.fdopen(fd, "wb") as output:
            if local is not None:
                with Path(local).open("rb") as source:
                    shutil.copyfileobj(source, output)
            else:
                if not url.startswith("https://"):
                    raise ValueError("upstream asset must use HTTPS")
                with urlopen(
                    Request(url, headers={"User-Agent": "qbox-offline-resolver/1"}),
                    timeout=120,
                ) as source:
                    shutil.copyfileobj(source, output)
        if sha256_file(Path(temporary)) != sha256:
            raise ValueError(f"asset SHA mismatch: {url}")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def select_runtime(releases, as_of):
    candidates = []
    pattern = re.compile(
        r"cpython-(3\.12\.\d+)\+(\d{8})-x86_64-unknown-linux-gnu-install_only\.tar\.gz"
    )
    for release in releases:
        if (
            release.get("draft")
            or release.get("prerelease")
            or release["published_at"][:10] > as_of
        ):
            continue
        for asset in release["assets"]:
            match = pattern.fullmatch(asset["name"])
            if (
                match
                and match[2] == release["tag_name"]
                and match[2] <= as_of.replace("-", "")
            ):
                candidates.append((Version(match[1]), match[2], asset))
    if not candidates:
        raise ValueError("no approved CPython 3.12 baseline runtime")
    version, build, asset = max(candidates, key=lambda row: row[:2])
    digest = asset.get("digest") or ""
    if not re.fullmatch("sha256:[0-9a-f]{64}", digest):
        raise ValueError("selected runtime has no official SHA-256 digest")
    url = asset["browser_download_url"]
    expected = f'https://github.com/astral-sh/python-build-standalone/releases/download/{build}/{asset["name"]}'
    if url != expected:
        raise ValueError("runtime source is not the official pinned release asset")
    return {
        "version": str(version),
        "build": build,
        "filename": asset["name"],
        "url": url,
        "sha256": digest[7:],
    }


def write_candidates(lock_directory, output, contents):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, data in contents.items():
        destination = output / name
        destination.write_bytes(data)
        previous = Path(lock_directory) / name
        old = previous.read_text() if previous.exists() else ""
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(True),
                data.decode().splitlines(True),
                fromfile=str(previous),
                tofile=str(destination),
            )
        )
        result[name] = {
            "path": str(destination),
            "sha256": sha256_file(destination),
            "diff": diff,
        }
    return result


def requirements_bytes(packages):
    return "".join(
        f'{p["name"]}=={p["version"]} --hash=sha256:{p["sha256"]}\n' for p in packages
    ).encode()


def pip_environment(environment=None):
    return {
        **{
            k: v
            for k, v in (os.environ if environment is None else environment).items()
            if not k.startswith("PIP_")
        },
        "PIP_CONFIG_FILE": "/dev/null",
    }


def container_command(image, root, command, *, network):
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("container image must use a fixed digest")
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "bridge" if network else "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-e",
        "HOME=/tmp",
        "-e",
        "PIP_CONFIG_FILE=/dev/null",
        "-v",
        f"{Path(root).resolve()}:/work",
        "-w",
        "/work",
        image,
        *command,
    ]


def pypi_source(package, document):
    matches = [
        asset for asset in document["urls"] if asset["filename"] == package["filename"]
    ]
    if len(matches) != 1:
        raise ValueError(
            f'wheel absent/ambiguous in PyPI metadata: {package["filename"]}'
        )
    asset = matches[0]
    if asset["digests"]["sha256"] != package["sha256"]:
        raise ValueError(f'PyPI SHA mismatch: {package["filename"]}')
    if not asset["url"].startswith("https://files.pythonhosted.org/"):
        raise ValueError("unexpected PyPI asset source")
    return {
        "url": asset["url"],
        "filename": package["filename"],
        "sha256": package["sha256"],
    }


def snapshot(url, directory, filename):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    # Metadata snapshots persist exact bytes; a replay does not silently refresh them.
    if not path.exists():
        with urlopen(
            Request(url, headers={"User-Agent": "qbox-offline-resolver/1"}), timeout=120
        ) as response:
            data = response.read()
        path.write_bytes(data)
        (directory / (filename + ".provenance.json")).write_bytes(
            canonical_json(
                {
                    "url": url,
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": sha256_file(path),
                }
            )
        )
    provenance = json.loads((directory / (filename + ".provenance.json")).read_text())
    if provenance["url"] != url or provenance["sha256"] != sha256_file(path):
        raise ValueError(f"metadata snapshot provenance mismatch: {path}")
    return path, provenance


def discover_runtime(settings, metadata):
    as_of = date.today().isoformat()
    try:
        path, provenance = snapshot(
            "https://api.github.com/repos/astral-sh/python-build-standalone/releases?per_page=100",
            metadata,
            "github-releases.json",
        )
    except HTTPError as error:
        # Only the controller-authorized GitHub API rate-limit acquisition failure
        # may change selection scope. Integrity/JSON/selection errors propagate.
        if error.code != 403:
            raise
        remaining = (
            error.headers.get("X-RateLimit-Remaining") if error.headers else None
        )
        body = error.read().decode("utf-8", errors="replace").lower()
        if (
            remaining != "0"
            and "rate limit exceeded" not in body
            and "secondary rate limit" not in body
        ):
            raise
        # Explicit, pinned official HTML fallback, never an unverified mirror.
        tag = settings["fallback_release_tag"]
        release_url = (
            f"https://github.com/astral-sh/python-build-standalone/releases/tag/{tag}"
        )
        page, page_provenance = snapshot(
            release_url, metadata, f"github-release-{tag}.html"
        )
        assets, asset_provenance = snapshot(
            f"https://github.com/astral-sh/python-build-standalone/releases/expanded_assets/{tag}",
            metadata,
            f"github-assets-{tag}.html",
        )
        published = re.search(
            r'<relative-time[^>]*datetime="([0-9TZ:.-]+)"', page.read_text()
        )
        if not published:
            raise ValueError("official release publication date unavailable")
        html = assets.read_text()
        candidates = []
        for match in re.finditer(
            r'<a href="(/astral-sh/python-build-standalone/releases/download/[^\"]+)"[^>]*>(.*?)</a>(.*?)(?=<a href=|$)',
            html,
            re.S,
        ):
            filename = match[1].rsplit("/", 1)[1]
            digest = re.search(r"sha256:([0-9a-f]{64})", match[3])
            candidates.append(
                {
                    "name": filename,
                    "browser_download_url": "https://github.com" + match[1],
                    "digest": None if digest is None else "sha256:" + digest[1],
                }
            )
        chosen = select_runtime(
            [
                {
                    "tag_name": tag,
                    "published_at": published[1],
                    "prerelease": False,
                    "draft": False,
                    "assets": candidates,
                }
            ],
            as_of,
        )
        asset_provenance = {
            **asset_provenance,
            "fallback_reason": str(error),
            "selection_scope": f"official pinned release {tag}; controller-approved API-rate-limit fallback",
        }
        return chosen, [page_provenance, asset_provenance]
    chosen = select_runtime(json.loads(path.read_text()), as_of)
    return chosen, [provenance]


_RUNTIME_PROBE = """import ctypes, json, pip, sqlite3, ssl, sys, sysconfig, zlib, tkinter
assert sys.version_info[:2] == (3, 12)
assert ctypes.CDLL(None)
assert sqlite3.connect(':memory:').execute('select 1').fetchone() == (1,)
assert ssl.create_default_context()
assert sysconfig.get_path('stdlib').startswith(sys.prefix)
print(json.dumps({'version':sys.version.split()[0], 'prefix':sys.prefix, 'ssl':ssl.OPENSSL_VERSION,'sqlite':sqlite3.sqlite_version,'pip':pip.__version__,'stdlib':sysconfig.get_path('stdlib'),'zlib':zlib.ZLIB_RUNTIME_VERSION,'tcl':tkinter.Tcl().eval('info patchlevel')}))
"""


def bootstrap_records(inventory):
    records = [{**package, "kind": "installed"} for package in inventory["installed"]]
    for line in inventory["pip_vendored"].splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9.+!-]+)", line)
        if not match:
            raise ValueError(f"unpinned bootstrap vendor: {line}")
        records.append(
            {
                "name": "pip-vendor-" + canonicalize_name(match[1]),
                "upstream_name": match[1],
                "version": match[2],
                "kind": "pip-vendored",
            }
        )
    return sorted(records, key=lambda item: item["name"])


def prepare_native_repairs(settings, cache, root, image):
    """Fetch, verify and execute only pinned maintainer repair inputs."""
    inputs = settings["native_repairs"]
    paths = {}
    for key in ("patchelf", "zlib_rpm", "zlib_srpm"):
        source = inputs[key]["source"]
        paths[key] = cache_asset(source["url"], source["sha256"], cache / "sha256")
    def inside(path):
        return "/work/" + str(path.relative_to(root))
    rpm_paths = [inside(paths[key]) for key in ("zlib_rpm", "zlib_srpm")]
    # Trust roots come from the digest-pinned Rocky image; import is confined to
    # an ephemeral container and never changes the maintainer RPM database.
    command = ["/bin/sh", "-c", 'mkdir /tmp/qbox-rpmdb && rpmkeys --dbpath /tmp/qbox-rpmdb --import /etc/pki/rpm-gpg/RPM-GPG-KEY-rockyofficial && rpmkeys --dbpath /tmp/qbox-rpmdb -Kv "$@"', "rpm-verify", *rpm_paths]
    verification = subprocess.run(container_command(image,root,command,network=False),
        check=True,capture_output=True,text=True)
    if "NOT OK" in verification.stdout or "NOKEY" in verification.stdout or "Signature" not in verification.stdout:
        raise ValueError("native library RPM signature verification failed")
    (cache / "native-rpm-verification.log").write_text(verification.stdout)
    payload = subprocess.run(container_command(image,root,["rpm2cpio",rpm_paths[0]],network=False),
        check=True,capture_output=True).stdout
    files = read_newc(payload)
    library = files[inputs["zlib_rpm"]["library_member"]]
    license_body = files[inputs["zlib_rpm"]["license_member"]]
    from hashlib import sha256
    if sha256(library).hexdigest()!=inputs["zlib_rpm"]["library_sha256"]:
        raise ValueError("pinned libz ELF digest mismatch")
    if sha256(license_body).hexdigest()!=inputs["zlib_rpm"]["license_sha256"]:
        raise ValueError("pinned libz license digest mismatch")
    with zipfile.ZipFile(paths["patchelf"]) as wheel:
        binary = wheel.read(inputs["patchelf"]["member"])
    if sha256(binary).hexdigest()!=inputs["patchelf"]["binary_sha256"]:
        raise ValueError("patchelf binary digest mismatch")
    tool = cache / "native-tools/patchelf"
    tool.parent.mkdir(exist_ok=True)
    tool.write_bytes(binary)
    tool.chmod(0o755)
    normalized = normalize_runtime(cache / "sha256" / inputs["runtime_upstream_sha256"], cache / "python-unrepaired.tar.gz")
    repair = repair_runtime(cache / "python-unrepaired.tar.gz",cache / "python.tar.gz",tool,
        {"python/lib/libz.so.1":library,"python/licenses/LICENSE.libz-system.txt":license_body})
    repair["inputs"] = inputs
    repair["rpm_verification_sha256"] = sha256_file(cache / "native-rpm-verification.log")
    (cache / "native-repair.json").write_bytes(canonical_json(repair))
    normalized.update({key:repair[key] for key in ("sha256","size")})
    return normalized, repair


def load_cpu_builds(bindings, directory):
    """Read immutable per-component histories and verify any recorded lock hashes."""
    from .cpu_wheels import validate_components
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("CPU builds require a nonempty component list")
    result = []
    for binding in bindings:
        for key in ('inputs', 'provenance'):
            if Path(binding[key]).name != binding[key]:
                raise ValueError("unsafe CPU component lock path")
        proof_path = directory / binding['provenance']
        inputs_path = directory / binding['inputs']
        hashes = {'provenance_sha256':sha256_file(proof_path), 'inputs_sha256':sha256_file(inputs_path)}
        if any(key in binding and binding[key] != value for key,value in hashes.items()):
            raise ValueError("CPU build provenance/input lock hash mismatch")
        result.append({'id':binding['id'], 'proof':json.loads(proof_path.read_text()),
                       'input_bytes':inputs_path.read_bytes(), 'binding':{**binding, **hashes}})
    validate_components(result, [p for item in result for p in item['proof']['outputs']])
    return result


def resolve(policy: Path, cache: Path) -> dict:
    """Acquire and resolve in digest-pinned Rocky 8; emit candidates and offline proof.

    Cache must be inside repository (one /work container mount). Prior candidates are
    scratch; reviewed packaging/offline locks are NEVER overwritten. Builder consumes
    sha256/<digest>, python.tar.gz and candidate-wheelhouse with the reviewed locks.
    """
    policy = Path(policy).resolve()
    root = policy.parents[2]
    cache = Path(cache).resolve()
    cache.relative_to(root)  # Fail before any mutation outside the repository.
    cache.mkdir(parents=True, exist_ok=True)
    config = json.loads(policy.read_text())
    settings = config["resolver"]
    image = settings["build_image"]
    cpu_components = []
    if "cpu_build" in settings:
        from .cpu_wheels import select_wheels, validate_components
        cpu_components = load_cpu_builds(settings['cpu_build'], policy.parent)
        for component in cpu_components:
            select_wheels(component['proof'], cache)  # Fail before resolution/network.
    metadata = cache / "metadata"
    upstream, provenance = discover_runtime(settings, metadata)
    archive = cache_asset(
        upstream["url"],
        upstream["sha256"],
        cache / "sha256",
        local=(
            cache / "downloads" / upstream["filename"]
            if (cache / "downloads" / upstream["filename"]).exists()
            else None
        ),
    )
    companion_name = f'cpython-{upstream["version"]}+{upstream["build"]}-x86_64-unknown-linux-gnu-pgo+lto-full.tar.zst'
    companion_page, companion_provenance = snapshot(
        f'https://github.com/astral-sh/python-build-standalone/releases/expanded_assets/{upstream["build"]}',
        metadata,
        f'github-assets-{upstream["build"]}.html',
    )
    companion_match = re.search(
        r'aria-label="Copy to clipboard digest for '
        + re.escape(companion_name)
        + r'"[^>]*value="sha256:([0-9a-f]{64})"',
        companion_page.read_text(),
    )
    if not companion_match:
        raise ValueError("companion runtime archive official digest missing")
    companion_source = {
        "filename": companion_name,
        "url": upstream["url"].rsplit("/", 1)[0] + "/" + companion_name,
        "sha256": companion_match[1],
    }
    companion_archive = cache_asset(
        companion_source["url"],
        companion_source["sha256"],
        cache / "sha256",
        local=(
            cache / "downloads" / companion_name
            if (cache / "downloads" / companion_name).exists()
            else None
        ),
    )
    companion_materials = preserve_runtime_materials(
        companion_archive, cache / "runtime-license-materials", companion_source
    )
    repair = None
    if "native_repairs" in settings:
        if settings["native_repairs"]["runtime_upstream_sha256"] != upstream["sha256"]:
            raise ValueError("native repair pins do not match selected runtime")
        normalized, repair = prepare_native_repairs(settings, cache, root, image)
    else:
        normalized = normalize_runtime(archive, cache / "python.tar.gz")
    (cache / "normalization.json").write_bytes(canonical_json(normalized))
    import tarfile

    for directory, asset in [
        ("original", archive),
        ("runtime", cache / "python.tar.gz"),
        ("relocated runtime", cache / "python.tar.gz"),
    ]:
        dest = cache / directory
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir()
        # Original was validated by normalize_runtime; retain the extraction filter.
        with tarfile.open(asset) as tar:
            tar.extractall(dest, filter="data")

    def inside(path):
        return "/work/" + str(Path(path).relative_to(root))

    def run(command, network=False, log=None):
        result = subprocess.run(
            container_command(image, root, command, network=network),
            env=pip_environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if log:
            (cache / log).write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(
                f"container command failed ({result.returncode}): {command}\n{result.stdout}"
            )
        return result.stdout

    def record_sources(packages, directory):
        for package in packages:
            meta, meta_provenance = snapshot(
                f'https://pypi.org/pypi/{package["name"]}/{package["version"]}/json',
                metadata,
                f'{package["name"]}-{package["version"]}.json',
            )
            package["source"] = pypi_source(package, json.loads(meta.read_text()))
            package["metadata_snapshot"] = meta_provenance
            cache_asset(
                package["source"]["url"],
                package["sha256"],
                cache / "sha256",
                local=directory / package["filename"],
            )

    probes = {}
    for directory in ["original", "runtime", "relocated runtime"]:
        probes[directory] = json.loads(
            run(
                [
                    inside(cache / directory / "python/bin/python3"),
                    "-I",
                    "-B",
                    "-c",
                    _RUNTIME_PROBE,
                ]
            )
        )
    python = inside(cache / "runtime/python/bin/python3")
    tools_dir = cache / "build-wheelhouse"
    if tools_dir.exists():
        shutil.rmtree(tools_dir)
    tools_dir.mkdir()
    run(
        [
            python,
            "-I",
            "-B",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "download",
            "--only-binary=:all:",
            "--dest",
            inside(tools_dir),
            *settings["build_requirements"],
        ],
        network=True,
        log="build-download.log",
    )
    build_packages = wheel_closure(
        sorted(tools_dir.glob("*.whl")), settings["build_requirements"], {}
    )
    record_sources(build_packages, tools_dir)
    build_lock = requirements_bytes(build_packages)
    (cache / "build-requirements.lock").write_bytes(build_lock)
    build_env = cache / "build-env"
    if build_env.exists():
        shutil.rmtree(build_env)
    run([python, "-I", "-B", "-m", "venv", inside(build_env)])
    build_python = inside(build_env / "bin/python")
    run(
        [
            build_python,
            "-I",
            "-B",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--no-index",
            "--require-hashes",
            "--find-links",
            inside(tools_dir),
            "-r",
            inside(cache / "build-requirements.lock"),
        ],
        log="build-install-offline.log",
    )
    source_wheels = cache / "qbox-wheel"
    source_wheels.mkdir(exist_ok=True)
    for old in source_wheels.glob("*.whl"):
        old.unlink()
    run(
        [
            build_python,
            "-I",
            "-B",
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            inside(source_wheels),
            "/work",
        ],
        log="qbox-build.log",
    )
    (qbox_wheel,) = source_wheels.glob("*.whl")
    qbox = wheel_metadata(qbox_wheel)
    environment = json.loads(
        run(
            [
                build_python,
                "-I",
                "-B",
                "-c",
                "import json; from packaging.markers import default_environment; print(json.dumps(default_environment()))",
            ]
        )
    )
    wheelhouse = cache / "candidate-wheelhouse"
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir()
    root_req = f'qbox[analysis,structure]=={qbox["version"]}'
    run(
        [
            python,
            "-I",
            "-B",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "download",
            "--only-binary=:all:",
            "--dest",
            inside(wheelhouse),
            "--find-links",
            inside(source_wheels),
            root_req,
        ],
        network=True,
        log="application-download.log",
    )
    if cpu_components:
        from .cpu_wheels import apply_selection
        for component in cpu_components:
            apply_selection(wheelhouse, component["proof"], cache)
    packages = wheel_closure(sorted(wheelhouse.glob("*.whl")), [root_req], environment)
    if len(packages) != len(list(wheelhouse.glob("*.whl"))):
        raise ValueError("unreachable wheel in resolved wheelhouse")
    application = [p for p in packages if p["name"] != "qbox"]
    custom = {p["name"]: p for component in cpu_components for p in component["proof"]["outputs"]}
    record_sources([p for p in application if p["name"] not in custom], wheelhouse)
    for package in application:
        if package["name"] in custom:
            original = custom[package["name"]]
            package["source"] = original["source"]
            package["build_provenance"] = original["build_provenance"]
    if cpu_components:
        validate_components(cpu_components, application)
    all_lock = requirements_bytes(packages).replace(
        f'qbox=={qbox["version"]}'.encode(), root_req.encode()
    )
    (cache / "offline-requirements.lock").write_bytes(all_lock)
    reinstall = cache / "offline-reinstall"
    if reinstall.exists():
        shutil.rmtree(reinstall)
    run([python, "-I", "-B", "-m", "venv", inside(reinstall)])
    offline_python = inside(reinstall / "bin/python")
    run(
        [
            offline_python,
            "-I",
            "-B",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--no-index",
            "--require-hashes",
            "--only-binary=:all:",
            "--find-links",
            inside(wheelhouse),
            "-r",
            inside(cache / "offline-requirements.lock"),
        ],
        log="offline-reinstall.log",
    )
    check = run(
        [offline_python, "-I", "-B", "-m", "pip", "--isolated", "check"],
        log="offline-pip-check.log",
    )
    imports = run(
        [
            offline_python,
            "-I",
            "-B",
            "-c",
            'import numpy, scipy, matplotlib, seekpath, pymatgen.core, ase, qbox; print("all qbox extras imported")',
        ],
        log="offline-imports.log",
    )
    bootstrap = json.loads(
        run(
            [
                python,
                "-I",
                "-B",
                "-c",
                "import importlib.metadata as m,json,pathlib,pip; p=pathlib.Path(pip.__file__).parent; print(json.dumps({'installed':[{'name':d.metadata['Name'],'version':d.version} for d in m.distributions()], 'pip_vendored':(p/'_vendor/vendor.txt').read_text()}))",
            ]
        )
    )
    runtime_lock = {
        "schema_version": 1,
        "implementation": "cpython",
        "version": upstream["version"],
        "build": upstream["build"],
        "target_triple": "x86_64-unknown-linux-gnu",
        "flavor": "install_only",
        "source": {k: upstream[k] for k in ["url", "filename", "sha256"]},
        "official_metadata": provenance,
        "companion_archive": {
            "source": companion_source,
            "official_metadata": companion_provenance,
            "purpose": "maintenance-only PYTHON.json and native license materials",
            "materials": {
                "directory": "runtime-license-materials",
                **companion_materials,
            },
        },
        "normalized": {k: v for k, v in normalized.items() if k != "links"},
        "link_map_sha256": sha256_file(cache / "normalization.json"),
        "bootstrap_packages": bootstrap_records(bootstrap),
        "probes": probes,
    }
    if repair is not None:
        runtime_lock["native_repair"] = repair
    deps = {
        "schema_version": 1,
        "extras": config["extras"],
        "marker_environment": environment,
        "build_image": image,
        "qbox_resolution_wheel": qbox,
        "packages": application,
        "build_packages": build_packages,
        "offline_verification": {
            "network": "none",
            "pip_check": check.strip(),
            "imports": imports.strip(),
            "requirements_sha256": sha256_file(cache / "offline-requirements.lock"),
            "logs": {
                name: sha256_file(cache / name)
                for name in [
                    "offline-reinstall.log",
                    "offline-pip-check.log",
                    "offline-imports.log",
                ]
            },
        },
    }
    if cpu_components:
        deps["cpu_build"] = [component["binding"] for component in cpu_components]
    image_lock = {
        "schema_version": 1,
        "build": image,
        "validation": settings["validation_images"],
    }
    contents = {
        "runtime.lock.json": canonical_json(runtime_lock),
        "dependencies.lock.json": canonical_json(deps),
        "requirements.lock": requirements_bytes(application),
        "build-requirements.lock": build_lock,
        "images.lock.json": canonical_json(image_lock),
    }
    result = write_candidates(policy.parent, cache / "candidate-locks", contents)
    (cache / "resolution-result.json").write_bytes(canonical_json(result))
    return result
