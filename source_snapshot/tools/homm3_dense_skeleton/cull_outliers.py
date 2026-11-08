#!/usr/bin/env python3
"""Cull outlier digitized samples (MAD + topology + bone-length)."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from constants import BONE_EDGES, JOINT_ORDER, OUT, REQUIRED_CORE  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _joint_xy(rec: dict, name: str) -> tuple[float, float] | None:
    j = (rec.get("joints") or {}).get(name)
    if not j or not j.get("visible", True):
        return None
    return float(j["nx"]), float(j["ny"])


def _topology_ok(rec: dict) -> tuple[bool, str]:
    mid = _joint_xy(rec, "MidHip")
    neck = _joint_xy(rec, "Neck")
    tip = _joint_xy(rec, "WeaponTip")
    rw = _joint_xy(rec, "RWrist")
    lw = _joint_xy(rec, "LWrist")
    if not mid or not neck:
        return False, "missing_torso"
    if mid[1] < neck[1] - 0.02:
        # image y down: MidHip should be below Neck (larger y)
        return False, "midhip_above_neck"
    if tip and rw and lw:
        d_r = (rw[0] - tip[0]) ** 2 + (rw[1] - tip[1]) ** 2
        d_l = (lw[0] - tip[0]) ** 2 + (lw[1] - tip[1]) ** 2
        if d_r > d_l * 1.35:
            return False, "strike_wrist_farther_than_support"
    return True, "ok"


def _bone_lengths(rec: dict) -> dict[str, float]:
    out = {}
    for a, b in BONE_EDGES:
        pa, pb = _joint_xy(rec, a), _joint_xy(rec, b)
        if pa and pb:
            out[f"{a}-{b}"] = float(math.hypot(pa[0] - pb[0], pa[1] - pb[1]))
    return out


def _mad_mask(vals: np.ndarray, thresh: float = 3.5) -> np.ndarray:
    """True = keep. vals shape (N,2)."""
    if len(vals) < 2:
        return np.ones(len(vals), dtype=bool)
    med = np.median(vals, axis=0)
    dist = np.linalg.norm(vals - med, axis=1)
    mad = np.median(np.abs(dist - np.median(dist)))
    if mad < 1e-6:
        return dist <= 0.08  # all nearly identical; drop far absolute outliers only
    score = 0.6745 * dist / mad
    return score <= thresh


def cull_group(recs: list[dict], *, mad_thresh: float = 3.5, max_joint_fail_frac: float = 0.35) -> dict:
    """Cull within one (frame, angle) group."""
    alive = [r for r in recs if r.get("ok")]
    dropped = [{"path": r.get("path"), "reason": r.get("error", "digitize_fail")} for r in recs if not r.get("ok")]

    topo_kept = []
    for r in alive:
        ok, why = _topology_ok(r)
        if ok:
            topo_kept.append(r)
        else:
            dropped.append({"path": r.get("path"), "reason": f"topology:{why}"})

    if len(topo_kept) < 1:
        return {
            "kept": [],
            "dropped": dropped,
            "keptCount": 0,
            "droppedCount": len(dropped),
            "inputCount": len(recs),
            "reason": "no_topology_survivors",
        }

    # Bone length medians
    length_maps = [_bone_lengths(r) for r in topo_kept]
    keys = set().union(*(m.keys() for m in length_maps))
    med_len = {}
    for k in keys:
        vals = [m[k] for m in length_maps if k in m]
        if vals:
            med_len[k] = float(np.median(vals))

    length_kept = []
    for r, lm in zip(topo_kept, length_maps):
        bad = 0
        checked = 0
        for k, med in med_len.items():
            if k not in lm or med < 1e-6:
                continue
            checked += 1
            if abs(lm[k] - med) / med > 0.55:
                bad += 1
        if checked and bad / checked > 0.4:
            dropped.append({"path": r.get("path"), "reason": "bone_length_outlier"})
        else:
            length_kept.append(r)

    if not length_kept:
        return {
            "kept": [],
            "dropped": dropped,
            "keptCount": 0,
            "droppedCount": len(dropped),
            "inputCount": len(recs),
            "reason": "no_length_survivors",
        }

    # Per-joint MAD across samples (skip when too few samples — MAD is unstable at N=2).
    if len(length_kept) < 3:
        return {
            "kept": length_kept,
            "dropped": dropped,
            "keptCount": len(length_kept),
            "droppedCount": len(dropped),
            "inputCount": len(recs),
            "madSkipped": True,
        }

    joint_keep_flags = {i: [] for i in range(len(length_kept))}
    for jname in JOINT_ORDER:
        pts = []
        idxs = []
        for i, r in enumerate(length_kept):
            xy = _joint_xy(r, jname)
            if xy is None:
                continue
            pts.append(xy)
            idxs.append(i)
        if len(pts) < 2:
            for i in idxs:
                joint_keep_flags[i].append(True)
            continue
        mask = _mad_mask(np.asarray(pts, dtype=np.float64), thresh=mad_thresh)
        for i, keep in zip(idxs, mask.tolist()):
            joint_keep_flags[i].append(bool(keep))

    final = []
    for i, r in enumerate(length_kept):
        flags = joint_keep_flags[i]
        if not flags:
            dropped.append({"path": r.get("path"), "reason": "no_joint_flags"})
            continue
        fail_frac = 1.0 - (sum(1 for f in flags if f) / len(flags))
        if fail_frac > max_joint_fail_frac:
            dropped.append({"path": r.get("path"), "reason": f"mad_joint_fail_frac={fail_frac:.2f}"})
        else:
            final.append(r)

    return {
        "kept": final,
        "dropped": dropped,
        "keptCount": len(final),
        "droppedCount": len(dropped),
        "inputCount": len(recs),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", type=Path, default=OUT / "digitize" / "samples.jsonl")
    ap.add_argument("--out", type=Path, default=OUT / "digitize" / "culled_report.json")
    ap.add_argument("--mad-thresh", type=float, default=3.5)
    args = ap.parse_args()
    if not args.samples.is_file():
        print(f"missing {args.samples}", file=sys.stderr)
        return 2
    rows = _load_jsonl(args.samples)
    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(int(r["frameIndex"]), str(r["angle"]))].append(r)

    by_group = {}
    kept_all = []
    for key, recs in sorted(groups.items()):
        res = cull_group(recs, mad_thresh=args.mad_thresh)
        by_group[f"f{key[0]:02d}/{key[1]}"] = {
            "keptCount": res["keptCount"],
            "droppedCount": res["droppedCount"],
            "inputCount": res["inputCount"],
            "dropped": res["dropped"],
            "keptPaths": [k.get("path") for k in res["kept"]],
        }
        kept_all.extend(res["kept"])

    if not kept_all:
        report = {"ok": False, "error": "no samples survived cull", "groups": by_group}
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    kept_path = args.out.parent / "samples_culled.jsonl"
    with kept_path.open("w", encoding="utf-8") as fh:
        for r in kept_all:
            fh.write(json.dumps(r) + "\n")

    report = {
        "ok": True,
        "keptTotal": len(kept_all),
        "inputTotal": len(rows),
        "culledJsonl": str(kept_path).replace("\\", "/"),
        "groups": by_group,
        "proof": "generated artifact validated — MAD/topology cull; not mocap",
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "keptTotal": len(kept_all), "inputTotal": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
