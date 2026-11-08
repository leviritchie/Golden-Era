#!/usr/bin/env python3
"""Unit tests for ToA alt authentic DEF rematerialization (GG_FF.png)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from rematerialize_toa_alt_authentic_def_names import rematerialize  # noqa: E402
from materialize_rife_source_frames import inventory_authentic_def_groups  # noqa: E402


class RematerializeToaAltAuthenticDefNamesTests(unittest.TestCase):
    def test_hot_a_names_become_gg_ff_and_inventory_sees_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lab = Path(tmp)
            sid = "h3_battle_griffin"
            base = "lvl3Alt"
            src_root = lab / sid / "extracted_battle_source_12fps"
            src_dir = src_root / f"{base}.dir"
            src_dir.mkdir(parents=True)
            # Minimal HotA-style plates referenced by sequences JSON.
            (src_dir / "CrgrifA000.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
            (src_dir / "CrgrifA001.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
            (src_dir / "CrgrifB000.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
            sequences = {
                "sequences": [
                    {
                        "group": 0,
                        "frames": [f"{base}.dir\\CrgrifA000.png", f"{base}.dir\\CrgrifA001.png"],
                    },
                    {"group": 2, "frames": [f"{base}.dir\\CrgrifB000.png"]},
                ]
            }
            (src_root / f"{base}.json").write_text(
                json.dumps(sequences, indent=2) + "\n", encoding="utf-8"
            )

            result = rematerialize(lab, sid, base)
            self.assertTrue(result["hasIdleGroup2"])
            inv = inventory_authentic_def_groups(src_dir)
            self.assertIn(2, inv)
            self.assertEqual(len(inv[2]), 1)
            self.assertTrue((src_dir / "02_00.png").is_file())
            self.assertTrue((src_dir / "00_00.png").is_file())
            self.assertFalse((src_dir / "CrgrifA000.png").exists())
            # Backup preserved original HotA names.
            backup = Path(result["backup"])
            self.assertTrue((backup / "CrgrifA000.png").is_file())


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
