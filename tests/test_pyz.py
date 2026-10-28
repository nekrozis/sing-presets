"""The packaged build: one file, and nothing installed for it.

`-S` is what makes these tests mean anything. Without it site-packages is on the path, so a
PyYAML that was never vendored still imports and a broken archive would look complete.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import build_pyz

DOCUMENT = """\
version: 1
presets:
  single:
    description: One preset.
    capabilities:
      - logging
      - dns-split
      - outbound-groups
"""

NODES = """\
{
  "version": 1,
  "sources": [],
  "nodes": [
    {
      "tag": "one",
      "type": "shadowsocks",
      "server": "198.51.100.10",
      "server_port": 8388,
      "method": "aes-128-gcm",
      "password": "example"
    }
  ]
}
"""


def run(pyz: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the archive the way a user would: a plain interpreter, no site-packages."""
    return subprocess.run(
        [sys.executable, "-S", str(pyz), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=pyz.parent,
        check=False,
    )


def test_the_archive_carries_what_it_imports(tmp_path: Path) -> None:
    pyz = build_pyz.build(tmp_path / "sing-presets.pyz")
    (tmp_path / "presets.yaml").write_text(DOCUMENT, encoding="utf-8")
    result = run(pyz, "list", "--presets", str(tmp_path / "presets.yaml"))
    assert result.returncode == 0, result.stderr
    assert "single" in result.stdout


def test_a_packaged_build_reads_the_document_beside_it(tmp_path: Path) -> None:
    """There is no checkout next to an archive, so the default has to be the working directory."""
    pyz = build_pyz.build(tmp_path / "sing-presets.pyz")
    (tmp_path / "presets.yaml").write_text(DOCUMENT, encoding="utf-8")
    result = run(pyz, "list")
    assert result.returncode == 0, result.stderr
    assert "single" in result.stdout


def test_the_archive_finds_the_surface_it_ships_with(tmp_path: Path) -> None:
    """The surface is package data, and only the import machinery can reach inside an archive.

    A path assembled with `Path` works in a checkout and fails here, which is the whole reason
    this test builds a real archive instead of importing the module.
    """
    pyz = build_pyz.build(tmp_path / "sing-presets.pyz")
    document = tmp_path / "presets.yaml"
    document.write_text(DOCUMENT, encoding="utf-8")
    nodes = tmp_path / "nodes.json"
    nodes.write_text(NODES, encoding="utf-8")
    result = run(
        pyz,
        "build",
        "--presets",
        str(document),
        "--nodes",
        str(nodes),
        "--out",
        str(tmp_path / "out"),
        "--no-verify",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out" / "single.json").is_file()


def test_the_exit_code_survives_the_archive(tmp_path: Path) -> None:
    """zipapp's own `__main__` drops the return value, which would report failure as success."""
    pyz = build_pyz.build(tmp_path / "sing-presets.pyz")
    broken = tmp_path / "broken.yaml"
    broken.write_text("version: 9\npresets:\n  one: {}\n", encoding="utf-8")
    result = run(pyz, "list", "--presets", str(broken))
    assert result.returncode == 2
    assert "unsupported document version 9" in result.stderr
    assert "Traceback" not in result.stderr
