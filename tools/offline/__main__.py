"""Maintainer CLI for qbox offline release data."""

import argparse
import json
from pathlib import Path
import sys

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
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "resolve":
        from .resolve import resolve

        try:
            print(json.dumps(resolve(args.policy, args.cache), indent=2))
        except (OSError, ValueError, RuntimeError) as error:
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
