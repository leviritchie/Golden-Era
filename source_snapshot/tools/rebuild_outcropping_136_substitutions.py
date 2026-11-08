#!/usr/bin/env python3
"""Rebuild entity substitution maps for missions that contain HoMM3 object id 136 (Outcropping)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(POC))

from campaign_mission import load_batch_manifest  # noqa: E402

AFFECTED = ROOT / "artifacts" / "campaign_port_poc" / "_outcropping_136_affected.json"


def main() -> int:
    rows = json.loads(AFFECTED.read_text(encoding="utf-8"))
    # Import once so MiniLM caches persist across missions.
    import build_homecoming_entity_substitution_map as sub_mod

    if sub_mod.TERRAIN_OBJECT_ROLES.get(136) != "rock":
        raise SystemExit(f"TERRAIN_OBJECT_ROLES[136] is not rock: {sub_mod.TERRAIN_OBJECT_ROLES.get(136)!r}")

    failures: list[dict] = []
    t0 = time.perf_counter()
    for i, row in enumerate(rows, 1):
        mission_id = row["missionId"]
        artifact_root = Path(row["artifactRoot"])
        substitution_path = Path(row["substitution"])
        alignment = artifact_root / "olden_storage_alignment" / f"{mission_id}.olden_storage_alignment.json"
        if not alignment.is_file():
            # homecoming uses different alignment name
            candidates = list((artifact_root / "olden_storage_alignment").glob("*.olden_storage_alignment.json"))
            if len(candidates) == 1:
                alignment = candidates[0]
            else:
                failures.append({"missionId": mission_id, "error": f"missing alignment at {alignment}"})
                print(f"FAIL {mission_id}: missing alignment", flush=True)
                continue

        os.environ["HOMECOMING_POC_OUT_ROOT"] = str(artifact_root)
        os.environ["HOMECOMING_POC_ARTIFACT_ROOT"] = str(artifact_root)
        os.environ["HOMECOMING_POC_ALIGNMENT_PATH"] = str(alignment)
        os.environ["HOMECOMING_POC_SUBSTITUTION_PATH"] = str(substitution_path)
        os.environ["HOMECOMING_POC_SUBSTITUTION_BASENAME"] = substitution_path.name.replace(
            ".json", ""
        )

        # Refresh module path globals that were bound at import time.
        basename = os.environ["HOMECOMING_POC_SUBSTITUTION_BASENAME"]
        sub_mod.OUT_ROOT = artifact_root
        sub_mod.ALIGNMENT_PATH = alignment
        sub_mod.OUT_DIR = artifact_root / "entity_substitutions"
        sub_mod._SUBSTITUTION_BASENAME = basename
        sub_mod.OUT_PATH = sub_mod.OUT_DIR / f"{basename}.json"
        sub_mod._REPORT_BASENAME = basename.replace(".olden_entity_substitution_map", "")
        sub_mod.REPORT_PATH = (
            sub_mod.OUT_DIR / f"{sub_mod._REPORT_BASENAME.upper()}_OLDEN_ENTITY_SUBSTITUTION_MAP_REPORT.md"
        )

        print(f"[{i}/{len(rows)}] substitution {mission_id}", flush=True)
        try:
            code = sub_mod.main()
        except Exception as exc:
            failures.append({"missionId": mission_id, "error": f"{type(exc).__name__}: {exc}"})
            print(f"FAIL {mission_id}: {type(exc).__name__}: {exc}", flush=True)
            continue
        if code != 0:
            failures.append({"missionId": mission_id, "error": f"exit {code}"})
            print(f"FAIL {mission_id}: exit {code}", flush=True)
            continue

        # Prove object-136 signatures are no longer pool-classified.
        payload = json.loads(substitution_path.read_text(encoding="utf-8"))
        bad = []
        for entry in payload.get("invalidEntitySubstitutions") or []:
            if not isinstance(entry, dict):
                continue
            if int(entry.get("templateObjectId") or -1) != 136 and "unmapped.136" not in str(
                entry.get("sourceSignature") or ""
            ):
                continue
            rule = str(entry.get("ruleName") or "")
            sid = str(entry.get("replacementSid") or "")
            if "pool" in rule or sid.startswith("pool"):
                bad.append((entry.get("sourceSignature"), rule, sid))
            for ov in entry.get("placementOverrides") or []:
                if not isinstance(ov, dict):
                    continue
                ov_rule = str(ov.get("ruleName") or "")
                ov_sid = str(ov.get("replacementSid") or "")
                if "pool" in ov_rule or ov_sid.startswith("pool"):
                    bad.append((entry.get("sourceSignature"), ov_rule, ov_sid))
        if bad:
            failures.append({"missionId": mission_id, "error": f"still pool-mapped: {bad[:3]}"})
            print(f"FAIL {mission_id}: still pool-mapped {bad[:3]}", flush=True)
        else:
            print(f"ok {mission_id}", flush=True)

    elapsed = time.perf_counter() - t0
    report = {
        "ok": not failures,
        "missionCount": len(rows),
        "failures": failures,
        "elapsedSec": round(elapsed, 2),
    }
    out = ROOT / "artifacts" / "campaign_port_poc" / "_outcropping_136_substitution_rebuild.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
