"""Command line entry point: read presets, write configurations, verify them.

Kept deliberately thin. Everything interesting happens in `presets` (what a user declares)
and `compile` (how it becomes a configuration); this module only maps arguments to those
and reports what happened.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from . import compile as comp
from . import presets as preset_lib
from .surface import Surface

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRESETS = REPO_ROOT / "presets.yaml"
DEFAULT_OUT = REPO_ROOT / "build"

#: Places to look for the binary that validates output. `sing-box` from PATH is the
#: normal case in CI; the explicit path keeps a local Windows setup working.
BINARY_CANDIDATES = (
    os.environ.get("SING_BOX"),
    shutil.which("sing-box"),
    r"C:\Users\Lyra\scoop\shims\sing-box.exe",
)


def find_sing_box() -> str | None:
    for candidate in BINARY_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def read_nodes(path: Path) -> list[dict]:
    """Read the node list produced by the subscription step."""
    if not path.exists():
        raise SystemExit(f"no node list at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes") if isinstance(payload, dict) else payload
    if not isinstance(nodes, list):
        raise SystemExit(f"{path} does not hold a list of nodes")
    return nodes


def write_build(build: comp.Build, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{build.preset}.json"
    target.write_text(
        json.dumps(build.config, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def verify(binary: str, path: Path) -> str | None:
    """Run sing-box check. Returns the error text, or None when the file is accepted."""
    result = subprocess.run(
        [binary, "check", "-c", str(path)], capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        return None
    return (result.stdout + result.stderr).strip() or f"exit code {result.returncode}"


def cmd_list(args: argparse.Namespace) -> int:
    document = preset_lib.load(args.presets)
    for name in document.names:
        preset = document.presets[name]
        description = f"  {preset.description}" if preset.description else ""
        print(f"{name:24s} {len(preset.capabilities)} capabilities{description}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    document = preset_lib.load(args.presets)
    surface = Surface.load()

    selected = document.names
    if args.only:
        missing = [name for name in args.only if name not in document.presets]
        if missing:
            raise SystemExit(f"no such preset: {', '.join(missing)}")
        selected = list(args.only)

    nodes = read_nodes(args.nodes) if args.nodes else []
    if not nodes and not args.allow_empty:
        raise SystemExit(
            "a node list is required: pass --nodes, or --allow-empty to build without "
            "subscription nodes (useful only for inspecting the skeleton)"
        )

    try:
        builds = comp.compile_all(
            surface, [document.presets[name] for name in selected], nodes
        )
    except comp.CompileError as error:
        print(f"build failed:\n{error}", file=sys.stderr)
        return 1

    binary = None if args.no_verify else (args.sing_box or find_sing_box())
    failures = 0
    for build in builds:
        target = write_build(build, args.out)
        print(f"{build.summary()} -> {target}")
        if binary:
            problem = verify(binary, target)
            if problem:
                failures += 1
                print(f"  rejected by sing-box: {problem}", file=sys.stderr)
        if args.audit:
            for problem in comp.audit(surface, build):
                failures += 1
                print(f"  audit: {problem}", file=sys.stderr)

    if binary is None and not args.no_verify:
        print(
            "no sing-box binary found, so nothing was verified; set SING_BOX to check output",
            file=sys.stderr,
        )
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sing-presets",
        description="Compile presets into sing-box configurations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list the presets in a document")
    listing.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)
    listing.set_defaults(handler=cmd_list)

    building = sub.add_parser("build", help="compile presets to JSON")
    building.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)
    building.add_argument(
        "--nodes", type=Path, help="JSON node list produced from the subscription"
    )
    building.add_argument("--out", type=Path, default=DEFAULT_OUT)
    building.add_argument(
        "--only", nargs="+", metavar="NAME", help="build only these presets"
    )
    building.add_argument(
        "--allow-empty",
        action="store_true",
        help="build without nodes, for inspecting the skeleton only",
    )
    building.add_argument(
        "--sing-box", help="path to the binary used for verification; defaults to PATH"
    )
    building.add_argument(
        "--no-verify", action="store_true", help="skip the sing-box check"
    )
    building.add_argument(
        "--audit",
        action="store_true",
        help="also run the slow capability isolation check",
    )
    building.set_defaults(handler=cmd_build)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
