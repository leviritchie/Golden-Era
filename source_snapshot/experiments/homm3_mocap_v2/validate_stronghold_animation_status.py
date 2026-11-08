"""Validate the read-only Stronghold animation roster inventory."""
import json
from pathlib import Path


def validate(status_path, faction_path):
    status = json.loads(Path(status_path).read_text(encoding="utf-8"))
    faction = json.loads(Path(faction_path).read_text(encoding="utf-8"))
    expected = [(line["tier"], name, line["baseSid"] if i == 0 else line["baseSid"] + ("_upg" if i == 1 else "_upg_alt"))
                for line in faction["unitLines"] for i, name in enumerate(line["names"])]
    rows = status.get("units", [])
    if len(rows) != len(expected):
        raise ValueError(f"status contains {len(rows)} units, expected {len(expected)}")
    keys = [(row.get("tier"), row.get("name")) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("status contains duplicate tier/name entries")
    missing = sorted(set((tier, name) for tier, name, _ in expected) - set(keys))
    if missing:
        raise ValueError(f"status is missing configured units: {missing}")
    required = {"sid", "mesh", "profile", "preparation", "corpus", "fit", "status"}
    if any(not required.issubset(row) for row in rows):
        raise ValueError("every status row must explicitly include all evidence fields")
    root = Path(status_path).resolve().parents[2]
    referenced = [row[field] for row in rows for field in ("mesh", "profile", "preparation", "corpus", "fit") if row[field]]
    missing_paths = [path for path in referenced if not (root / path).exists()]
    if missing_paths:
        raise ValueError(f"referenced artifact paths do not exist: {missing_paths}")
    for row in rows:
        if row.get("evidenceAsset"):
            if not row.get("fit"):
                raise ValueError("evidenceAsset requires a fit report")
            report = json.loads((root / row["fit"]).read_text(encoding="utf-8"))
            if report.get("asset") != row["evidenceAsset"]:
                raise ValueError(f"fit report asset {report.get('asset')} does not match evidenceAsset {row['evidenceAsset']}")
    mismatched_sid = [row["name"] for row, (_, _, sid) in zip(rows, expected) if row.get("sid") != sid]
    if mismatched_sid:
        raise ValueError(f"status SID does not match configured variant mapping: {mismatched_sid}")
    return {"unitCount": len(rows), "configuredCount": len(expected), "inventoryValid": True}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--status", required=True); parser.add_argument("--faction", required=True)
    args = parser.parse_args(); print(json.dumps(validate(args.status, args.faction), indent=2))
