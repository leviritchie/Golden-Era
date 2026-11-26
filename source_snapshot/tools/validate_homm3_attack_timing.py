#!/usr/bin/env python3
"""Gate: h3_* attack contact / shot release times follow the clips that ship.

  * the timing table (custom_factions/contracts/homm3_attack_timing.json) was measured from the GLB each delivery
    slice now pins (frozen idleRetimedGlbSha256), so a redelivered attack or shot clip fails until
    tools/homm3_def_retarget_delivery/attack_timing.py build is rerun;
  * every measured contact lies inside its clip (0 < hit < length) and after = length - hit;
  * with --core: every h3_* units_views row the table covers carries exactly the table's attackTimeBefore/After on
    each animation slot its default/alternative/counter attacks use (tools/release_port/homm3_attack_timing_overlay.py
    writes them), so the damage / projectile lands on the pose the unit strikes or shoots on.

apply_release_core_overlay.py runs this on the candidate and the updated release Core.zip. Static/generated proof only.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))
import homm3_attack_timing_overlay as T  # noqa: E402

_DELIVERY = ROOT / "tools" / "homm3_def_retarget_delivery"
# rebuild slices redeliver slice_v1 units with re-authored clips; listed last so their pins win
SLICES = sorted(_DELIVERY.glob("*_slice_v1.json")) + sorted(_DELIVERY.glob("*_rebuild_v1.json"))
TOL = 1e-3


def table_errors(doc: dict) -> list[str]:
    errors = []
    pins: dict[str, str] = {}
    for sf in SLICES:
        for r in json.loads(sf.read_text(encoding="utf-8")).get("units", []):
            pins[r.get("gameSid") or r["labSid"]] = r["frozen"]["idleRetimedGlbSha256"]
    for sid, u in sorted(doc["units"].items()):
        if sid in pins and pins[sid] != u.get("glbSha256"):
            errors.append(f"{sid}: timing measured on GLB {str(u.get('glbSha256'))[:12]}, slice now pins "
                          f"{pins[sid][:12]} (rerun attack_timing.py build --only {sid})")
        for clip, c in u["clips"].items():
            if not (0 < c["hit"] < c["length"]):
                errors.append(f"{sid}: {clip} contact {c['hit']} outside the clip (0, {c['length']})")
            if abs(c["after"] - (c["length"] - c["hit"])) > TOL:
                errors.append(f"{sid}: {clip} after {c['after']} != length - hit")
        if "Unit_AttackFront" not in u["clips"]:
            errors.append(f"{sid}: no Unit_AttackFront timing")
    for sid, host in doc.get("fusionHosts", {}).items():
        if host not in doc["units"]:
            errors.append(f"fusion {sid}: host {host} not measured")
    return errors


def core_errors(doc: dict, core: Path) -> tuple[list[str], int]:
    errors, checked = [], 0
    with zipfile.ZipFile(core) as z:
        for name in z.namelist():
            if not (name.startswith("DB/units/units_views/") and name.endswith("_v.json")
                    and Path(name).name.startswith("h3_")):
                continue
            for row in json.loads(z.read(name).decode("utf-8-sig")).get("array") or []:
                if not isinstance(row, dict):
                    continue
                slots = T.expected_slots(doc, row)
                if slots is None:
                    continue
                checked += 1
                before, after = row.get("attackTimeBefore") or [], row.get("attackTimeAfter") or []
                for idx, (b, a) in sorted(slots.items()):
                    got_b = before[idx] if idx < len(before) else None
                    got_a = after[idx] if idx < len(after) else None
                    if got_b is None or abs(got_b - b) > TOL or got_a is None or abs(got_a - a) > TOL:
                        errors.append(f"{row.get('id')}: slot {idx} before/after {got_b}/{got_a} != clip {b}/{a}")
    return errors, checked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--core", type=Path)
    args = ap.parse_args()
    doc = T.load_table()
    errors = table_errors(doc)
    checked = 0
    if args.core:
        more, checked = core_errors(doc, args.core)
        errors += more
        if checked == 0:
            errors.append(f"no measured h3_* units_views rows in {args.core}")
    for e in errors:
        print("ERROR: " + e)
    print(f"{'FAIL' if errors else 'OK'}: {len(doc['units'])} measured unit(s), {checked} Core row(s), "
          f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
