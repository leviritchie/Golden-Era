#!/usr/bin/env python3
"""Texture-only delivery slice: copy frozen unit inputs from base selections and swap the body basecolor.

  python tools/homm3_def_retarget_delivery/retex_slice.py --base A.json B.json --slice conflux_tex_v1 --retexture-dir <root> [--exclude u1,u2]

Later bases override earlier ones per labSid. Geometry, clips, VFX and idle timing stay byte-identical;
only the embedded body image (both GLBs), inputs/basecolor.png and the hash chain change. A unit with no
painted texture is copied unchanged so the new slice still covers it. Writes
tools/homm3_def_retarget_delivery/<slice>.json (CRLF).
"""
import argparse, hashlib, json, shutil, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools/homm3_unit_look"))
import glbpatch  # noqa: E402

sha = lambda b: hashlib.sha256(b).hexdigest()
load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))


def dump(p, o, indent):
    Path(p).write_bytes((json.dumps(o, indent=indent, ensure_ascii=False) + "\n").replace("\n", "\r\n").encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", nargs="+", required=True)
    ap.add_argument("--slice", required=True)
    ap.add_argument("--retexture-dir", required=True)
    ap.add_argument("--exclude", default="")
    ap.add_argument("--supersede-raw", default="", help="labSids whose rawAccepted raw texture the repaint replaces")
    a = ap.parse_args()
    exclude = set(filter(None, a.exclude.split(",")))
    supersede = set(filter(None, a.supersede_raw.split(",")))
    rows = {}
    for b in a.base:
        sel = load(REPO / b)
        for r in sel["units"]:
            rows[r["labSid"]] = (r, REPO / sel["out"])
    out_rel = f"artifacts/homm3_def_retarget_delivery/{a.slice}"
    out = REPO / out_rel
    new_rows, swapped, kept = [], [], []
    for sid, (row, base_out) in rows.items():
        if sid in exclude:
            continue
        src, dst = base_out / sid, out / sid
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src / "inputs", dst / "inputs")
        shutil.copy2(src / "delivered_idle_retimed.glb", dst / "delivered_idle_retimed.glb")
        shutil.copy2(src / "idle_retime_report.json", dst / "idle_retime_report.json")
        fz = dict(row["frozen"])
        stamp = load(dst / "inputs/stamp.json")
        look_p, ret_p = dst / "inputs/look_delivered.glb", dst / "delivered_idle_retimed.glb"
        for p, k in ((look_p, "lookDeliveredGlbSha256"), (ret_p, "idleRetimedGlbSha256")):
            if sha(p.read_bytes()) != fz[k]:
                raise SystemExit(f"{sid}: base input {p.name} no longer matches the base selection")
        new_row = {k: v for k, v in row.items() if k != "recolor"}
        tex = Path(a.retexture_dir) / sid / "out/basecolor_hexlit_pbr.png"
        grade = tex.parent / "graded/grade.json"
        why = None
        if not tex.is_file() or not grade.is_file():
            why = "no graded texture"
        elif load(grade)["installedSha256"]["basecolor_hexlit_pbr.png"].lower() != sha(tex.read_bytes()):
            why = "texture differs from graded record"
        elif stamp.get("kind") is not None and not (sid in supersede and stamp["kind"] == "rawAccepted"):
            why = f"stamp kind {stamp['kind']}"
        if why:
            if "recolor" in row:
                new_row["recolor"] = row["recolor"]
            kept.append(f"{sid} ({why})")
        else:
            png = tex.read_bytes()
            for p in (look_p, ret_p):
                g = glbpatch.Glb.load(p)
                g.replace_image(g.body_base_color_image(), png)
                p.write_bytes(g.to_bytes())
            (dst / "inputs/basecolor.png").write_bytes(png)
            fz["lookDeliveredGlbSha256"] = sha(look_p.read_bytes())
            fz["idleRetimedGlbSha256"] = sha(ret_p.read_bytes())
            fz["basecolorSha256"] = sha(png)
            stamp["deliveredGlbSha256"] = fz["lookDeliveredGlbSha256"]
            stamp["basecolorSha256"] = fz["basecolorSha256"]
            superseded_raw = stamp.get("kind") == "rawAccepted"
            if superseded_raw:  # the raw-texture evidence no longer describes what ships
                stamp.pop("kind")
                stamp["supersededRawAccepted"] = stamp.pop("rawAccepted")
                stamp["basecolorFile"] = "basecolor.png"
            dump(dst / "inputs/stamp.json", stamp, 1)
            if superseded_raw:  # the ship tool allows the whole-stamp pin only on rawAccepted rows
                fz.pop("lookStampSha256", None)
            rep = load(dst / "idle_retime_report.json")
            rep.update(src=str(look_p), dst=str(ret_p), srcSha256=fz["lookDeliveredGlbSha256"],
                       dstSha256=fz["idleRetimedGlbSha256"])
            dump(dst / "idle_retime_report.json", rep, 1)
            swapped.append(sid)
        new_row["frozen"] = fz
        new_rows.append(new_row)
    doc = {"schema": "homm3_def_retarget_delivery_selection.v1", "slice": a.slice,
           "disposition": "user_requested_ingame_test", "accepted": False, "out": out_rel,
           "note": "Texture-only re-ship: " + " + ".join(Path(b).stem for b in a.base)
                   + " with HoMM3-graded 2K repaint basecolor; geometry, clips and VFX unchanged.",
           "units": new_rows}
    dump(REPO / f"tools/homm3_def_retarget_delivery/{a.slice}.json", doc, 2)
    print(f"{a.slice}: {len(swapped)} retextured, {len(kept)} unchanged: {kept}")


if __name__ == "__main__":
    main()
