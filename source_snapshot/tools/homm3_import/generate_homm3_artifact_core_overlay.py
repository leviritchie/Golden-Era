#!/usr/bin/env python3
"""Generate HoMM3 artifact Core overlay inspection members from the catalog."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_import"))

from homm3_artifact_core_overlay import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
