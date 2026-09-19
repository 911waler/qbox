"""Maintainer CLI for qbox offline release data."""

import argparse
import json
from pathlib import Path
import sys
import subprocess

from .model import validate_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.offline")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate-manifest", help="validate an offline release manifest"
    )
    validate.add_argument("manifest", type=Path)
    resolve = commands.add_parser(
        "resolve", help="resolve candidate offline locks in pinned Rocky 8"
    )
    resolve.add_argument(
        "--policy", type=Path, default=Path("packaging/offline/policy.json")
    )
    resolve.add_argument("--cache", type=Path, default=Path("build/offline/cache"))
    build = commands.add_parser("build", help="assemble a deterministic candidate from local fixed inputs")
    build.add_argument("--cache", type=Path, default=Path("build/offline/cache"))
    build.add_argument("--output", type=Path, default=Path("dist/offline"))
    audit = commands.add_parser("audit", help="audit offline license and native inputs")
    audit.add_argument("--cache", type=Path, default=Path("build/offline/cache"))
    audit.add_argument("--output", type=Path, default=Path("build/offline/audit"))
    cpu = commands.add_parser("cpu-build", help="explicit pinned maintainer CPU wheel build (two clean runs)")
    cpu.add_argument("--lock", type=Path, default=Path("packaging/offline/cpu-build-inputs.lock.json"))
    cpu.add_argument("--cache", type=Path, default=Path("build/offline/cache"))
    cpu.add_argument("--output", type=Path, default=Path("build/offline/cpu-build"))
    cpu.add_argument("--fetch", action="store_true", help="acquire missing fixed-hash build inputs")
    finalize = commands.add_parser("cpu-finalize", help="pin final normalization of completed independent scientific builds")
    finalize.add_argument("provenance", type=Path)
    finalize.add_argument("--cache", type=Path, default=Path("build/offline/cache"))
    finalize.add_argument("--output", type=Path, required=True)
    for name in ("matrix", "gate"):
        command = commands.add_parser(name, help="offline release " + name)
        command.add_argument("--candidate", type=Path, required=True)
        if name == "matrix":
            command.add_argument("--engine", default="docker")
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--evidence", type=Path, required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command in ("matrix", "gate"):
        from .matrix import matrix, gate
        try:
            if args.command == "matrix":
                matrix(args.candidate, args.engine, args.output)
            else:
                gate(args.candidate, args.evidence)
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
            print(f"qbox offline: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "build":
        from .build import build
        try:
            print(build(args.cache, args.output))
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
            print(f"qbox offline: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "cpu-finalize":
        from .cpu_wheels import finalize_wheels
        try:
            print(json.dumps(finalize_wheels(args.provenance, args.cache, args.output), indent=2))
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
            print(f"qbox offline: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "cpu-build":
        from .cpu_wheels import build_wheels
        try:
            print(json.dumps(build_wheels(args.lock, args.cache, args.output, fetch=args.fetch), indent=2))
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
            print(f"qbox offline: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "audit":
        from .audit import audit

        try:
            result = audit(args.cache, args.output)
            print(json.dumps(result, indent=2))
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
            print(f"qbox offline: {error}", file=sys.stderr)
            return 1
        return 0 if result["status"] == "passed-static" else 1
    if args.command == "resolve":
        from .resolve import resolve

        try:
            print(json.dumps(resolve(args.policy, args.cache), indent=2))
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
            print(f"qbox offline: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "validate-manifest":
        try:
            value = json.loads(args.manifest.read_text(encoding="utf-8"))
            validate_manifest(value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            print(f"qbox offline: {error}", file=sys.stderr)
            return 1
        print(value["release_id"])
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
