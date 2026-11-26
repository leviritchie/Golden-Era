#!/usr/bin/env python3
"""Splice freshly assembled rebuild rows into a ``<faction>_rebuild_v1.json`` selection.

Coordinator step between ``assemble_rebuild_slice.py`` (which writes a temp selection)
and ``ship_def_retarget_slice.py``. For every assembled row it:

* keeps the existing row's ``attackTiming`` unless the unit's sandbox
  ``<rebuild-root>/<labSid>/rebuild_report.json`` provides a newer one
  (``attackTiming.<clip>.hit`` seconds; family workers write that file);
* checks ``frozen.basecolorSha256``: it must equal the current row's sha, or the
  graded texture recorded in ``<retexture-dir>/<labSid>/out/graded/grade.json``
  (``installedSha256``), or be a unit new to the selection. Anything else aborts
  unless ``--allow-texture-change`` is given;
* replaces only the units it was given; untouched rows stay byte-identical in value.

The selection is written with indent=2 and CRLF (repo convention). If the target
does not exist yet (first rebuild of a faction) it is created from the assembled
selection header.

Usage:
  python tools/homm3_def_retarget_delivery/splice_rebuild_rows.py \
    --assembled V:/olden_port_work/<tmp>_assembled.json \
    --target tools/homm3_def_retarget_delivery/<faction>_rebuild_v1.json \
    [--retexture-dir <root>] [--rebuild-root V:/scratch_claude/unit_rebuild] \
    [--units u1,u2] [--dry-run] [--allow-texture-change]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CLIPS = ("Unit_AttackFront", "Unit_ShootFront", "Unit_AttackUp", "Unit_AttackDown")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def graded_sha(retexture_dir: Path | None, sid: str) -> str | None:
    if not retexture_dir:
        return None
    g = retexture_dir / sid / "out" / "graded" / "grade.json"
    if not g.is_file():
        return None
    return (load(g).get("installedSha256") or {}).get("basecolor_hexlit_pbr.png")


def report_timing(rebuild_root: Path, sid: str) -> dict:
    rep = rebuild_root / sid / "rebuild_report.json"
    if not rep.is_file():
        return {}
    at = load(rep).get("attackTiming") or {}
    out = {}
    for clip in CLIPS:
        hit = (at.get(clip) or {}).get("hit")
        if isinstance(hit, (int, float)) and hit > 0:
            out[clip] = {"hit": round(float(hit), 4),
                         "source": f"rebuild_report.json tPeak ({rep.parent.name} v{load(rep).get('version', '?')})"}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assembled", required=True, type=Path)
    ap.add_argument("--target", required=True, type=Path)
    ap.add_argument("--retexture-dir", type=Path)
    ap.add_argument("--rebuild-root", type=Path, default=Path("V:/scratch_claude/unit_rebuild"))
    ap.add_argument("--units", default="")
    ap.add_argument("--attack-hits", type=Path,
                    help="JSON {labSid: tPeak seconds} for Unit_AttackFront, for lanes that did not write "
                         "rebuild_report.json (overrides kept/report values)")
    ap.add_argument("--shoot-hits", type=Path,
                    help="JSON {labSid: release seconds} for Unit_ShootFront (overrides kept/report values)")
    ap.add_argument("--hits-source", default="measured tPeak of the whip-swing rebuild")
    ap.add_argument("--shoot-source", default="authored release key of the rebuild")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-texture-change", action="store_true")
    a = ap.parse_args()

    asm = load(a.assembled)
    hits = load(a.attack_hits) if a.attack_hits else {}
    shots = load(a.shoot_hits) if a.shoot_hits else {}
    want = {u for u in a.units.split(",") if u}
    rows = [r for r in asm["units"] if not want or r["labSid"] in want]
    if want - {r["labSid"] for r in rows}:
        print("missing from assembled:", sorted(want - {r["labSid"] for r in rows}))
        return 2

    if a.target.is_file():
        tgt = load(a.target)
    else:
        tgt = {k: v for k, v in asm.items() if k != "units"}
        tgt["slice"] = a.target.stem
        tgt["units"] = []
    index = {r["labSid"]: i for i, r in enumerate(tgt["units"])}

    bad = []
    for r in rows:
        sid = r["labSid"]
        old = tgt["units"][index[sid]] if sid in index else None
        new_sha = (r.get("frozen") or {}).get("basecolorSha256")
        old_sha = ((old or {}).get("frozen") or {}).get("basecolorSha256")
        gsha = graded_sha(a.retexture_dir, sid)
        tex = "new" if old is None else "same" if new_sha == old_sha else "graded" if new_sha == gsha else "CHANGED"
        if tex == "CHANGED" and not a.allow_texture_change:
            bad.append(sid)
        timing = dict((old or {}).get("attackTiming") or {})
        fresh = report_timing(a.rebuild_root, sid)
        if sid in hits:
            fresh["Unit_AttackFront"] = {"hit": round(float(hits[sid]), 4), "source": a.hits_source}
        if sid in shots:
            fresh["Unit_ShootFront"] = {"hit": round(float(shots[sid]), 4), "source": a.shoot_source}
        timing.update(fresh)
        merged = dict(r)
        merged.pop("attackTiming", None)
        if timing:
            merged["attackTiming"] = timing
        shown = ", ".join(f"{c.split('_')[1]}={v['hit']}" for c, v in timing.items()) or "-"
        print(f"{sid:28s} tex={tex:7s} timing={'report' if fresh else 'kept' if timing else 'none':6s} {shown}")
        if sid in index:
            tgt["units"][index[sid]] = merged
        else:
            index[sid] = len(tgt["units"])
            tgt["units"].append(merged)

    if bad:
        print("ABORT: unexpected basecolor change (not the recorded graded sha):", ", ".join(bad))
        return 1
    if a.dry_run:
        print("dry run: target not written")
        return 0
    with open(a.target, "w", encoding="utf-8", newline="\r\n") as fh:
        json.dump(tgt, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {a.target} ({len(rows)} row(s) spliced, {len(tgt['units'])} total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
