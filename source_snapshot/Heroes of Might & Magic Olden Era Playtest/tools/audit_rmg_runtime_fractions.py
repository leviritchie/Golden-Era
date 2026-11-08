"""
Audit RMG templates + Core.zip for faction wiring relevant to custom factions.

1) map_templates/*.rmg.json — search for literal faction id strings (human, dungeon, …).
   Shipped templates use zone refs (Match / FromList / differentFrom), not faction literals.

2) Core.zip — simulate OfflineUnlockMod LoadHeroesByFraction (regex scan of DB/heroes/**/*.json):
   count heroes per fraction; compare to DB/data.json availableFractions.

3) City configs — print sceneName + fraction for known towns (clone vs vanilla).

Run:
  python audit_rmg_runtime_fractions.py
  python audit_rmg_runtime_fractions.py --core "C:/path/to/Core.zip"
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

# JSON object keys like "fraction": "dungeon" (not hero sids like dungeon_hero_1).
RMG_FRACTION_VALUE = re.compile(
    r'"fraction"\s*:\s*"(human|undead|dungeon|demon|nature|unfrozen|'
    r'homm3_stronghold|homm3_fortress|dungeon_raw)"',
    re.IGNORECASE,
)


def default_paths() -> tuple[Path, Path]:
    playtest = Path(__file__).resolve().parents[1]
    streaming = playtest / "HeroesOE_Data" / "StreamingAssets"
    return streaming / "Core.zip", streaming / "map_templates"


def load_heroes_by_fraction_plugin_style(archive: zipfile.ZipFile) -> dict[str, list[str]]:
    """Mirror OfflineUnlockMod.Plugin LoadHeroesByFraction pairing (first N id with first N fraction)."""
    result: dict[str, list[str]] = {}
    for name in archive.namelist():
        if not name.startswith("DB/heroes/") or not name.endswith(".json"):
            continue
        text = archive.read(name).decode("utf-8-sig")
        ids = re.findall(r'"id"\s*:\s*"([^"]+)"', text)
        frs = re.findall(r'"fraction"\s*:\s*"([^"]+)"', text)
        n = min(len(ids), len(frs))
        for i in range(n):
            fid, fr = ids[i], frs[i]
            if not fid or not fr:
                continue
            result.setdefault(fr, []).append(fid)
    return result


def audit_rmg_templates(map_templates_dir: Path) -> dict[str, list[str]]:
    """Return map filename -> list of quoted fraction values found (if any)."""
    out: dict[str, list[str]] = {}
    if not map_templates_dir.is_dir():
        return {"_error": [f"not a directory: {map_templates_dir}"]}
    for path in sorted(map_templates_dir.glob("*.rmg.json")):
        text = path.read_text(encoding="utf-8-sig")
        found = sorted(set(m.group(1).lower() for m in RMG_FRACTION_VALUE.finditer(text)))
        if found:
            out[path.name] = found
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--core", type=Path, help="Path to Core.zip (default: playtest StreamingAssets)")
    args = ap.parse_args()
    default_core, map_dir = default_paths()
    core_path = args.core if args.core else default_core

    print("=== RMG templates (JSON \"fraction\": \"<id>\" only) ===")
    rmg_hits = audit_rmg_templates(map_dir)
    if "_error" in rmg_hits:
        print(" ", rmg_hits["_error"][0])
    elif not rmg_hits:
        print(
            "  No hardcoded JSON fraction values in .rmg.json (expected: templates use "
            "zone ids / Match / FromList; words like dungeon_hero_* are hero SIDs, not factions)."
        )
    else:
        for fname, frs in rmg_hits.items():
            print(f"  {fname}: {', '.join(frs)}")

    print("\n=== Core.zip offline quick-start parity (hero pools) ===")
    if not core_path.is_file():
        print(f"  Missing Core.zip: {core_path}")
        return

    with zipfile.ZipFile(core_path, "r") as z:
        data = json.loads(z.read("DB/data.json").decode("utf-8-sig"))
        af = list(data.get("availableFractions") or [])
        hb = load_heroes_by_fraction_plugin_style(z)

    print(f"  availableFractions ({len(af)}): {', '.join(af)}")
    problems: list[str] = []
    for fr in af:
        n = len(hb.get(fr, []))
        status = "ok" if n > 0 else "EMPTY — offline launcher / PickFraction may skip"
        print(f"  {fr}: {n} heroes ({status})")
        if n == 0:
            problems.append(fr)

    print("\n=== City sceneName + fraction (sample) ===")
    with zipfile.ZipFile(core_path, "r") as z:
        for cid in (
            "dungeon_city",
            "dungeon_city_raw",
            "homm3_fortress_city",
            "homm3_stronghold_city",
        ):
            p = f"DB/objects_logic/cities/{cid}.json"
            if p not in z.namelist():
                print(f"  {cid}: (not in Core)")
                continue
            city = json.loads(z.read(p).decode("utf-8-sig"))["array"][0]
            print(
                f"  {cid}: sceneName={city.get('sceneName')!r} fraction={city.get('fraction')!r}"
            )

    if problems:
        print("\n  Fractions with no heroes (fix Core hero JSON or regex pairing bug):", ", ".join(problems))


if __name__ == "__main__":
    main()
