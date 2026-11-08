#!/usr/bin/env python3
"""Adventure-map object animation audit: DEF contact sheets and motion-part measurements.

The hand-labelled motion table in ``map_building_anim.py`` (now ``MOTION_PARTS``) was first assigned
from one motion sheet per DEF and missed or misread independent moving parts (avggolm0's flywheels;
avggrem0 was relabelled "wheel + pendulum" although only the pendulum moves). This tool
renders, for any HoMM3 adventure-map DEF, a sheet a person can check:

  * every frame of group 0 (nearest x3, on a neutral grey);
  * the motion heat mask (how many distinct palette values each pixel takes over the cycle);
  * the moving region cropped and enlarged per frame, so small parts (a pendulum bob, a crane
    hook, a turning wheel) are visible;
  * per motion component: bbox, pixel count, hue mix, loop period and the centroid trajectory of
    the changed pixels (a swing shows as an arc, a spin as a fixed centroid, a rising plume as a
    vertical drift).

It reuses the DEF reader in ``map_building_anim.py`` (LOD index + DEF decode); it does not add a
new DEF parser.

Subcommands
-----------
``sheets [--def NAME ...] [--rows animated|all]``
    Render ``artifacts/map_building_anim/audit/<stem>_audit.png`` and write
    ``artifacts/map_building_anim/audit/measurements.json`` (per-DEF component measurements).
    Without ``--def`` it renders every animated row of ``map_building_anim_inventory.json`` plus
    every DEF of every non-inventory row in ``map_object_anim_coverage.json``.

``census``
    Aggregate every placement in the raw_translation ``*placement_ground_truth.json`` files (not
    creatures/heroes/resources/artifacts), decode each placed DEF and write the animated ones with
    their Olden Era SIDs and emit status to ``map_object_anim_census.json``.
``probe-native [--path ...]``
    UnityPy read of the installed Golden Era ``resources.assets``: Animator controllers and
    ParticleSystem counts under each native prefab named by ``map_object_anim_coverage.json``;
    writes ``oe_native_prefab_anim.json``. Read-only; does not touch the game process.

Proof tier of the outputs: generated artifact (DEF decode). Motion *types* in the audit doc are an
inspected classification of these sheets, not something the numbers alone prove.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))
import map_building_anim as mba  # noqa: E402

ROOT = mba.ROOT
AUDIT_DIR = ROOT / "artifacts" / "map_building_anim" / "audit"
COVERAGE = TOOL_DIR / "map_object_anim_coverage.json"
BG = (96, 104, 96)


def _font(size: int):
    for name in ("consola.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def read_def_by_name(def_name: str) -> tuple[str | None, bytes | None]:
    """Find a DEF by file name in the LODs the map-building tooling already uses (HotA first)."""
    want = def_name.lower()
    if not want.endswith(".def"):
        want += ".def"
    for name, data, idx in mba._lods():
        if want in idx:
            o, size, csize = idx[want]
            blob = data[o:o + csize] if csize else data[o:o + size]
            return name, (zlib.decompress(blob) if csize else blob)
    if mba.BULWARK_ZIP.is_file():
        with zipfile.ZipFile(mba.BULWARK_ZIP) as z:
            for m in z.namelist():
                if m.lower().endswith("/" + want):
                    return "bulwark.zip", z.read(m)
    return None, None


def all_def_versions(def_name: str) -> list[tuple[str, int]]:
    """(source, total frame count) for every LOD that carries this DEF (SoD vs HotA overrides)."""
    want = def_name.lower()
    if not want.endswith(".def"):
        want += ".def"
    out = []
    for name, data, idx in mba._lods():
        if want in idx:
            o, size, csize = idx[want]
            blob = data[o:o + csize] if csize else data[o:o + size]
            blob = zlib.decompress(blob) if csize else blob
            try:
                _pal, groups = mba.decode_def(blob)
                out.append((name, sum(len(v) for v in groups.values())))
            except Exception:  # noqa: BLE001 - report, do not hide
                out.append((name, -1))
    return out


def loop_period(frames: list[np.ndarray], body: np.ndarray) -> int:
    """Smallest p with frame[i] == frame[i+p] (on the body) for all i; len(frames) if none."""
    n = len(frames)
    for p in range(1, n):
        if n % p:
            continue
        if all((frames[i][body] == frames[(i + p) % n][body]).all() for i in range(n)):
            return p
    return n


def component_measure(frames: list[np.ndarray], pal: np.ndarray, comp: np.ndarray) -> dict:
    st = np.stack(frames)
    n = len(frames)
    x0, y0, x1, y1 = mba.bbox(comp)
    # Per-frame opaque pixels inside the component: centroid + count.
    cents = []
    areas = []
    for i in range(n):
        m = comp & (st[i] > 7)
        areas.append(int(m.sum()))
        if m.any():
            ys, xs = np.nonzero(m)
            cents.append([round(float(xs.mean()), 1), round(float(ys.mean()), 1)])
        else:
            cents.append(None)
    valid = [c for c in cents if c]
    spread = None
    if valid:
        a = np.array(valid)
        spread = [round(float(a[:, 0].max() - a[:, 0].min()), 1), round(float(a[:, 1].max() - a[:, 1].min()), 1)]
    return {
        "bbox": [int(x0), int(y0), int(x1), int(y1)],
        "px": int(comp.sum()),
        "hue": mba.classify_hue(frames, pal, comp),
        "areaMinMax": [min(areas), max(areas)],
        "centroidSpreadPx": spread,
        "centroids": cents,
        "period": loop_period(frames, comp),
    }


def render_sheet(stem: str, source: str, pal: np.ndarray, frames: list[np.ndarray], title_extra: str = "") -> dict:
    n = len(frames)
    h, w = frames[0].shape
    st = np.stack(frames)
    body = (st > 7).any(0)
    mv = mba.motion_mask(frames)
    distinct = np.zeros((h, w), np.int32)
    if n > 1:
        srt = np.sort(st, axis=0)
        distinct = 1 + (np.diff(srt, axis=0) != 0).sum(0)
        distinct[~mv] = 0
    comps = mba.components(mv, link=2) if mv.any() else []
    comps = sorted(comps, key=lambda c: -int(c.sum()))
    meas = [component_measure(frames, pal, c) for c in comps[:12]]

    s = 3
    font = _font(12)
    font_b = _font(14)
    cols = min(n, 8)
    rows = (n + cols - 1) // cols
    tile_w, tile_h = w * s, h * s
    # crop of the moving region
    if mv.any():
        cx0, cy0, cx1, cy1 = mba.bbox(mba.dilate(mv, 3) & np.ones_like(mv))
        cx0, cy0 = max(0, cx0), max(0, cy0)
        cx1, cy1 = min(w - 1, cx1), min(h - 1, cy1)
    else:
        cx0, cy0, cx1, cy1 = 0, 0, w - 1, h - 1
    cw, ch = cx1 - cx0 + 1, cy1 - cy0 + 1
    zs = max(2, min(8, int(160 / max(cw, ch))))
    ccols = min(n, max(1, 1100 // (cw * zs + 6)))
    crows = (n + ccols - 1) // ccols

    W = max(cols * (tile_w + 6) + 6, 2 * (tile_w + 6) + 360, ccols * (cw * zs + 6) + 6)
    H = 30 + rows * (tile_h + 20) + 20 + tile_h + 30 + crows * (ch * zs + 18) + 20 + 16 * (len(meas) + 2)
    img = Image.new("RGB", (W, H), (40, 40, 44))
    d = ImageDraw.Draw(img)
    d.text((6, 6), f"{stem}  ({source})  frames={n}  moving px={int(mv.sum())}  components={len(comps)}  {title_extra}",
           fill=(240, 240, 240), font=font_b)

    def frame_rgb(fr):
        rgba = mba.index_to_rgba(fr, pal)
        base = Image.new("RGBA", (w, h), BG + (255,))
        base.alpha_composite(Image.fromarray(rgba, "RGBA"))
        return base.convert("RGB")

    y = 30
    for i, fr in enumerate(frames):
        cx = 6 + (i % cols) * (tile_w + 6)
        cy = y + (i // cols) * (tile_h + 20)
        img.paste(frame_rgb(fr).resize((tile_w, tile_h), Image.NEAREST), (cx, cy))
        d.text((cx + 2, cy + tile_h + 2), f"f{i}", fill=(220, 220, 220), font=font)
    y += rows * (tile_h + 20) + 10

    # heat mask + components
    heat = np.zeros((h, w, 3), np.uint8)
    heat[body] = (70, 70, 70)
    if mv.any():
        mx = max(1, int(distinct.max()))
        t = distinct.astype(float) / mx
        heat[mv] = np.stack([255 * t[mv], 180 * (1 - t[mv]) + 60, 40 + 0 * t[mv]], -1).astype(np.uint8)
    himg = Image.fromarray(heat).resize((tile_w, tile_h), Image.NEAREST)
    img.paste(himg, (6, y))
    dh = ImageDraw.Draw(img)
    palette = [(255, 255, 0), (0, 255, 255), (255, 0, 255), (0, 255, 0), (255, 128, 0), (128, 128, 255),
               (255, 255, 255), (255, 80, 80), (80, 255, 160), (200, 160, 255), (160, 255, 80), (255, 200, 120)]
    for k, m in enumerate(meas):
        bx0, by0, bx1, by1 = m["bbox"]
        col = palette[k % len(palette)]
        dh.rectangle([6 + bx0 * s, y + by0 * s, 6 + (bx1 + 1) * s, y + (by1 + 1) * s], outline=col)
        dh.text((6 + bx0 * s + 1, y + by0 * s + 1), f"c{k}", fill=col, font=font)
        pts = [(6 + c[0] * s + 1, y + c[1] * s + 1) for c in m["centroids"] if c]
        if len(pts) > 1:
            dh.line(pts + [pts[0]], fill=col, width=1)
    # static first frame beside
    img.paste(frame_rgb(frames[0]).resize((tile_w, tile_h), Image.NEAREST), (12 + tile_w, y))
    d.text((6, y + tile_h + 2), "motion heat (distinct values) + components + centroid paths", fill=(220, 220, 220), font=font)
    y += tile_h + 24

    # zoomed crop strip
    d.text((6, y), f"moving region x{zs}: x{cx0}-{cx1} y{cy0}-{cy1}", fill=(220, 220, 220), font=font)
    y += 14
    for i, fr in enumerate(frames):
        crop = frame_rgb(fr).crop((cx0, cy0, cx1 + 1, cy1 + 1)).resize((cw * zs, ch * zs), Image.NEAREST)
        px = 6 + (i % ccols) * (cw * zs + 6)
        py = y + (i // ccols) * (ch * zs + 18)
        img.paste(crop, (px, py))
        d.text((px + 2, py + ch * zs + 1), f"f{i}", fill=(220, 220, 220), font=font)
    y += crows * (ch * zs + 18) + 6

    for k, m in enumerate(meas):
        d.text((6, y), f"c{k}: bbox={m['bbox']} px={m['px']} period={m['period']} area={m['areaMinMax']} "
                       f"centroidSpread={m['centroidSpreadPx']} hue={m['hue']}",
               fill=palette[k % len(palette)], font=font)
        y += 16
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDIT_DIR / f"{stem.lower()}_audit.png"
    img.save(out)
    return {
        "def": stem, "source": source, "frames": n, "movingPx": int(mv.sum()),
        "movingFracOfOpaque": round(float(mv.sum() / max(1, body.sum())), 4),
        "period": loop_period(frames, body) if n > 1 else 1,
        "components": [{k: v for k, v in m.items() if k != "centroids"} for m in meas],
        "sheet": str(out.relative_to(ROOT)).replace("\\", "/"),
    }


def sheet_for_inventory_row(dir_rel: str) -> dict:
    label, pal, g0 = mba.def_frames(dir_rel)
    stem = Path(dir_rel).name[:-4]
    if stem.lower() == "capitol":
        stem = dir_rel.split("/")[0].replace("homm3_", "") + "_capitol"
    return render_sheet(stem, label or "?", pal, g0)


def sheet_for_def(def_name: str) -> dict | None:
    label, blob = read_def_by_name(def_name)
    if blob is None:
        return None
    pal, groups = mba.decode_def(blob)
    g0 = groups.get(0) or next(iter(groups.values()))
    stem = def_name[:-4] if def_name.lower().endswith(".def") else def_name
    return render_sheet(stem, label or "?", pal, g0)


def cmd_sheets(args) -> int:
    results = {}
    if args.defs:
        for name in args.defs:
            r = sheet_for_def(name)
            print(name, "missing" if r is None else f"{r['frames']} frames -> {r['sheet']}")
            if r:
                results[r["def"].lower()] = r
    else:
        inv = json.loads(mba.INVENTORY_OUT.read_text(encoding="utf-8"))
        for row in inv["rows"]:
            if args.rows == "animated" and not row.get("animated"):
                continue
            r = sheet_for_inventory_row(row["dir"])
            results[r["def"].lower()] = r
            print(row["dir"], r["frames"], r["sheet"])
        if COVERAGE.is_file():
            cov = json.loads(COVERAGE.read_text(encoding="utf-8"))
            for row in cov.get("rows", []):
                if not row.get("homm3Animates") or row.get("lane") == "inventory_row":
                    continue
                for d in row.get("defs", []):
                    r = sheet_for_def(d)
                    if r:
                        results[r["def"].lower()] = r
                        print(d, r["frames"], r["sheet"])
    mpath = AUDIT_DIR / "measurements.json"
    prev = json.loads(mpath.read_text(encoding="utf-8")) if mpath.is_file() else {}
    prev.update(results)
    mpath.write_text(json.dumps(dict(sorted(prev.items())), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(results)} sheet(s); measurements -> {mpath}")
    return 0


# ----------------------------------------------------------------------------------------------
# census: which placed HoMM3 map objects animate, and what the translated maps show for them
# ----------------------------------------------------------------------------------------------

CENSUS = TOOL_DIR / "map_object_anim_census.json"
NATIVE_PROBE = TOOL_DIR / "oe_native_prefab_anim.json"
GROUND_TRUTH_GLOBS = [
    "artifacts/campaign_port_poc/*/*/raw_translation_map/*placement_ground_truth.json",
    "artifacts/campaign_port_poc/*/raw_translation_map/*placement_ground_truth.json",
]
# Not adventure-map buildings: creatures, heroes, artifacts, resources, scrolls, events, random
# placeholders, boats. Everything else placed on a translated map is in scope.
NON_BUILDING_OBJECT_IDS = {5, 8, 26, 34, 54, 62, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 79, 93,
                           162, 163, 164}


def cmd_census(_args) -> int:
    import collections
    import glob
    files = sorted({f for g in GROUND_TRUTH_GLOBS for f in glob.glob(str(ROOT / g))})
    if not files:
        raise SystemExit("no placement ground-truth files found; run the raw_translation map pipeline first")
    agg: dict[str, dict] = {}
    for f in files:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for p in d["placements"]:
            h = p["h3"]
            if h["templateObjectId"] in NON_BUILDING_OBJECT_IDS:
                continue
            o = p.get("olden") or {}
            key = h["templateAnimation"].lower()
            a = agg.setdefault(key, {"objects": collections.Counter(), "placements": 0,
                                     "sids": collections.Counter(), "emitStatus": collections.Counter()})
            a["objects"][f"{h['templateObjectId']}/{h.get('templateSubtype')}"] += 1
            a["placements"] += 1
            a["sids"][str(o.get("sid"))] += 1
            a["emitStatus"][str(p.get("emitStatus"))] += 1
    rows = []
    static = 0
    for d, a in sorted(agg.items()):
        src, blob = read_def_by_name(d)
        if blob is None:
            raise SystemExit(f"placed DEF {d} not found in any LOD")
        _pal, groups = mba.decode_def(blob)
        g0 = groups.get(0) or next(iter(groups.values()))
        if len(g0) <= 1:
            static += 1
            continue
        mv = mba.motion_mask(g0)
        if not mv.any():
            static += 1
            continue
        rows.append({"def": d, "defSource": src, "frames": len(g0), "movingPx": int(mv.sum()),
                     "objects": dict(a["objects"]), "placements": a["placements"],
                     "sids": dict(a["sids"].most_common()), "emitStatus": dict(a["emitStatus"].most_common())})
    doc = {"schema": "homm3_map_object_anim_census.v1",
           "generator": "tools/homm3_map_building_meshes/audit_map_object_animation.py census",
           "source": f"{len(files)} raw_translation placement_ground_truth files",
           "counts": {"placedDefs": len(agg), "animatedDefs": len(rows), "staticDefs": static},
           "excludedObjectIds": sorted(NON_BUILDING_OBJECT_IDS),
           "rows": rows}
    CENSUS.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {CENSUS} {doc['counts']}")
    return 0


GOLDEN_ERA_DATA = Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
                       r"\HeroesOldenEra_Data")


def cmd_probe_native(args) -> int:
    """Read the installed game's native map-object prefabs (UnityPy) and record, per Resources
    path, the Animator controllers and ParticleSystem count under the prefab root. Read-only."""
    import UnityPy
    env = UnityPy.load(str(GOLDEN_ERA_DATA / "globalgamemanagers"), str(GOLDEN_ERA_DATA / "resources.assets"))
    rm = rmfile = None
    for o in env.objects:
        if o.type.name == "ResourceManager":
            rm, rmfile = o.read_typetree(), o.assets_file
            break
    if rm is None:
        raise SystemExit("ResourceManager not found in globalgamemanagers")
    cont: dict[str, list] = {}
    for k, v in rm["m_Container"]:
        cont.setdefault(k.lower(), []).append(v)

    def resolve(pp, sf):
        fid, pid = pp["m_FileID"], pp["m_PathID"]
        if pid == 0:
            return None
        f = sf
        if fid:
            ext = sf.externals[fid - 1].path.lower().split("/")[-1]
            f = next((ff for kk, ff in env.files.items() if kk.lower().endswith(ext)), None)
        return None if f is None else f.objects.get(pid)

    cov = json.loads(COVERAGE.read_text(encoding="utf-8"))
    paths = sorted({p for r in cov["rows"] for p in r.get("nativePrefabPaths", [])} | set(args.path or []))
    out = {}
    for tp in paths:
        ents = cont.get(tp.lower())
        if not ents:
            out[tp] = {"missing": True}
            continue
        rec = {"nodes": 0, "animators": [], "particleSystems": 0}
        for e in ents:
            root = resolve(e, rmfile)
            if root is None or root.type.name != "GameObject":
                continue
            stack, seen = [root], set()
            while stack:
                go = stack.pop()
                if go.path_id in seen:
                    continue
                seen.add(go.path_id)
                rec["nodes"] += 1
                tt = go.read_typetree()
                for c in tt["m_Component"]:
                    co = resolve(c["component"], go.assets_file)
                    if co is None:
                        continue
                    tn = co.type.name
                    if tn in ("Transform", "RectTransform"):
                        for ch in co.read_typetree()["m_Children"]:
                            tro = resolve(ch, co.assets_file)
                            if tro is not None:
                                g = resolve(tro.read_typetree()["m_GameObject"], tro.assets_file)
                                if g is not None:
                                    stack.append(g)
                    elif tn == "Animator":
                        ac = resolve(co.read_typetree()["m_Controller"], co.assets_file)
                        rec["animators"].append({"gameObject": tt["m_Name"],
                                                 "controller": ac.read_typetree().get("m_Name") if ac else None})
                    elif tn == "ParticleSystem":
                        rec["particleSystems"] += 1
        out[tp] = rec
        print(tp, rec)
    doc = {"schema": "homm3_oe_native_prefab_anim.v1",
           "generator": "tools/homm3_map_building_meshes/audit_map_object_animation.py probe-native",
           "source": "installed Golden Era HeroesOldenEra_Data resources.assets via the Resources container",
           "prefabs": out}
    NATIVE_PROBE.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {NATIVE_PROBE} ({len(out)} prefabs)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sheets")
    p.add_argument("--def", dest="defs", nargs="*", default=None)
    p.add_argument("--rows", choices=["animated", "all"], default="animated")
    p.set_defaults(func=cmd_sheets)
    p = sub.add_parser("census", help="write map_object_anim_census.json from placement ground truth")
    p.set_defaults(func=cmd_census)
    p = sub.add_parser("probe-native", help="write oe_native_prefab_anim.json (UnityPy, read-only)")
    p.add_argument("--path", nargs="*", default=None)
    p.set_defaults(func=cmd_probe_native)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
