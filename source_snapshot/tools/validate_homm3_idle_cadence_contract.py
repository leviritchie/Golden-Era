"""Validate the HoMM3 idle-cadence delivery contract (docs/homm3_idle_cadence.md).

    python tools/validate_homm3_idle_cadence_contract.py [--repo-root R] [--unit U ...] [--require-complete]

Always (source/static):
- `tools/homm3_idle_cadence/idle_exceptions.json` parses; every entry names a unit, a known
  treatment and a non-empty reason; factors and wing cycles are in range; wing treatments name
  bones; no unknown keys.
- the rule module imports and its constants are sane.

For every rolled-out unit (a `artifacts/homm3_idle_cadence/roster/<unit>/report.json`), when both
the source def_retarget GLB and the retimed GLB exist locally (GLBs are not in git):
- the report's treatment / factor equals what the rule + exceptions table give now;
- the retimed idle lasts exactly factor x the source idle (1e-4 s);
- every idle transform channel closes its loop (|last - first| <= 1e-3, quaternion sign-aware);
- body channels hit every source key pose at its stretched time (1e-4);
- every other animation is identical: same names, channels, samplers, and the same accessor
  bytes (compared by value, so an unrelated texture swap does not matter);
- nodes, meshes and skins are identical JSON.
Reads only the JSON chunks and the animation accessors (seek), so it is fast on the whole roster.

Input and staleness: the source is re-resolved now with idle_cadence_rule.resolve_input (pipeline
order build -> emphasis -> idle retime -> look; look's superseded original when the GLB is look's
stamped delivery). If its animation hash (anim_sha256) differs from the report's, the
retimed GLB was made from other clips - e.g. before the emphasis pass rewrote them - and is an ERROR
(never usable) until rollout_idle.py regenerates it. A look texture bake changes no animation and
does not stale an output. When the emphasis lane's stamp
(artifacts/homm3_def_retarget_emphasis/<unit>/stamp.json) says the unit is emphasised, the input must
carry its asset.extras.homm3DefRetargetEmphasis (ERROR otherwise: the input predates emphasis).
Fast path: when the on-disk GLB and the recorded input keep the size/mtime
the report recorded, the recorded resolution is reused (resolving hashes whole GLBs); the animation
hash is always recomputed.
Texture/VFX layers keep time with the retimed idle (texture_idle_errors): the unit-look VFX manifest
(artifacts/homm3_unit_look/<unit>/vfx/vfx_manifest.json) keys every Unit_Idle layer - uvAtlas cell
lists such as the conflux elementals' / nymph's element_flow, defFlipbook sheets, effectLight curves,
volumetricFire intensities - per DEF idle frame at 12 fps in the *un-retimed* time base. Neither
rollout_idle.py nor look.py rewrites those lists, and they must not: the one consumer that pairs them
with the retimed GLB, tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py, maps every idle
window through make_time_map (the retime's own t0 + (t - t0) x factor) before the lab bakes them into
the clip. Checked per unit: manifest fps 12; each key sits on its DEF frame's window; per-frame layers
(uvAtlas, effectLight, volumetricFire) list exactly the DEF idle's frames (frames.json loops); the source
idle spans those frames plus the loop's transitionKeys; and the delivery's make_time_map, applied to the
source idle and to every key, lands on the retimed GLB's own idle end and on a retimed key (1e-4 s). A
cell list left at source tempo against a stretched idle (texture 3.2x faster than the bones) fails here.
--require-complete: every def_retarget GLB must have a retimed output or an `exclude` entry.
A unit with a report but no GLBs locally is a note (fresh clone), never silently skipped.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "homm3_idle_cadence"))

COMP = {5126: "<f4", 5123: "<u2", 5125: "<u4", 5121: "u1", 5122: "<i2", 5120: "i1"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class LazyGlb:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            head = f.read(20)
            magic, ver, total = struct.unpack_from("<4sII", head, 0)
            if magic != b"glTF":
                raise ValueError(f"{path}: not a GLB")
            ln, typ = struct.unpack_from("<I4s", head, 12)
            self.js = json.loads(f.read(ln).decode("utf-8"))
            f.seek(20 + ln)
            bl, _ = struct.unpack("<I4s", f.read(8))
            self.bin_off = 20 + ln + 8
        self._f = open(path, "rb")          # one handle per GLB: thousands of opens dominate otherwise
        self._cache = {}

    def close(self):
        self._f.close()

    def raw(self, i) -> bytes:
        a = self.js["accessors"][i]
        bv = self.js["bufferViews"][a["bufferView"]]
        n = NCOMP[a["type"]]; dt = np.dtype(COMP[a["componentType"]])
        stride = bv.get("byteStride", 0) or dt.itemsize * n
        if stride != dt.itemsize * n or "sparse" in a:
            raise ValueError(f"{self.path}: accessor {i} is interleaved or sparse")
        if i not in self._cache:
            self._f.seek(self.bin_off + bv.get("byteOffset", 0) + a.get("byteOffset", 0))
            self._cache[i] = self._f.read(a["count"] * n * dt.itemsize)
        return self._cache[i]

    def arr(self, i) -> np.ndarray:
        a = self.js["accessors"][i]
        return np.frombuffer(self.raw(i), dtype=COMP[a["componentType"]]).reshape(a["count"], -1).astype(np.float64)

    def anim(self, name):
        hits = [a for a in self.js.get("animations", []) if a.get("name") == name]
        if len(hits) != 1:
            raise KeyError(f"{self.path}: animation {name!r} found {len(hits)} times")
        return hits[0]


def _quat_close(a, b):
    return min(np.max(np.abs(a - b)), np.max(np.abs(a + b)))


def check_unit(unit, S, dst, rep, expected, errors, idle_clip):
    e0 = len(errors)
    D = LazyGlb(dst)
    try:
        return _check(unit, S, D, rep, expected, errors, idle_clip, e0)
    finally:
        D.close()


def _check(unit, S, D, rep, expected, errors, idle_clip, e0):
    for key in ("nodes", "meshes", "skins"):
        if S.js.get(key) != D.js.get(key):
            errors.append(f"{unit}: {key} differ between source and retimed GLB")
    if rep.get("treatment") != expected["treatment"] or abs(rep.get("factor", -1) - expected["factor"]) > 1e-9 \
            or rep.get("wingCycles") != expected.get("wingCycles"):
        errors.append(f"{unit}: retimed with {rep.get('treatment')}/{rep.get('factor')}/{rep.get('wingCycles')} but the "
                      f"rule now gives {expected['treatment']}/{expected['factor']}/{expected.get('wingCycles')}; rerun rollout")
    sn = [a["name"] for a in S.js["animations"]]; dn = [a["name"] for a in D.js["animations"]]
    if sn != dn:
        errors.append(f"{unit}: animation list differs {sn} vs {dn}")
        return
    for sa, da in zip(S.js["animations"], D.js["animations"]):
        if sa["name"] == idle_clip:
            continue
        if sa["channels"] != da["channels"] or len(sa["samplers"]) != len(da["samplers"]):
            errors.append(f"{unit}: {sa['name']} channels differ"); continue
        for ss, ds in zip(sa["samplers"], da["samplers"]):
            if ss.get("interpolation") != ds.get("interpolation") or S.raw(ss["input"]) != D.raw(ds["input"]) \
                    or S.raw(ss["output"]) != D.raw(ds["output"]):
                errors.append(f"{unit}: {sa['name']} sampler data differs from the source"); break
    si, di = S.anim(idle_clip), D.anim(idle_clip)
    if si["channels"] != di["channels"]:
        errors.append(f"{unit}: idle channel targets differ"); return
    s_t = [S.arr(s["input"])[:, 0] for s in si["samplers"]]
    d_t = [D.arr(s["input"])[:, 0] for s in di["samplers"]]
    s0 = min(t[0] for t in s_t); s_len = max(t[-1] for t in s_t) - s0
    d0 = min(t[0] for t in d_t); d_len = max(t[-1] for t in d_t) - d0
    f = expected["factor"]
    if abs(d0 - s0) > 1e-4 or abs(d_len - f * s_len) > 1e-4:
        errors.append(f"{unit}: idle spans {d_len:.5f} s from {d0:.4f}, expected {f} x {s_len:.5f} = {f * s_len:.5f} s from {s0:.4f}")
    wing_nodes = set(rep.get("wingNodes") or [])
    for ch in di["channels"]:
        path = ch["target"]["path"]
        if path not in ("translation", "rotation", "scale"):
            continue
        ss, ds = si["samplers"][ch["sampler"]], di["samplers"][ch["sampler"]]
        sv, dv = S.arr(ss["output"]), D.arr(ds["output"])
        st, dt = S.arr(ss["input"])[:, 0], D.arr(ds["input"])[:, 0]
        close = _quat_close(dv[-1], dv[0]) if path == "rotation" else float(np.max(np.abs(dv[-1] - dv[0])))
        if close > 1e-3:
            errors.append(f"{unit}: idle {path} of node {ch['target']['node']} does not close its loop ({close:.4g})")
        if ch["target"]["node"] in wing_nodes or len(st) == 2:
            continue
        for tk, vk in zip(s0 + (st - s0) * f, sv):
            j = int(np.argmin(np.abs(dt - tk)))
            if abs(dt[j] - tk) > 1e-4:
                errors.append(f"{unit}: idle {path} node {ch['target']['node']} has no key at stretched source time {tk:.4f}"); break
            dev = _quat_close(dv[j], vk) if path == "rotation" else float(np.max(np.abs(dv[j] - vk)))
            if dev > 1e-4:
                errors.append(f"{unit}: idle {path} node {ch['target']['node']} misses the source pose at {tk:.4f} ({dev:.3g})"); break
    return len(errors) == e0


PER_FRAME_LAYERS = {"uvAtlas", "effectLight", "volumetricFire"}   # one entry per DEF frame; defFlipbook may skip frames


def _idle_times(G, idle_clip):
    return np.unique(np.concatenate([G.arr(s["input"])[:, 0] for s in G.anim(idle_clip)["samplers"]]))


def texture_idle_errors(unit, root, S, dst, factor, idle_clip):
    """(errors, idle layers checked): look VFX idle layers against the source idle and, through the delivery time map, the retimed idle."""
    mp = os.path.join(root, f"artifacts/homm3_unit_look/{unit}/vfx/vfx_manifest.json")
    if not os.path.exists(mp):
        return [], 0
    m = json.load(open(mp, encoding="utf-8"))
    layers = {lid: ly for lid, ly in (m.get("layers") or {}).items() if idle_clip in (ly.get("clips") or {})}
    if not layers:
        return [], 0
    sys.path.insert(0, os.path.join(root, "tools/homm3_def_retarget_delivery"))
    import ship_def_retarget_slice as ship
    fps = ship.FPS
    if float(m.get("fps", 0)) != fps:
        return [f"{unit}: look vfx manifest fps {m.get('fps')} != {fps}; its idle windows cannot be mapped"], len(layers)
    fr = os.path.join(root, f"artifacts/homm3_def_retarget/{unit}/{unit}_def_retarget.blend.frames.json")
    try:
        loop = json.load(open(fr, encoding="utf-8"))["loops"][idle_clip]
        n, tk = int(loop["frames"]), int(loop.get("transitionKeys", 0))
    except Exception as e:
        return [f"{unit}: look vfx has idle layers {sorted(layers)} but the DEF idle frame count is unreadable "
                f"({os.path.relpath(fr, root)}: {type(e).__name__}: {e})"], len(layers)
    D = LazyGlb(dst)
    try:
        st, dt = _idle_times(S, idle_clip), _idle_times(D, idle_clip)
    finally:
        D.close()
    s0, s1, d0, d1 = float(st[0]), float(st[-1]), float(dt[0]), float(dt[-1])
    err = []
    if abs(s0 - 1 / fps) > 1e-4 or abs((s1 - s0) - (n + tk) / fps) > 1e-3:
        err.append(f"{unit}: source idle keys {s0:.4f}..{s1:.4f} s are not the DEF idle's {n} frames + {tk} transition "
                   f"keys from 1/{fps:g} s; the look's per-frame idle layers {sorted(layers)} no longer line up")
    fact = {"lookGlb": {"clips": {ship.IDLE: {"first": s0, "last": s1}}}, "idleFactor": float(factor),
            "glb": {"clips": {ship.IDLE: {"first": d0, "last": d1}}}}
    try:
        tmap, _ = ship.make_time_map(unit, fact)
    except ship.ShipError as e:
        return err + [f"{unit}: delivery time map refuses the retimed idle: {e}"], len(layers)
    if abs(tmap(idle_clip, s1) - d1) > 1e-4:
        err.append(f"{unit}: delivery time map sends the source idle end {s1:.4f} to {tmap(idle_clip, s1):.4f}, "
                   f"but the retimed idle ends at {d1:.4f}")
    for lid, ly in sorted(layers.items()):
        c = ly["clips"][idle_clip]
        keys = c.get("keys") if isinstance(c, dict) else c
        if not keys:
            continue
        frames = []
        for i, k in enumerate(keys):
            f = int(k.get("defFrame", i)) if isinstance(k, dict) else i
            w = k.get("window") if isinstance(k, dict) else None
            want = [(f + 0.5) / fps, (f + 1.5) / fps]
            if w is not None and max(abs(w[0] - want[0]), abs(w[1] - want[1])) > 1e-4:
                err.append(f"{unit}: {lid} ({ly['type']}) idle key {i} window {w} is not DEF frame {f}'s {want}")
                break
            frames.append(f)
        else:
            if max(frames) >= n or frames != sorted(set(frames)):
                err.append(f"{unit}: {lid} ({ly['type']}) idle keys name DEF frames {frames}; the DEF idle has {n}")
            elif ly["type"] in PER_FRAME_LAYERS and len(frames) != n:
                err.append(f"{unit}: {lid} ({ly['type']}) has {len(frames)} idle entries for a {n}-frame DEF idle; "
                           f"regenerate its cell list (e.g. tools/homm3_vfx/element_flow_scores.py {unit}) and re-apply the look")
            else:
                for f in frames:
                    t = tmap(idle_clip, s0 + f / fps)
                    if float(np.min(np.abs(dt - t))) > 1e-4:
                        err.append(f"{unit}: {lid} ({ly['type']}) DEF frame {f} maps to {t:.4f} s, where the retimed "
                                   f"idle has no key (texture and bones would drift apart)")
                        break
    return err, len(layers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=os.path.abspath(os.path.join(HERE, "..")))
    ap.add_argument("--unit", action="append", default=[])
    ap.add_argument("--require-complete", action="store_true")
    args = ap.parse_args()
    root = os.path.abspath(args.repo_root)
    errors, notes = [], []
    try:
        import idle_cadence_rule as rule
        table = rule.load_exceptions()
        errors += rule.table_errors(table)
    except Exception as e:
        print(f"HOMM3 IDLE CADENCE CONTRACT: FAIL\n  rule/exceptions table: {type(e).__name__}: {e}")
        return 1
    if not (1.0 <= rule.IDLE_TIME_SCALE <= 6.0 and 10 <= rule.RESAMPLE_HZ <= 120):
        errors.append(f"rule constants out of range: {rule.IDLE_TIME_SCALE}, {rule.RESAMPLE_HZ}")
    roster = os.path.join(root, "artifacts/homm3_idle_cadence/roster")
    reports = sorted(glob.glob(os.path.join(roster, "*", "report.json")))
    checked = stale = tex_units = tex_layers = 0
    done_units = set()
    for rp in reports:
        unit = os.path.basename(os.path.dirname(rp))
        if args.unit and unit not in args.unit:
            continue
        done_units.add(unit)
        rep = json.load(open(rp))
        expected = rule.treatment_for(unit, table)
        if rep.get("status") == "excluded" or rep.get("dst") is None:
            if expected["treatment"] != "exclude":
                errors.append(f"{unit}: report says excluded but the table now gives {expected['treatment']}; rerun rollout")
            continue
        dst = os.path.join(root, rep["dst"])
        glb_now = os.path.join(root, f"artifacts/homm3_def_retarget/{unit}/{unit}_def_retarget.glb")
        if not (os.path.exists(glb_now) and os.path.exists(dst)):
            notes.append(f"{unit}: GLB(s) not present locally; skipped")
            continue
        try:
            src, kind = os.path.join(root, rep["src"]), rep.get("srcKind")
            g = os.stat(glb_now)
            same = (g.st_size == rep.get("glbSize") and abs(g.st_mtime - rep.get("glbMtime", 0)) < 1e-3
                    and os.path.exists(src) and os.stat(src).st_size == rep.get("srcSize")
                    and abs(os.stat(src).st_mtime - rep.get("srcMtime", 0)) < 1e-3)
            if not same:            # files changed: re-resolve (hashes whole GLBs, so only when needed)
                src, kind = rule.resolve_input(unit)
            S = LazyGlb(src)
            cur_sha = rule.anim_sha256(S.js, S.raw)
        except Exception as e:
            errors.append(f"{unit}: cannot resolve the retime input: {type(e).__name__}: {e}")
            continue
        emph = rule.emphasis_errors(unit, S.js)
        if emph:
            stale += 1
            errors += [e + f"; the retimed GLB is not usable - rerun: python tools/homm3_idle_cadence/rollout_idle.py {unit}" for e in emph]
            S.close()
            continue
        if cur_sha != rep.get("srcAnimSha256"):     # a look apply may move the input path; the animation decides
            stale += 1
            errors.append(f"{unit}: STALE - the retime input's animation changed since the retime (emphasis or a "
                          f"rebuild; now {kind} {cur_sha[:12]}, retimed from {str(rep.get('srcAnimSha256'))[:12]}); "
                          f"the retimed GLB is not usable - rerun: python tools/homm3_idle_cadence/rollout_idle.py {unit}")
            S.close()
            continue
        try:
            check_unit(unit, S, dst, rep, expected, errors, rule.IDLE_CLIP)
            checked += 1
            tex, nl = texture_idle_errors(unit, root, S, dst, expected["factor"], rule.IDLE_CLIP)
            tex_units += nl > 0
            tex_layers += nl
            errors += tex
        except Exception as e:
            errors.append(f"{unit}: {type(e).__name__}: {e}")
        finally:
            S.close()
    if args.require_complete:
        for p in glob.glob(os.path.join(root, "artifacts/homm3_def_retarget/*/*_def_retarget.glb")):
            u = os.path.basename(os.path.dirname(p))
            if os.path.basename(p) != f"{u}_def_retarget.glb" or (args.unit and u not in args.unit):
                continue
            if u not in done_units and rule.treatment_for(u, table)["treatment"] != "exclude":
                errors.append(f"{u}: def_retarget GLB has no retimed idle and no exclude entry")
    status = "OK" if not errors else "FAIL"
    print(f"HOMM3 IDLE CADENCE CONTRACT: {status} (table {len(table['units'])} entries, "
          f"{len(reports)} reports, {checked} GLB pairs checked, {stale} stale; "
          f"{tex_layers} look VFX idle layers on {tex_units} units in step with the retimed idle)")
    for n in notes[:20]:
        print("  note:", n)
    if len(notes) > 20:
        print(f"  note: ... {len(notes) - 20} more")
    for e in errors:
        print("  ERROR:", e)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
