"""Small path helpers for local sidecar directories."""

from __future__ import annotations

import os
import pathlib


def get_app_root() -> pathlib.Path:
    """Return the local app root using the same environment style as the app."""
    return pathlib.Path(os.environ.get("OUROBOROS_APP_ROOT", pathlib.Path.home() / "Ouroboros")).expanduser()


def get_data_dir() -> pathlib.Path:
    """Return the sidecar ``Data`` directory located next to the app root."""
    return get_app_root() / "Data"


__all__ = ["get_app_root", "get_data_dir"]
