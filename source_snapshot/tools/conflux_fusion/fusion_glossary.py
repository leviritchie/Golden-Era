"""Elemental Fusion glossary data: every fusion (stage 1 pairs + stage 2 recipes) with the built unit's stats and kit.

Reads the built Core zip (units_logics / units_views rows + english Lang) and fusion_config.json, so the glossary always
shows what the game will load. Used by the glossary mockup; the in-game window reads the same fields from the live DB.

    python tools/conflux_fusion/fusion_glossary.py --core <Core.custom_biome_pack.zip> --out <glossary.json>
"""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "custom_factions/conflux_fusion/fusion_config.json"
RANK_NAMES = {1: "Basic", 2: "Advanced", 3: "Expert"}


def load_rows(z: zipfile.ZipFile, folder: str) -> dict:
    rows = {}
    for n in z.namelist():
        if n.startswith(f"DB/units/{folder}/") and n.endswith(".json"):
            for row in json.loads(z.read(n).decode("utf-8-sig")).get("array") or []:
                if isinstance(row, dict) and row.get("id"):
                    rows[row["id"]] = row
    return rows


def load_lang(z: zipfile.ZipFile) -> dict:
    out = {}
    for n in z.namelist():
        if n.startswith("Lang/english/texts/") and n.endswith(".json"):
            try:
                data = json.loads(z.read(n).decode("utf-8-sig"))
            except ValueError:
                continue
            for t in data.get("tokens") or []:
                if isinstance(t, dict) and "sid" in t:
                    out[t["sid"]] = t.get("text", "")
    return out


def build(core: Path) -> list[dict]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    tier_lines = {int(k): set(v) for k, v in cfg["tierLines"].items()}
    line_of = {sid: line for line, sids in cfg["lines"].items() for sid in sids}
    rank_of_line = {line: min(k for k, v in tier_lines.items() if line in v) for line in cfg["lines"]}
    with zipfile.ZipFile(core) as z:
        logics, views, lang = load_rows(z, "units_logics"), load_rows(z, "units_views"), load_lang(z)

    def name(sid):
        return lang.get(f"{sid}_name") or sid

    def cards(view, key):
        return [{"name": lang.get(c.get("name"), c.get("name")), "description": lang.get(c.get("description"), c.get("description")), "icon": c.get("icon")}
                for c in view.get(key) or [] if isinstance(c, dict)]

    rank = {}
    entries = []
    for stage, rows in ((1, cfg["pairs"]), (2, cfg["recipes"])):
        for p in rows:
            sid = p["fused"]
            if stage == 1:
                r = max(rank_of_line[line_of[p["a"]]], rank_of_line[line_of[p["b"]]])
            else:
                r = max(cfg.get("recipeMinRank", 1), rank[p["a"]], rank[p["b"]])
            rank[sid] = r
            logic, view = logics.get(sid), views.get(sid)
            if logic is None or view is None:
                raise SystemExit(f"{sid} missing from {core}")
            s = logic["stats"]
            attacks = [a.get("attackType_") for a in logic.get("defaultAttacks") or [] if isinstance(a, dict)]
            entries.append({
                "sid": sid, "name": name(sid), "stage": stage,
                "parents": [name(p["a"]), name(p["b"])], "parentSids": [p["a"], p["b"]],
                "host": name(p["host"]),
                "rank": r, "rankName": RANK_NAMES[r],
                "squadValue": logic.get("squadValue"),
                "hp": s.get("hp"), "attack": s.get("offence"), "defence": s.get("defence"),
                "damageMin": s.get("damageMin"), "damageMax": s.get("damageMax"),
                "speed": s.get("speed"), "initiative": s.get("initiative"),
                "ranged": "shoot" in attacks,
                "abilities": cards(view, "abilities"), "passives": cards(view, "passives"),
            })
    return entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    entries = build(a.core)
    a.out.write_text(json.dumps({"schema": "homm3_conflux_fusion_glossary.v1", "entries": entries}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(entries)} fusions -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
