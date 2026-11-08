"""Quality census of every custom-faction and neutral homm3_import.json row: what the game shows now and whether it passes.

    python tools/homm3_def_retarget_delivery/quality_census.py [--out tools/homm3_def_retarget_delivery/census/quality_census.json]

Read-only over the repo, the artifact chain and the installed game (bundles, Core.zip, BepInEx/LogOutput.log). Per row:

  lane         what the installed bundle is, by bytes: `fleet_slice` (its sha256 equals the bundle a fleet selection
               installed, per <out>/installed_readback.json), `stopgap` (custom_factions/contracts/
               homm3_unit_presentation_stopgaps.json names it), otherwise `older_owned_skinned` (an earlier lane's
               bundle: mocap / Meshy smart-rig / hand rig). A row whose selection froze a build that is not what is
               installed says so in `frozenNotInstalled`.
  meshIdentity the mesh repair ledger's identity verdict (verified_correct / unresolved_provenance), the stopgap
               contract's declaredMeshIdentity, and MESH_OVERRIDES (regenerations after the ledger was written).
  gates        fleet_slice rows only, measured on the frozen delivered_idle_retimed.glb that was bundled:
               articulation (flyer_articulation.gate on Unit_Move: wings / legs / toy ratio / jitter), freeze
               (flyer_articulation.freeze_check on every clip: no pose held 3+ DEF frames while the DEF moves), facing
               (idle frame 0 forward within the facing contract, or its allowlist), stride (stride_match_glb
               measure). Older-lane rows are `unmeasured`: their clips are not a fleet build and they are queued.
  texture      runtime log evidence from the current LogOutput.log: `bound` (the lane loaded the lab's own bundle
               texture and no albedo check failed), `failed` (albedo check or Hex/Lit rebind error), `not_seen`.
  visibility   squads on custom / campaign maps in Core.zip that place the unit (any of its game sids): the count
               orders the rebuild queue after user-reported units.
  lastReview   the date this effort last looked at the row (the selection freeze, a named review, or this census).

Proof tier: generated-artifact + installed-payload census (static reads); nothing here is runtime or user-visible proof
except the `texture` column, which quotes the game's own log.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fleet_census import IMPORT, LEDGER, ROOT, STOPGAPS, load  # noqa: E402
from flyer_articulation import GATE_CLIP, freeze_check, gate as articulation_gate, glb_clips, move_rule, wing_rule  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from validate_homm3_owned_skinned_facing_contract import GLB_FORWARD_TOL, glb_idle0_forward_rule  # noqa: E402

GAME = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
BUNDLES = GAME / "BepInEx/plugins/OfflineUnlockMod/homm3_bundles"
LOG = GAME / "BepInEx/LogOutput.log"
CORE_ZIP = GAME / "HeroesOldenEra_Data/StreamingAssets/Core.zip"
FACING_ALLOW = ROOT / "tools/homm3_owned_skinned_facing_allowlist.json"
ART_DEBT = ROOT / "tools/homm3_owned_skinned_articulation_debt.json"
TODAY = datetime.date.today().isoformat()

# Units the user reported in game; they head the queue whatever their map count.
USER_REPORTED = {
    "h3_cavalier": "2026-09-26 user: 'very jittery with poorly articulated motion, like the old mesh and animation' (old lane in game)",
    "h3_champion": "same line as h3_cavalier (coordinator: de-yawed cavalier/champion/justiciar are the re-freeze priority)",
    "h3_justiciar": "same line as h3_cavalier",
    "h3_royal_griffin": "coordinator 2026-09-26: the user named griffins specifically (wings do not beat)",
    "h3_battle_griffin": "coordinator 2026-09-26: the user named griffins specifically (wings do not beat)",
}
# Mesh regenerations after the repair ledger was written (lab sid -> verdict).
MESH_OVERRIDES = {
    "h3_royal_griffin": "regenerated_2026-09-26: Meshy-7 wings-spread rest mesh installed (identity_regen/h3_royal_griffin); "
                        "folded-wing mesh superseded; not yet re-rigged or shipped",
    "h3_battle_griffin": "regenerated_2026-09-26: Meshy-7 wings-spread rest mesh installed (identity_regen/h3_battle_griffin); "
                         "folded-wing mesh superseded; not yet re-rigged or shipped",
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fleet_index():
    """bundle -> [{selection, sha256, bytes, labSid, retimed, frozenAt}] for every installed fleet selection."""
    idx, frozen = {}, {}
    for sp in sorted(HERE.glob("*_slice_v1.json")):
        s = load(sp)
        if s.get("schema") != "homm3_def_retarget_delivery_selection.v1":
            continue
        out = ROOT / s["out"]
        rb = load(out / "installed_readback.json") or {}
        at = datetime.datetime.fromtimestamp(sp.stat().st_mtime).date().isoformat()
        by_bundle = {r["bundleName"]: r for r in s["units"]}
        for r in s["units"]:
            frozen.setdefault(r["labSid"], []).append({"selection": sp.stem, "installed": bool(rb), "frozenAt": at})
        for b in rb.get("bundles", []):
            r = by_bundle.get(b["bundle"])
            if r:
                idx.setdefault(b["bundle"], []).append({"selection": sp.stem, "sha256": b["sha256"], "bytes": b.get("bytes"),
                                                       "labSid": r["labSid"], "frozenAt": at,
                                                       "retimed": out / r["labSid"] / "delivered_idle_retimed.glb"})
    return idx, frozen


def squad_counts(sids: set[str]) -> dict[str, int]:
    """Squads in Core.zip DB/squads/ whose file stem ends with _<sid>_x<N> (longest sid wins)."""
    counts = dict.fromkeys(sids, 0)
    by_len = sorted(sids, key=len, reverse=True)
    with zipfile.ZipFile(CORE_ZIP) as z:
        for n in z.namelist():
            if not n.startswith("DB/squads/") or not n.endswith(".json"):
                continue
            m = re.match(r"(.*)_x\d+$", n.rsplit("/", 1)[-1][:-5])
            if not m:
                continue
            stem = m.group(1)
            hit = next((s for s in by_len if stem.endswith("_" + s) or stem == s), None)
            if hit:
                counts[hit] += 1
    return counts


def log_texture(labs: set[str]) -> tuple[dict[str, str], str | None]:
    if not LOG.is_file():
        return {}, None
    text = LOG.read_text(encoding="utf-8", errors="replace")
    stamp = datetime.datetime.fromtimestamp(LOG.stat().st_mtime).isoformat(timespec="seconds")
    res = {}
    for lab in labs:
        pre = f"homm3_lab/{lab}/"
        bad = [ln for ln in text.splitlines() if pre in ln and ("albedo check failed" in ln or "rebind failed" in ln)]
        if bad:
            res[lab] = "failed: " + bad[-1][-200:]
        elif f"loaded bundle texture 'Assets/CustomUnits/{pre}" in text:
            res[lab] = "bound"
        else:
            res[lab] = "not_seen"
    return res, stamp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=HERE / "census/quality_census.json")
    args = ap.parse_args()

    table = load(IMPORT)
    ledger = {r["unitSid"]: r for r in load(LEDGER)["rows"]}
    stop = load(STOPGAPS)
    stopgaps, declared = stop["stopgaps"], stop["declaredMeshIdentity"]
    allow = set(load(FACING_ALLOW)["units"])
    debt = {(d["selection"], d["labSid"]) for d in load(ART_DEBT).get("entries", [])}
    fleet, frozen = fleet_index()
    labs = {e["battlePrefabAssetPath"].split("/")[3] for e in table["entries"]}
    tex, log_at = log_texture(labs)
    all_game = {g for e in table["entries"] for g in e.get("gameUnitSids", [])}
    squads = squad_counts(all_game | labs)

    rows = []
    for e in table["entries"]:
        lab = e["battlePrefabAssetPath"].split("/")[3]
        game = e.get("gameUnitSids", [])
        faction = e["battleResPath"].split("/")[2]
        bundle = BUNDLES / e["bundleName"]
        r = {"labSid": lab, "gameSids": game, "faction": faction, "bundleName": e["bundleName"],
             "visibilitySquads": sum(squads.get(s, 0) for s in set(game) | {lab})}
        inst = sha(bundle) if bundle.is_file() else None
        r["installedBundleSha256"] = inst
        hit = next((f for f in fleet.get(e["bundleName"], []) if f["sha256"] == inst), None)
        in_stop = [g for g in [lab, *game] if g in stopgaps]
        if inst is None:
            r["lane"] = "missing_bundle"
        elif hit:
            r["lane"], r["laneSource"] = "fleet_slice", hit["selection"]
        elif in_stop:
            r["lane"], r["laneSource"] = "stopgap", f"{in_stop[0]}: {stopgaps[in_stop[0]]['class']}"
        else:
            r["lane"] = "older_owned_skinned"
        fz = [f for f in frozen.get(lab, []) if not (hit and f["selection"] == hit["selection"])]
        if fz:
            r["frozenNotInstalled"] = fz

        # mesh identity
        lr = ledger.get(lab) or next((ledger[g] for g in game if g in ledger), None)
        mi = {"ledger": lr["identity"]["status"] if lr else "no_ledger_row"}
        dm = [g for g in [lab, *game] if g in declared]
        if dm:
            mi["declared"] = declared[dm[0]]["evidence"][:200]
        if lab in MESH_OVERRIDES:
            mi["override"] = MESH_OVERRIDES[lab]
        if in_stop:
            mi["stopgap"] = ", ".join(stopgaps[in_stop[0]]["issues"])
        mi["verdict"] = ("regenerated" if lab in MESH_OVERRIDES else "wrong_or_borrowed" if in_stop else
                         "declared_source_ok_bundle_stale" if dm else
                         "verified" if mi["ledger"] == "verified_correct" else "unverified")
        r["meshIdentity"] = mi

        # gates on what is installed
        if hit:
            clips = glb_clips(hit["retimed"])
            move = clips.get(GATE_CLIP)
            bad = ["no " + GATE_CLIP] if move is None else articulation_gate(move, lab)
            keep = {k: move.get(k) for k in ("wingSwing", "wingRange", "legSwing", "bodyRot", "toyRatio", "jitterP90")} if move else {}
            r["articulation"] = {"pass": not bad, "faults": bad, "move": keep,
                                 "wingRule": list(wing_rule(lab)) if move and move.get("wingBones") else None,
                                 "moveRule": move_rule(lab),
                                 "debtListed": (hit["selection"], lab) in debt}
            try:
                # a <source>:<lab sid> freeze (toa_boar_rider from h3_boar_rider) measures against the source
                # unit's DEF; the slice's look stamp names that unit
                stamp = Path(hit["retimed"]).parent / "inputs/stamp.json"
                src_unit = json.loads(stamp.read_text(encoding="utf-8"))["unit"] if stamp.is_file() else lab
                fbad, frec = freeze_check(src_unit, Path(hit["retimed"]), Path(hit["retimed"]).parent / "inputs/look_delivered.glb")
            except SystemExit as e:
                fbad, frec = [str(e)], {}
            r["freeze"] = {"pass": not fbad, "faults": fbad, "measuredOn": {c: v.get("glb") for c, v in frec.items()}}
            f, frule, _ = glb_idle0_forward_rule(hit["retimed"])
            ang = None if f is None else round(math.degrees(math.atan2(f[0], f[2])), 1)
            ok = ang is not None and abs(ang) <= GLB_FORWARD_TOL
            r["facing"] = {"pass": ok or lab in allow, "idle0YawDeg": ang, "rule": frule, "allowlisted": lab in allow}
            r["lastReview"] = hit["frozenAt"]
        else:
            r["articulation"] = {"pass": None, "faults": ["unmeasured: installed bundle is not a fleet build"]}
            r["freeze"] = {"pass": None, "faults": ["unmeasured: installed bundle is not a fleet build"]}
            r["facing"] = {"pass": None, "allowlisted": lab in allow}
            r["lastReview"] = max((f["frozenAt"] for f in frozen.get(lab, [])), default=None)
        r["texture"] = tex.get(lab, "not_seen")

        # verdict + queue
        why = []
        if r["lane"] != "fleet_slice":
            why.append(f"lane {r['lane']}")
        if r["articulation"]["pass"] is False:
            why.append("articulation: " + "; ".join(r["articulation"]["faults"])[:160])
        if r["freeze"]["pass"] is False:
            why.append("freeze: " + "; ".join(r["freeze"]["faults"])[:160])
        if r["facing"]["pass"] is False:
            why.append(f"facing yaw {r['facing'].get('idle0YawDeg')}")
        if r["texture"].startswith("failed"):
            why.append("texture binding failed in the game log")
        if mi["verdict"] in ("wrong_or_borrowed", "declared_source_ok_bundle_stale", "regenerated"):
            why.append(f"mesh {mi['verdict']}")
        r["ok"] = not why
        r["queueReasons"] = why
        if lab in USER_REPORTED:
            r["userReported"] = USER_REPORTED[lab]
        rows.append(r)
        print(f"{lab:30s} {faction:10s} {r['lane']:20s} sq={r['visibilitySquads']:4d} {'OK' if r['ok'] else '; '.join(why)[:110]}",
              flush=True)

    queue = sorted((r for r in rows if not r["ok"]),
                   key=lambda r: (0 if "userReported" in r else 1, -r["visibilitySquads"], r["labSid"]))
    for k, r in enumerate(queue, 1):
        r["queueRank"] = k
    counts = {}
    for r in rows:
        counts.setdefault(r["lane"], 0)
        counts[r["lane"]] += 1
    out = {"schema": "homm3_unit_quality_census.v1", "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
           "generator": "tools/homm3_def_retarget_delivery/quality_census.py",
           "proof": "installed-payload + generated-artifact census (static reads); texture column quotes the game log",
           "gameLog": {"path": str(LOG), "modifiedAt": log_at},
           "queueOrder": "user-reported first, then squads placing the unit on custom/campaign maps (Core.zip DB/squads), descending",
           "counts": {"rows": len(rows), "byLane": counts, "ok": sum(r["ok"] for r in rows), "queued": len(queue),
                      "articulationFail": sum(r["articulation"]["pass"] is False for r in rows),
                      "facingFail": sum(r["facing"]["pass"] is False for r in rows),
                      "textureFailed": sum(r["texture"].startswith("failed") for r in rows),
                      "textureBoundInLog": sum(r["texture"] == "bound" for r in rows)},
           "queue": [{"rank": r["queueRank"], "labSid": r["labSid"], "faction": r["faction"], "squads": r["visibilitySquads"],
                      "why": r["queueReasons"]} for r in queue],
           "rows": rows}
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["counts"]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
