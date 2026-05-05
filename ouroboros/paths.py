"""Shared runtime path helpers."""

from __future__ import annotations

import os
import pathlib
from typing import Any

from ouroboros.config import DATA_DIR


def get_data_dir(ctx: Any | None = None) -> pathlib.Path:
    """Return the active runtime data directory.

    Preference order:
    1. ``ctx.drive_root`` when a tool context is available.
    2. ``OUROBOROS_DATA_DIR`` from the live environment.
    3. ``ouroboros.config.DATA_DIR`` fallback.
    """
    drive_root = getattr(ctx, "drive_root", None) if ctx is not None else None
    if drive_root:
        return pathlib.Path(drive_root).expanduser().resolve(strict=False)

    configured = (os.environ.get("OUROBOROS_DATA_DIR", "") or "").strip()
    if configured:
        return pathlib.Path(configured).expanduser().resolve(strict=False)

    return pathlib.Path(DATA_DIR).expanduser().resolve(strict=False)
