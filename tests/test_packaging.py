"""Small build-contract and frozen logging checks; no executable compilation."""
import logging
from pathlib import Path
import sys
import tomllib

from cyber_analyst.app.diagnostics import configure_logging


def test_license_metadata_and_exact_build_versions():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "GPL-3.0-only"
    assert project["license-files"] == ["LICENSE"]
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 29 June 2007" in license_text
    assert "How to Apply These Terms to Your New Programs" in license_text
    requirements = (root / "packaging" / "requirements-build.txt").read_text().splitlines()
    assert all("==" in line for line in requirements if line and not line.startswith("#"))


def test_development_does_not_create_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert configure_logging() is None
    assert not list(tmp_path.iterdir())


def test_frozen_log_is_local_bounded_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    logger = logging.getLogger("cyber_analyst")
    previous_handlers = tuple(logger.handlers)
    previous_level = logger.level
    try:
        path = configure_logging()
        assert path == tmp_path / "CyberAnalyst" / "logs" / "application.log"
        assert configure_logging() == path
        handlers = [h for h in logger.handlers if h not in previous_handlers]
        assert len(handlers) == 1
        assert handlers[0].maxBytes == 1024 * 1024 and handlers[0].backupCount == 2
        logging.getLogger("cyber_analyst.ai.runtime").info("Runtime ready: pid=42")
        handlers[0].flush()
        assert "Runtime ready: pid=42" in path.read_text(encoding="utf-8")
    finally:
        for handler in tuple(logger.handlers):
            if handler not in previous_handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(previous_level)


def test_unwritable_profile_does_not_prevent_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    file = tmp_path / "not-a-directory"
    file.write_text("synthetic")
    monkeypatch.setenv("LOCALAPPDATA", str(file))
    assert configure_logging() is None
