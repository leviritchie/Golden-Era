"""Attack contact / projectile release times of the shipped owned-skinned clips (the h3_* UnitView timing table).

    python tools/homm3_def_retarget_delivery/attack_timing.py build [--out PATH] [--only SID,..]
    python tools/homm3_def_retarget_delivery/attack_timing.py show SID

Native battle code waits ``attackTimeBefore[animationIndex]`` seconds after starting the attack state before it
applies melee damage or launches the projectile, then ``attackTimeAfter[animationIndex]`` more before the attack
ends (vanilla crossbowman shot: 0.58 + 1.353 = its clip). h3_* view rows inherited both arrays from their Olden Era
donors, whose clips are unrelated to the DEF-retargeted ones that ship: centaur captain's Unit_AttackFront is 8 DEF
frames (0.667 s) with the glaive at full reach on frame 5, while the donor row hit at 1.23 s, after the clip ended.

This tool measures every shipped unit's own clips, from the sources the clips were fitted to:

  * clip length: the frozen ``delivered_idle_retimed.glb`` of the unit's delivery slice (what the lab build imports;
    the lab refuses a clip whose length differs), keys at 1/12 s per DEF pose (docs/homm3_full_creature_animation_
    pipeline.md, delivery duration is DEF playback);
  * shot release (Unit_ShootFront, and Unit_AttackFront when a shooter has no shot clip): the creature's
    ``attackClimaxFrame``, the DEF frame on which HoMM3/VCMI emits the missile. Keyed by the shot group's DEF name
    from the VCMI mod configs (HotA, Tears of Ashan, third upgrades, ...), else by creature name from CRANIM.TXT
    (HoMM3 H3bitmap.lod, then HotA.lod);
  * melee contact (Unit_AttackFront): the first DEF frame of the attack group whose opaque silhouette reaches
    within REACH_TOL_PX of its furthest point toward the target (DEF battle sprites face right). A creature with no
    climax and a shot clip falls back to the same reach rule on the shot group.

Rebuild slices (*_rebuild_v1.json, re-authored 30 fps clips) override the slice_v1 row of the same unit. A rebuild
row may carry ``attackTiming: {clip: {"hit": seconds}}``, the impact its animator measured on the new clip; that
wins over the DEF frame rule (source ``authored_rebuild``). Without it the DEF frame is scaled onto the new length.

Contact time = frame / 12 scaled by clip length / (frames / 12), so a clip whose length is not its frame count
(none today) still lands on the same pose. ``attackTimeAfter`` = clip length - contact.

Output: custom_factions/contracts/homm3_attack_timing.json (schema homm3_attack_timing.v1), read by
tools/release_port/apply_release_core_overlay.py (assign_homm3_attack_timings) and checked by
tools/validate_homm3_attack_timing.py. Rebuild it after any delivery that changes an attack or shot clip.
Proof tier: generated artifact (measured from the shipped clip inputs); in-game sync is not proven by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "custom_factions/contracts/homm3_attack_timing.json"
# rebuild slices (re-authored 30 fps clips) redeliver units first shipped by a *_slice_v1; listed last so they win
SLICES = sorted(HERE.glob("*_slice_v1.json")) + sorted(HERE.glob("*_rebuild_v1.json"))
RETARGET = ROOT / "artifacts/homm3_def_retarget"
LAB = Path("V:/homm3_unity_work/Assets/CustomUnits/homm3_lab")
FUSION_UNITS = ROOT / "custom_factions/conflux_fusion/fusion_units.json"
VCMI_MODS = ROOT / "vcmi/Mods"
VCMI_DATA = ROOT / "vcmi/Data"
H3_HD_BITMAP = Path("V:/SteamLibrary/steamapps/common/Heroes of Might & Magic III - HD Edition/data/H3BITMAP.LOD")
FPS = 12.0
REACH_TOL_PX = 2
REACH_WINDOW = (0.3, 0.8)   # reach frame / (frames - 1) outside this window is not the blow
# shot DEFs that are neither in a VCMI mod config nor named like their CRANIM.TXT row (H3 reference names)
DEF_CRANIM_ALIASES = {
    "MATERIALIZED_H3_ARCHER": "Light Crossbowman", "MATERIALIZED_H3_MARKSMAN": "Heavy Crossbowman",
    "CCYCLLOR": "Cyclops Lord", "CGTITA": "Greater Titan", "CGREMM": "Master Gremlin",
    "CPLIZA": "Primitive Lizardman", "CALIZA": "Advanced Lizardman", "CAMAGE": "Arch Mage", "CHALF": "Halfling",
}
# shots with no climax anywhere, read off the DEF by eye: (frame, reason)
SHOT_FRAME_OVERRIDES = {
    "CLEPRCHN": (4, "leprechaun g18 gold toss: the coins leave the hand on frame 4; the in-sprite arc reaches "
                    "furthest on frame 11, which the reach rule would pick"),
}
CLIP_GROUPS = {"Unit_AttackFront": "g12_attack_front", "Unit_ShootFront": "g15_shoot_front"}
SCHEMA = "homm3_attack_timing.v1"


# ---------------------------------------------------------------- climax sources
def _lod_member(path: Path, want: str) -> bytes | None:
    if not path.exists():
        return None
    b = path.read_bytes()
    count = struct.unpack_from("<I", b, 8)[0]
    for i in range(count):
        o = 92 + i * 32
        name = b[o:o + 16].split(b"\0")[0].decode("latin1")
        off, size, _typ, csize = struct.unpack_from("<IIII", b, o + 16)
        if name.lower() == want.lower():
            raw = b[off:off + (csize or size)]
            return zlib.decompress(raw) if csize else raw
    return None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def cranim_climax() -> dict[str, tuple[int, str]]:
    """Creature name (normalised) -> (attack climax frame, source lod), HotA rows override HoMM3."""
    out: dict[str, tuple[int, str]] = {}
    for lod in (H3_HD_BITMAP, VCMI_DATA / "H3bitmap.lod", VCMI_DATA / "HotA.lod"):
        raw = _lod_member(lod, "CRANIM.TXT")
        if raw is None:
            continue
        for line in raw.decode("latin1").splitlines()[2:]:
            cells = line.split("\t")
            if len(cells) < 25 or not cells[-1].strip():
                continue
            try:
                climax = int(float(cells[-2]))
            except ValueError:
                continue
            if climax > 0:
                fixed = cells[-1].strip().replace("Crossboman", "Crossbowman")
                out[_norm(fixed)] = (climax, lod.name)
    return out


def _vcmi_json(text: str):
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


def vcmi_climax() -> dict[str, list[tuple[int, str]]]:
    """DEF basename (upper) -> [(attackClimaxFrame, config path)] from every VCMI mod config (loose and zipped)."""
    out: dict[str, list[tuple[int, str]]] = {}

    def walk(o, where):
        if isinstance(o, dict):
            g = o.get("graphics")
            if isinstance(g, dict) and isinstance(g.get("animation"), str) and isinstance(g.get("missile"), dict) \
                    and "attackClimaxFrame" in g["missile"]:
                key = Path(g["animation"]).stem.upper()
                out.setdefault(key, []).append((int(g["missile"]["attackClimaxFrame"]), where))
            for v in o.values():
                walk(v, where)
        elif isinstance(o, list):
            for v in o:
                walk(v, where)

    if not VCMI_MODS.exists():
        return out
    for dp, _dn, fn in os.walk(VCMI_MODS):
        for f in fn:
            p = Path(dp) / f
            if f.endswith(".json"):
                t = p.read_text(encoding="utf-8-sig", errors="replace")
                if "attackClimaxFrame" in t:
                    try:
                        walk(_vcmi_json(t), str(p.relative_to(ROOT)).replace("\\", "/"))
                    except json.JSONDecodeError:
                        pass
            elif f.endswith(".zip"):
                try:
                    z = zipfile.ZipFile(p)
                except zipfile.BadZipFile:
                    continue
                for m in z.namelist():
                    if m.lower().endswith(".json"):
                        t = z.read(m).decode("utf-8-sig", "replace")
                        if "attackClimaxFrame" in t:
                            try:
                                walk(_vcmi_json(t), str(p.relative_to(ROOT)).replace("\\", "/") + "!" + m)
                            except json.JSONDecodeError:
                                pass
    return out


# ---------------------------------------------------------------- shipped clips
def glb_clip_lengths(path: Path) -> dict[str, float]:
    b = path.read_bytes()
    n = struct.unpack_from("<I", b, 12)[0]
    js = json.loads(b[20:20 + n])
    return {a["name"]: max(js["accessors"][s["input"]]["max"][0] for s in a["samplers"]) for a in js.get("animations", [])}


def shipped_units() -> dict[str, dict]:
    """gameSid -> slice row facts (last slice listing the sid wins, as the last deploy does)."""
    units: dict[str, dict] = {}
    for sf in SLICES:
        d = json.loads(sf.read_text(encoding="utf-8"))
        for r in d.get("units", []):
            glb = ROOT / d["out"] / r["labSid"] / "delivered_idle_retimed.glb"
            if not glb.exists():
                continue
            units[r.get("gameSid") or r["labSid"]] = {"labSid": r["labSid"], "slice": sf.name, "glb": glb,
                                                       "glbSha256": r["frozen"]["idleRetimedGlbSha256"],
                                                       "authored": r.get("attackTiming") or {}}
    return units


def def_segments(lab: str) -> tuple[dict[str, tuple[str, list[str]]], str]:
    """Clip group -> (DEF dir name, source frame PNGs) from the unit's retarget frames manifest."""
    f = RETARGET / lab / f"{lab}_def_retarget.blend.frames.json"
    if not f.exists():
        # no retarget frames manifest (toa_boar_rider): the lab's extracted DEF, when it is one sprite
        dirs = sorted((LAB / lab / "extracted_battle").glob("*.dir"))
        if len(dirs) != 1:
            return {}, ""
        out = {}
        for clip, group in CLIP_GROUPS.items():
            srcs = sorted(str(p).replace("\\", "/") for p in dirs[0].glob(group[1:3] + "_*.png"))
            if srcs:
                out[group] = (dirs[0].name.removesuffix(".dir"), srcs)
        return out, str(dirs[0]).replace("\\", "/")
    d = json.loads(f.read_text(encoding="utf-8"))
    out = {}
    for name, a, b in d["segments"]:
        if name.startswith("g02_idle") or name in out:
            continue
        srcs = d["sources"][a:b]
        out[name] = (Path(srcs[0]).parent.name.removesuffix(".dir"), srcs)
    return out, str(f.relative_to(ROOT)).replace("\\", "/")


def reach_frame(frames: list[str]) -> tuple[int, list[int]] | None:
    """First frame within REACH_TOL_PX of the furthest opaque column toward the target (DEF sprites face right)."""
    rights = []
    for p in frames:
        if not Path(p).exists():
            return None
        a = np.asarray(Image.open(p).convert("RGBA"))[..., 3] == 255
        cols = np.nonzero(a.any(0))[0]
        rights.append(int(cols.max()) if len(cols) else -1)
    top = max(rights)
    return next(i for i, r in enumerate(rights) if r >= top - REACH_TOL_PX), rights


def unit_display_names(sid: str, lab: str) -> list[str]:
    """Lab sid first (it names the HoMM3 creature, e.g. h3_power_lich), then the game sid."""
    return [re.sub(r"^(h3|hota_[a-z]+|toa)_", "", s).replace("_", " ") for s in (lab, sid)]


def measure(sid: str, row: dict, vc: dict, cr: dict) -> dict:
    lab = row["labSid"]
    lengths = glb_clip_lengths(row["glb"])
    segs, frames_src = def_segments(lab)
    clips = {}
    shooter = "Unit_ShootFront" in lengths
    for clip, group in CLIP_GROUPS.items():
        if clip not in lengths:
            continue
        length = float(lengths[clip])
        entry: dict = {"length": round(length, 4)}
        seg = segs.get(group)
        if seg is None and clip == "Unit_ShootFront":
            # a shot taken from a non-standard DEF group (leprechaun: g18): the one other segment whose pose
            # count is the clip's length
            cands = [v for k, v in segs.items() if k not in CLIP_GROUPS.values()
                     and abs(len(v[1]) / FPS - length) < 1e-3]
            if len(cands) == 1:
                seg = cands[0]
                group = "other"
        if seg is None:
            raise SystemExit(f"{sid}: no {group} segment in {frames_src or lab + ' frames manifest'}")
        def_name, frames = seg
        n = len(frames)
        entry.update({"def": def_name, "group": group, "frames": n})
        wants_climax = clip == "Unit_ShootFront"
        frame, source = None, None
        if wants_climax:
            hits = vc.get(def_name.upper())
            if hits:
                vals = sorted({h[0] for h in hits})
                if len(vals) == 1:
                    frame, source = vals[0], "vcmi_climax:" + hits[0][1]
                else:
                    # same DEF basename in several mods: take the one whose path names the unit's faction folder
                    fac = re.sub(r"_(slice|rebuild)_v1\.json$", "", row["slice"]).split("_")[0]
                    pick = [h for h in hits if f"/{fac}/" in h[1].replace("\\", "/")]
                    if len({h[0] for h in pick}) == 1:
                        frame, source = pick[0][0], "vcmi_climax:" + pick[0][1]
            if frame is None and def_name.upper() in SHOT_FRAME_OVERRIDES:
                frame, why = SHOT_FRAME_OVERRIDES[def_name.upper()]
                source = "override:" + why
            if frame is None:
                alias = DEF_CRANIM_ALIASES.get(def_name.upper())
                for nm in ([alias] if alias else []) + unit_display_names(sid, lab):
                    if _norm(nm) in cr:
                        frame, source = cr[_norm(nm)][0], f"cranim:{cr[_norm(nm)][1]}:{nm}"
                        break
        if frame is None:
            r = reach_frame(frames)
            if r is None:
                raise SystemExit(f"{sid}: {clip} source frames missing ({frames[0]})")
            frame, rights = r
            entry["reachPx"] = rights
            share = frame / max(n - 1, 1)
            if REACH_WINDOW[0] <= share <= REACH_WINDOW[1] and max(rights) > min(rights) + REACH_TOL_PX:
                source = "sprite_reach"
            else:
                # wings, auras or a static body set the silhouette's reach, not the blow: VCMI's melee rule
                # (MeleeAttackAnimation: the hit stage fires once currentFrame * 2 >= framesInGroup)
                frame, source = (n + 1) // 2, "vcmi_melee_half"
        if frame >= n:
            entry["climaxClamped"] = frame
            frame = n - 1
        hit = round(frame / FPS * (length / (n / FPS)), 4)
        authored = (row.get("authored") or {}).get(clip)
        if authored is not None:
            # a re-authored clip (rebuild slice) strikes where its animator measured the impact, not on a DEF frame
            hit = round(float(authored["hit"]), 4)
            if not 0 < hit < length:
                raise SystemExit(f"{sid}: authored {clip} hit {hit} outside the clip (0, {length})")
            source = "authored_rebuild:" + row["slice"]
        entry.update({"hitFrame": int(frame), "hit": hit, "after": round(max(0.0, length - hit), 4), "source": source})
        clips[clip] = entry
    return {"labSid": lab, "slice": row["slice"], "glbSha256": row["glbSha256"], "framesManifest": frames_src,
            "shooterClip": shooter, "clips": clips}


def fusion_hosts() -> dict[str, str]:
    if not FUSION_UNITS.exists():
        return {}
    d = json.loads(FUSION_UNITS.read_text(encoding="utf-8"))
    out = {}
    for bucket in ("units", "stage2"):
        b = d.get(bucket) or {}
        items = b.items() if isinstance(b, dict) else ((x.get("sid") or x.get("id"), x) for x in b if isinstance(x, dict))
        for sid, v in items:
            if sid and isinstance(v, dict) and isinstance(v.get("host"), str):
                out[sid] = v["host"]
    return out


def build(out: Path, only: set[str] | None) -> int:
    vc, cr = vcmi_climax(), cranim_climax()
    units = shipped_units()
    table = {}
    if only and out.exists():
        table = json.loads(out.read_text(encoding="utf-8")).get("units", {})
    for sid in sorted(units):
        if only and sid not in only:
            continue
        table[sid] = measure(sid, units[sid], vc, cr)
    raw_hosts = fusion_hosts()
    hosts = {}
    for k in sorted(raw_hosts):
        v, seen = raw_hosts[k], {k}
        while v not in table and v in raw_hosts and v not in seen:   # stage 2 fuses a stage-1 fused host
            seen.add(v)
            v = raw_hosts[v]
        if v in table:
            hosts[k] = v
    doc = {"schema": SCHEMA, "generator": "tools/homm3_def_retarget_delivery/attack_timing.py",
           "fps": FPS, "reachTolerancePx": REACH_TOL_PX, "units": table, "fusionHosts": hosts}
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    out.write_text(text, encoding="utf-8", newline="\n")
    srcs: dict[str, int] = {}
    for u in table.values():
        for c in u["clips"].values():
            k = c["source"].split(":")[0]
            srcs[k] = srcs.get(k, 0) + 1
    print(f"wrote {out} ({len(table)} units, {len(hosts)} fusion hosts, sources {srcs}, "
          f"sha256 {hashlib.sha256(text.encode()).hexdigest()[:12]})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, default=OUT)
    b.add_argument("--only", default="")
    s = sub.add_parser("show")
    s.add_argument("sid")
    a = ap.parse_args()
    if a.cmd == "build":
        return build(a.out, {x for x in a.only.split(",") if x} or None)
    doc = json.loads(OUT.read_text(encoding="utf-8"))
    print(json.dumps(doc["units"].get(a.sid) or {"fusionHost": doc["fusionHosts"].get(a.sid)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
