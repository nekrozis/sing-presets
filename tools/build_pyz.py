"""Package the command line into one file that runs wherever Python 3.10 does.

A zipapp needs no virtualenv, no install step and no console script: `python
sing-presets.pyz fetch ...` is the whole story, which is what a CI job, a router's shell or a
throwaway machine wants. It is not a standalone binary - a Python interpreter is still
required - but it does mean nobody has to reproduce this project's environment to run it.

Nothing is installed for the archive, so it has to carry everything it imports:

  - `sing_presets`, including the generated surface under `data/`;
  - PyYAML's Python modules. Its C extension cannot be loaded from an archive entry and the
    pure Python path is complete, so the extension is skipped rather than shipped dead;
  - a `__main__.py` of our own, because the one zipapp generates discards the return value
    and this command reports failure through its exit code.

    python tools/build_pyz.py                  # -> dist/sing-presets.pyz
    python tools/build_pyz.py -o /tmp/tool.pyz

Byte-for-byte reproducibility is not attempted: zipapp records each file's timestamp, so two
builds of the same sources differ.
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "sing_presets"

#: Imported at run time by the package, so it has to be inside the archive. Everything else
#: this code imports is in the standard library.
VENDORED = ("yaml",)

IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyd", "*.so", "*.so.*")

MAIN = """\
import sys

from sing_presets.cli import main

sys.exit(main())
"""


def _copy_package(staging: Path) -> None:
    """Copy the package, keeping the data the build reads and dropping compiled leftovers."""
    shutil.copytree(REPO_ROOT / PACKAGE, staging / PACKAGE, ignore=IGNORED)


def _copy_dependency(name: str, staging: Path) -> None:
    """Copy an installed dependency's package directory, without its compiled parts."""
    module = importlib.import_module(name)
    location = getattr(module, "__file__", None)
    if location is None:
        raise SystemExit(f"{name} is built into the interpreter, so it cannot be vendored")
    source = Path(location).resolve().parent
    shutil.copytree(source, staging / name, ignore=IGNORED)


def build(target: Path) -> Path:
    """Write the archive and return where it landed."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary)
        _copy_package(staging)
        for name in VENDORED:
            _copy_dependency(name, staging)
        (staging / "__main__.py").write_text(MAIN, encoding="utf-8")
        zipapp.create_archive(
            staging,
            target,
            interpreter="/usr/bin/env python3",
            compressed=True,
        )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=REPO_ROOT / "dist" / "sing-presets.pyz",
        help="where to write the archive",
    )
    args = parser.parse_args(argv)
    written = build(args.out)
    size = written.stat().st_size
    print(f"{written} ({size // 1024} KiB) - run it with: python {written.name} list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
