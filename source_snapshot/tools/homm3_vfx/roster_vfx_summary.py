"""Ranked roster and per-faction summaries from inventory.json (called by roster_vfx_inventory.py).

Usage (standalone re-render): python tools/homm3_vfx/roster_vfx_summary.py
"""
from __future__ import annotations

import json
import os

TIER_ORDER = {"effect_heavy": 0, "attack_accents": 1, "none": 2}
RETARGET_GROUP = {0: "Unit_Move", 1: "Unit_Mouseover", 2: "Unit_Idle", 3: "Unit_Hitted", 4: "Unit_Defence", 5: "Unit_Death",
                  12: "Unit_AttackFront", 15: "Unit_ShootFront", 20: "Unit_MoveStart", 21: "Unit_MoveEnd"}


def unit_lines(u, r):
    """Short human-readable effect list for one unit."""
    out = []
    ise = r.get("idleSelfEffect", {}).get("classes", {})
    for c, v in ise.items():
        if v.get("animated") and v["bodyShare"] >= 0.05:
            out.append(f"idle self-{c}: {v['bodyShare']:.0%} of body, flicker {v['flicker']:.2f} (animated: texture/uvAtlas or flipbook, not a bake)")
        elif v.get("steadyGlowCandidate"):
            out.append(f"idle steady {c}: {v['bodyShare']:.0%} of body, flicker {v['flicker']:.2f} (bakedGlow candidate, check it is not body paint)")
    if r.get("translucency", {}).get("ghostly"):
        t = r["translucency"]
        out.append(f"ghostly translucency: dither {t['ditherMax']:.2f}, semi-on-body {t['semiOnBodyMax']:.2f}")
    for g, gd in sorted(r["groups"].items(), key=lambda kv: int(kv[0])):
        for e in gd["events"]:
            if e.get("posePaintSuspect"):
                continue
            bones = e.get("boneCandidatesAtOrigin") or e.get("boneCandidatesAtPeak") or []
            b = f", bone {bones[0]['bone']} ({bones[0]['distPx']} px)" if bones else ""
            hold = f", holds {e['fxHolds']}" if e["fxHolds"] else ""
            rt = "" if gd["inRetarget"] else " [group not in retarget]"
            out.append(f"g{int(g):02d} {gd['name']}{rt}: {e['kind']}, frames {e['frames'][0]}-{e['frames'][-1]}, peak {e['peakPx']} px "
                       f"({e['peakShareOfBody']:.0%} body) @f{e['peakFrame']}, {e['motion']}, origin {e['regionAtOrigin']}{b}{hold}")
    if r.get("shooter"):
        p = r.get("projectile", {})
        sub = p.get("overlayNativeSubstitute")
        out.append("shooter: " + (f"overlay native substitute {sub['projectile']} ({sub['trajectory']})" if sub else "no overlay projectile mapping under this unit id"))
    return out


def write(inv, out_dir):
    # projectile lookup also under the release SID alias (hota_cove_pirate -> h3_pirate)
    import re
    from roster_vfx_inventory import projectile_specs
    proj = projectile_specs()
    for u, r in inv["units"].items():
        if r.get("shooter") and not r.get("projectile", {}).get("overlayNativeSubstitute"):
            alias = re.sub(r"^(hota_[a-z]+|toa|temple)_", "h3_", u)
            if proj.get(alias):
                r["projectile"].update({"overlayNativeSubstitute": proj[alias], "lookedUp": sorted({u, alias}),
                                        "status": "native substitute mapped by overlay SID"})
    units = {u: r for u, r in inv["units"].items() if "error" not in r}
    errs = {u: r["error"] for u, r in inv["units"].items() if "error" in r}
    ranked = sorted(units.items(), key=lambda kv: (TIER_ORDER[kv[1]["tier"]], -kv[1]["score"], kv[0]))
    counts = {t: sum(1 for _, r in ranked if r["tier"] == t) for t in TIER_ORDER}
    md = ["# Roster VFX inventory (DEF-measured)", "",
          "Proof: generated artifact. Measured from the extracted DEF PNGs the def_retarget consumed "
          "(`tools/homm3_vfx/roster_vfx_inventory.py`, rules in `def_effects.py`). Heuristic detection: "
          "check each unit's `sheets/<unit>.png` before building layers. Nothing here is rendered or in game.", "",
          f"Units: {len(units)} measured ({counts['effect_heavy']} effect-heavy, {counts['attack_accents']} attack accents only, "
          f"{counts['none']} none), {len(errs)} errors.", "",
          "Tiers: **effect_heavy** = animated self-effect in idle, or one large effect (>=12% of the body), or effects in 3+ clips; "
          "**attack_accents** = smaller effects only; **none** = nothing above the per-unit threshold. "
          "`[group not in retarget]` = the DEF draws it in a group the GLB has no clip for (attack/shoot up/down, cast).", ""]
    for tier in TIER_ORDER:
        md.append(f"## {tier}")
        md.append("")
        for u, r in ranked:
            if r["tier"] != tier:
                continue
            fac = ",".join(sorted({f["faction"] for f in r.get("factions", [])})) or "-"
            ex = f" **EXCLUDED: {r['excluded']}**" if r.get("excluded") else ""
            md.append(f"- `{u}` ({r['def']}, {fac}, score {r['score']}){ex}")
            if tier != "none":
                for line in unit_lines(u, r):
                    md.append(f"  - {line}")
        md.append("")
    if errs:
        md.append("## errors")
        md += [f"- `{u}`: {e}" for u, e in sorted(errs.items())]
    open(os.path.join(out_dir, "inventory_summary.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")

    fac_units: dict[str, list] = {}
    for u, r in units.items():
        for f in {f["faction"] for f in r.get("factions", [])} or {"_unassigned"}:
            fac_units.setdefault(f, []).append(u)
    os.makedirs(os.path.join(out_dir, "factions"), exist_ok=True)
    for fac, us in sorted(fac_units.items()):
        us = sorted(us, key=lambda u: (TIER_ORDER[units[u]["tier"]], -units[u]["score"], u))
        data = {"faction": fac, "schema": "homm3_vfx_roster_faction.v1", "proof": inv.get("proof"),
                "units": [{"unit": u, "def": units[u]["def"], "tier": units[u]["tier"], "score": units[u]["score"],
                           "excluded": units[u].get("excluded"), "roster": [f for f in units[u].get("factions", []) if f["faction"] == fac],
                           "sheet": units[u].get("sheet"), "effects": unit_lines(u, units[u]),
                           "ripperCandidates": ripper_candidates(units[u])} for u in us]}
        json.dump(data, open(os.path.join(out_dir, "factions", f"{fac}.json"), "w"), indent=1)
        lines = [f"# {fac}: DEF effect inventory", "",
                 "Generated from `inventory.json`; proof = generated artifact (DEF measurement, heuristic). "
                 "Rip with `python tools/homm3_vfx/def_effect_ripper.py <unit> --auto` (see the tool docstring) and "
                 "check the unit's sheet first.", ""]
        for d in data["units"]:
            ex = f" **EXCLUDED: {d['excluded']}**" if d["excluded"] else ""
            lines.append(f"## `{d['unit']}` ({d['def']}) - {d['tier']}{ex}")
            if d["sheet"]:
                lines.append(f"Sheet: `{d['sheet']}`")
            lines += [f"- {x}" for x in d["effects"]] or ["- no DEF-drawn effect above threshold"]
            if d["ripperCandidates"]:
                lines.append("- ripper candidates (retarget clips only): " + "; ".join(
                    f"{c['clip']} g{c['defGroup']} f{c['frames'][0]}-{c['frames'][-1]} {c['class']} -> {c['bone']}" for c in d["ripperCandidates"]))
            lines.append("")
        open(os.path.join(out_dir, "factions", f"{fac}.md"), "w", encoding="utf-8").write("\n".join(lines))


def ripper_candidates(r):
    out = []
    for g, gd in r["groups"].items():
        g = int(g)
        if not gd["inRetarget"] or g not in RETARGET_GROUP:
            continue
        for e in gd["events"]:
            if e.get("posePaintSuspect"):
                continue
            bones = e.get("boneCandidatesAtOrigin") or e.get("boneCandidatesAtPeak") or []
            out.append({"clip": RETARGET_GROUP[g], "defGroup": g, "frames": e["frames"], "class": e["class"],
                        "bone": bones[0]["bone"] if bones else None, "motion": e["motion"], "kind": e["kind"]})
    return out


if __name__ == "__main__":
    here = os.path.join(r"V:/games/Olden Era Playtest Tweak", "artifacts/homm3_vfx_experiments/_roster")
    write(json.load(open(os.path.join(here, "inventory.json"))), here)
