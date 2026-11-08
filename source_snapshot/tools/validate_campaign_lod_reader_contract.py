#!/usr/bin/env python3
"""Run the focused campaign LOD reader safety and bounded-I/O tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

from test_lod_entry_reader import LodEntryReaderTests  # noqa: E402


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LodEntryReaderTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
