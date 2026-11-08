#!/usr/bin/env python3
"""CLI: emit a stock-legal Olden map from a standalone HoMM3 .h3m."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POC = REPO / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

from vanilla_stock.emit_map import main_emit_cli  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main_emit_cli())
