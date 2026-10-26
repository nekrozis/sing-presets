"""The command line, where a wrong default is noticed by a user rather than by a test.

Only the parts with behaviour belong here; argument parsing is exercised through the
integration test that runs a real build.
"""

from __future__ import annotations

from pathlib import Path

from sing_presets import cli


def test_a_broken_preset_document_is_a_message_not_a_traceback(
    capsys, tmp_path: Path
) -> None:
    """The preset file is the thing a user edits, so a typo in it is expected input."""
    document = tmp_path / "presets.yaml"
    document.write_text("version: 9\npresets:\n  one: {}\n", encoding="utf-8")
    assert cli.main(["list", "--presets", str(document)]) == 2
    captured = capsys.readouterr()
    assert "unsupported document version 9" in captured.err
    assert "Traceback" not in captured.err


def test_the_binary_path_is_read_when_it_is_looked_for(
    monkeypatch, tmp_path: Path
) -> None:
    """SING_BOX was read at import time, so setting it afterwards had no effect.

    That is exactly what a wrapper script or a test does, and the lookup then silently fell
    through to whatever `sing-box` happened to be on PATH.
    """
    fake = tmp_path / "sing-box.exe"
    fake.write_text("", encoding="utf-8")

    monkeypatch.setenv(cli.SING_BOX_ENV, str(fake))
    assert cli.find_sing_box() == str(fake)

    monkeypatch.delenv(cli.SING_BOX_ENV)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert cli.find_sing_box() is None


def test_a_stale_environment_variable_falls_back_to_path(monkeypatch, tmp_path: Path) -> None:
    """A path that no longer exists must not stop the lookup from finding the real binary."""
    on_path = tmp_path / "bin" / "sing-box"
    on_path.parent.mkdir()
    on_path.write_text("", encoding="utf-8")

    monkeypatch.setenv(cli.SING_BOX_ENV, str(tmp_path / "gone"))
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(on_path))
    assert cli.find_sing_box() == str(on_path)
