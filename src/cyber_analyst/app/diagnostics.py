"""Small local lifecycle log for the windowed portable executable."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile


def configure_logging():
    # Development startup keeps its existing logging behavior.
    if not getattr(sys, "frozen", False):
        return None
    root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    path = root / "CyberAnalyst" / "logs" / "application.log"
    logger = logging.getLogger("cyber_analyst")
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == path:
            return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    except OSError:
        # A protected profile must not prevent dataset browsing/startup.
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("Portable startup; Python=%s", sys.version.split()[0])
    return path
