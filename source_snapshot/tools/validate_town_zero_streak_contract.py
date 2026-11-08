#!/usr/bin/env python3
"""Gate: the full-3D town zero-visible-streak lane (docs/homm3_town_scene_methodology_v2.md) keeps its bar.

    python tools/validate_town_zero_streak_contract.py [--static-only]

Static (source):
  - the certificate (tools/homm3_town_scene_meshes/town_full3d_zero_streak.py) passes only on zero visible behind
    components at every pose, with the streak / reveal / area thresholds of the user's bar (2026-10-01: "0 visible
    streaking behind objects");
  - the recipe builder (town_full3d_recipe.py) gates on that pass *and* on no ground hole beyond the rest frame's own
    count, in every certified state, and fails closed;
  - the LDI pass keeps its installed defaults (ratio-cap back rule, KEEP_ROUNDS hole keeping): the view-set bound and
    no-keep options are opt-in flags, so a shipped candidate is never silently rebuilt under another rule;
  - the repair rule flap (town_full3d_step_flap.py) keeps its flaps hidden at rest (FLAP_HIDE) and on the residual's
    own affine texels, and its unit test and the candidate-fork inheritance test (test_town_full3d_fork.py) pass;
  - every recipe under tools/homm3_town_scene_meshes/recipes/ parses under schema town_full3d_recipe.v1.
Staged (generated artifact): for every recipe whose candidate is staged on this machine, `town_full3d_recipe.py
verify` - the stored result passes, came from this recipe file, and every bin it measured is byte-identical. A
candidate that is not staged here (artifacts/ is not in git) is reported and skipped. No raster runs here: the
certificate itself is the recipe build's gate. Proof tier: source/static + generated artifact.
GPU (docs/town_gpu_kernels.md): the certificate's default device is cuda (town_gpu_kernels). Static: the CPU reference
path and the --device cpu|cuda switch stay, and the default is cuda only together with the parity test. Staged:
test_town_gpu_kernels.py certifies real staged scenes on both devices and requires byte-identical reports (a scene not
staged here is skipped; a missing CUDA device fails, as the certificate itself would).
Recipe v2 (town_full3d_recipe.v2; Castle zs_v5 user 2026-10-01: floating cottages, meshes off their textures). Static:
  - the gate requires zero unseen-face px (town_full3d_zero_streak.unseen_face) in every state and the ground-contact
    gate (town_full3d_ground_contact.contact_gate) on the staged files; anchoring fails closed on a changed rest frame;
  - the build states come from the building tree (town_full3d_build_states) and verify re-derives their sha, so the
    certified set cannot shrink; v2 forbids certificate.states; `final` (the reachable-range gate) stays and verify
    requires it on the installed scene;
  - ground contact keeps its thresholds and its --device cpu|cuda switch with the cpu reference, and its parity test;
    anchor leaves a piece it cannot ground as it is only when its gap is within CONTACT_GATE_M ("withinGate").
  - the houses lane's foot check keeps its thresholds; fit fails closed on it, stage requires its record, and the
    fit's ground ring excludes the propMask px.
  - the rest-paint term (town_full3d_recipe.rest_paint: the rest albedo against the HoMM3 painting, every build state)
    keeps its thresholds and gates the build and `final`; the houses stage re-runs the props check, which measures
    rest visibility in every build state without the staged props occluding their own instances; Stage carries a
    cloth bin's vertex colours (.vcol) through card and planar.
  - the houses fit's foot slide is a scale about the rest camera bounded by FOOT_SLIDE_MAX; the sprite ground decals
    (town_full3d_sprite_decal) run before the repair rounds on the rest-paint thresholds, never emit a quad across a
    depth step, and are measured as building-depth decal bins (span like ray; no seam, no flap).
Staged: test_town_ground_contact_gpu.py --quick on GC_PARITY_SCENE when it is staged here (skipped otherwise).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "tools" / "homm3_town_scene_meshes"
CERT = TS / "town_full3d_zero_streak.py"
RECIPE = TS / "town_full3d_recipe.py"
LDI = TS / "town_full3d_ldi.py"
RECIPES = TS / "recipes"
FLAP = TS / "town_full3d_step_flap.py"
UNIT_TESTS = ("test_town_full3d_step_flap.py", "test_town_full3d_fork.py", "test_town_full3d_known_gaps.py")
GPU_PARITY_TEST = "test_town_gpu_kernels.py"
GC = TS / "town_full3d_ground_contact.py"
HOUSES = TS / "town_full3d_houses.py"
BSTATES = TS / "town_full3d_build_states.py"
GC_PARITY_TEST = "test_town_ground_contact_gpu.py"
GC_PARITY_SCENE = ("castle", "zs_v5")
TERRAIN_PARITY_TEST = "test_town_gpu_terrain.py"     # periphery bake + raymarch, cpu reference vs cuda
MECH_PARITY_TEST = "test_town_gpu_mech.py"           # fx wheel hub grid (town_full3d_mech.fit_wheel), cpu vs cuda


def static_errors() -> list[str]:
    errs = []
    c = CERT.read_text(encoding="utf-8")
    if not re.search(r'"pass": all\(r\["visibleBehindComponents"\] == 0 for r in P_\.values\(\)\)', c):
        errs.append(f"{CERT.name}: pass must be zero visible behind components at every pose")
    for name, val in (("MIN_AREA", "16"), ("REVEAL_TOL", "0.03")):
        if not re.search(rf"^{name}\s*=\s*{re.escape(val)}\b", c, re.M):
            errs.append(f"{CERT.name}: {name} must stay {val} (the certificate's visible / revealed rule)")
    if not re.search(r'^DEVICES = \("cpu", "cuda"\)', c, re.M) or 'add_argument("--device", choices=DEVICES' not in c:
        errs.append(f"{CERT.name}: the --device cpu|cuda switch must stay (cpu is the reference implementation)")
    if "TP.zbuffer(sc.cam, P, F, sup=1)" not in c or 'if device == "cuda":' not in c:
        errs.append(f"{CERT.name}: the CPU reference path must stay next to the cuda path")
    if not (TS / GPU_PARITY_TEST).is_file():
        errs.append(f"{GPU_PARITY_TEST}: missing (the cuda default needs its parity test)")
    r = RECIPE.read_text(encoding="utf-8")
    if not re.search(r'v\["maxVisibleBehindPx"\] == 0 and v\["pass"\] and v\["groundHoleGrowthPx"\] == 0', r):
        errs.append(f"{RECIPE.name}: the gate must require zero visible px, pass and zero ground-hole growth per state")
    if 'fail(f"gate: the staged candidate does not pass' not in r:
        errs.append(f"{RECIPE.name}: a failing gate must fail the build")
    # ---- recipe v2: unseen faces, ground contact, build states from the tree, the reachable-range final gate
    for needle, why in (
            ('and (not v2 or v["maxUnseenFacePx"] == 0) for v in summ.values())',
             "the v2 gate must require zero unseen-face px in every state"),
            ('ok = ok and cg["pass"]', "the v2 gate must require ground contact"),
            ('fail(f"ground contact: anchoring changed the rest frame', "anchoring must fail closed on a changed rest frame"),
            ("GC.anchor(gs, lambda faces=None: GC.rest_identity(gs, before, faces), T, drop=drop)",
             "anchoring must run strict (fail closed) in the build"),
            ("BS.enumerate_states(SC.FP, SC.layer_map())", "v2 build states must come from the building tree"),
            ('if bs.get("sha256") != BS.states_sha(layers_of)', "verify must re-derive the build-state sha"),
            ("a {SCHEMA_V2} recipe measures every build state of the tree", "v2 must forbid certificate.states"),
            ('choices=["build", "verify", "final", "rest-paint", "_finish", "_catalog"]',
             "the final (reachable-range) and rest-paint commands must stay"),
            ('ok = ok and cg["pass"] and rp["pass"]', "the v2 gate must require the rest-paint term"),
            ('if not g["restPaint"]["pass"]:', "final must fail closed on the rest-paint term"),
            ('b["col"] = np.concatenate([b["col"], b["col"][b["f"][lf]].reshape(-1, 4)])',
             "card and planar must carry cloth vertex colours"),
            ("has no passing final gate", "verify must require the final gate on the installed scene"),
            ('fail(f"repair: {len(ufails)} unseen faces stretch and the recipe does not allow rule planar")',
             "unseen faces must fail closed without rule planar"),
            ('fail(f"repair: only faces that already are cards still fail, round {rnd}',
             "a face that already is a card is held, and the build fails closed when only such cards are left"),
            ('fail(f"repair: {len(fails)} faces still fail after {n_rounds} rounds (cycle {cycle})")',
             "the round cap must fail the build"),
            ("            if not fails and not ufails:\n                break",
             "the rounds end only on a clean certificate")):
        if needle not in r:
            errs.append(f"{RECIPE.name}: {why}")
    if "def unseen_face(" not in c or "def reachable_cams_full(" not in c:
        errs.append(f"{CERT.name}: unseen_face() and reachable_cams_full() must stay")
    if not BSTATES.is_file() or 'SCHEMA = "town_build_states.v1"' not in BSTATES.read_text(encoding="utf-8"):
        errs.append(f"{BSTATES.name}: missing or not town_build_states.v1")
    g = GC.read_text(encoding="utf-8") if GC.is_file() else ""
    for name, val in (("CONTACT_GATE_M", "0.15"), ("ANCHOR_TOL_M", "0.05"), ("FILL_SPIKE_DEG", "45.0")):
        if not re.search(rf"^{name}\s*=\s*{re.escape(val)}\b", g, re.M):
            errs.append(f"{GC.name}: {name} must stay {val}")
    if 'ok = all(e["floating"] == 0 and e["unsupported"] == 0 for e in by.values())' not in g:
        errs.append(f"{GC.name}: the contact gate must pass only with no floating and no unsupported piece")
    if "        if g <= CONTACT_GATE_M:\n" not in g or "            fail(msg)\n" not in g:
        errs.append(f"{GC.name}: anchor may leave an ungroundable piece as it is only within CONTACT_GATE_M (strict "
                    f"fails closed over it)")
    # extensionDrop (coordinator decision 2026-10-02): nearfield dressing only, wholly outside the painted rect before
    # and after, 0 px change inside the rect in every state; the recipe re-checks the rect against the pre-anchor frames
    for needle, why in (('EXT_DROP = re.compile(r"^Mesh_Near_[A-Za-z]+(_\\d+)?$")', "extensionDrop is Mesh_Near_* only"),
                        ('        return None, "lies partly inside the painted rect"', "a piece must lie wholly "
                         "outside the painted rect"),
                        ('        return None, "would drop into the painted rect"', "and stay outside after the drop"),
                        ("    if any(inside.values()):\n        b[\"v\"] = v0\n", "a drop that changes the painted rect "
                         "is undone"),
                        ('"restPxOutsideRect"', "the outside-rect px are recorded")):
        if needle not in g:
            errs.append(f"{GC.name}: {why}")
    if "if any(ch.values()) or any(ch_rect.values()):" not in r:
        errs.append(f"{RECIPE.name}: ground contact must re-check the painted rect against the pre-anchor frames")
    # removeHidden (coordinator 2026-10-02): a named piece (bin, piece, verts identity pin, reason) is dropped only after
    # the environment-alone raster proves 0 px at rest and every reachable pose; recorded in the build result
    for needle, why in (('REMOVE_HIDDEN_KEYS = {"bin", "piece", "verts", "why"}', "removeHidden entries carry an "
                         "identity pin and a reason"),
                        ('fail("removeHidden: named pieces draw px at the rest camera or a reachable pose', "a named "
                         "piece that draws any px fails closed"),
                        ("re-measure before removing anything", "a renumbered / reshaped piece fails closed")):
        if needle not in g:
            errs.append(f"{GC.name}: {why}")
    if 'res["removedHidden"] = removed' not in r or "cams_rh = {**ZS.reachable_cams_full(sc, 48), **cams}" not in r:
        errs.append(f"{RECIPE.name}: removeHidden must prove against every sweep sample and final's poses and be "
                    "recorded in the build result")
    # peripherySettle (Dungeon zs_v4 2026-10-02): the periphery's own settle rule re-applied against the staged frame
    # surface; only Mesh_Outer pieces with a reason, fails closed on sky intrusions and on any intrusion left, and every
    # v2 build records the measured intrusion
    for needle, why in (('PERIPHERY_SETTLE_KEYS = {"pieces", "why"}', "peripherySettle entries name pieces and a reason"),
                        ("intrusion px remain after {PERIPHERY_SETTLE_ROUNDS} rounds", "intrusions left fail closed"),
                        ("(an intrusion into the sky has no settle depth)", "a sky intrusion fails closed"),
                        ("intr = drawn & (~has | (zA < zF))", "an intrusion is any piece px nearer than the frame or "
                         "over no frame surface"),
                        ('res["periphery"] = per_settle', "the build result records the periphery block")):
        if needle not in r:
            errs.append(f"{RECIPE.name}: {why}")
    # restOwner (Fortress zs_v2 2026-10-02): listed Meshy layers are drawn at rest only where the painting shows them;
    # only rest-paint-differing px act, outside-own-sprite faces drop, covered faces go back along their rest rays,
    # the rounds are capped (fail closed) and the build result records the block
    for needle, why in (('REST_OWNER_KEYS = {"layers", "why"}', "restOwner entries name layers and a reason"),
                        ("mis = rect & differs & np.isin(ob, mine) & ~grow(top == ia)",
                         "a misowned px differs from the painting, is drawn by the layer and is not its owner px"),
                        ('misowned px remain after {REST_OWNER_ROUNDS} rounds', "the round cap fails closed"),
                        ('b["v"][vv[go]] *= (zt[go] / zc[go])[:, None]', "a covered face moves along its rest rays"),
                        ('res["restOwner"] = rest_own', "the build result records the restOwner block")):
        if needle not in r:
            errs.append(f"{RECIPE.name}: {why}")
    # restSky refinement of the ground-hole term (coordinator 2026-10-02): excluded only where the pose's Sky_ raster
    # covers the px (explicit, fail closed without sky); hidden always counts; both are reported per pose
    c = CERT.read_text(encoding="utf-8")
    # background frame (coordinator 2026-10-02, general correctness fix): q is also judged against the environment-only
    # rest frame (no building layer, no backstop / floor fill); still excluded only where the pose's Sky_ covers the px
    for needle, why in (("    return (sky_state & cov, sky_any, ins & ~sky_any & (fr >= 0) & (z0[yi, xi] < zc),\n"
                         "            sky_any & ~sky_state & cov)", "restSky / restSkyEnv need the sky coverage; hidden "
                         "is a rest surface in front of the hit point where the background frame is drawn"),
                        ("cov = np.zeros(len(xs), bool) if sky_cov is None else sky_cov[yi0, xi0]", "without sky no "
                         "px is excluded"),
                        ('env_bins = np.array([n.startswith("environment/") and bin_class(n) != "backstop" for n in names]',
                         "the background frame is the environment bins without the backstop class and no building"),
                        ('raise SystemExit("zero-streak: the restSky refinement needs the background frame', "no "
                         "background frame with sky fails closed"),
                        ('"groundRestSkyPx": int(rs.sum()), "groundRestSkyEnvPx": int(rs_env.sum()),', "every class is "
                         "reported per pose"),
                        ("ground[gy[rs | rs_env], gx[rs | rs_env]] = False", "only the covered restSky px leave the "
                         "ground count")):
        if needle not in c:
            errs.append(f"{CERT.name}: {why}")
    # backstop.groundFloor (Inferno zs_v3): the floor fill is hidden at rest in every state, fail closed
    for needle, why in (('fail(f"floor fill: {len(shown_fill)} fill faces draw', "a floor fill face drawn at rest in "
                         "any state fails the build"),
                        ("valid = cover & (s > 0) & (dist < cap) & (s > behind * zmax)", "the "
                         "fill only stands behind every state's rest surface"),
                        ("    cap = far_cap + reach", "the fill reaches the far cap of every certified pose camera"),
                        ('E = int(min(FLOOR_FILL_EXT_PX, m["left"], m["right"], m["top"], m["bottom"]))', "the fill "
                         "extends past the rest frame inside the backstop's margin (off-frame ground always counts)"),
                        ("{**cams, **ZS.reachable_cams_full(sc, FINAL_LOOP)}", "the fill's reach covers the build's and "
                         "`final`'s cams"),
                        ("prune = np.asarray(sorted(sky_t - ground_t - set(np.nonzero(prune_keep)[0].tolist())), np.int64)",
                         "the sky-side prune keeps fill faces that are ground for some certified pose"),
                        ('seen[FF["px"][:, 0] + m["top"], FF["px"][:, 1] + m["left"]] = True', "every fill square's "
                         "texel gets content (a final pose may see it)")):
        if needle not in r:
            errs.append(f"{RECIPE.name}: {why}")
    # the sky-side prune's ground keep reads the certified pose set (Dungeon zs_v7: 1-px slits onto backstop
    # triangles only a `final` pose's ground ray meets); parity: test_town_full3d_prune_ground.py (needs CUDA)
    for needle, why in (("def ground_ray_px(", "ground_ray_px (the per-pose ground-ray mask) must stay"),
                        ("def final_ground_tris(", "final_ground_tris (backstop ground rays of final's poses) must stay"),
                        ("final_only = {k: c for k, c in cert_cams.items() if k not in cams}", "the prune's extra "
                         "ground pass covers every certified pose the build does not"),
                        ("ground_t |= final_ground_tris(stage, state_keys, final_only, final_masks, bs_bi)", "a "
                         "backstop triangle a final pose's ground ray meets is kept by the sky-side prune")):
        if needle not in r:
            errs.append(f"{RECIPE.name}: {why}")
    # certificate.extraPoses "final" (opt-in): the build certifies final's own pose set from the start
    for needle, why in (('EXTRA_POSES_FINAL = "final"', 'the extraPoses value "final" must stay'),
                        ("        return ZS.reachable_cams_full(sc, FINAL_LOOP)", 'extraPoses "final" resolves to '
                         "final's pose set (reachable_cams_full(sc, FINAL_LOOP))"),
                        ("    cams = cert_cams_of(sc, ZS, r)", "the build's rounds, prune and gate read cert_cams_of")):
        if needle not in r:
            errs.append(f"{RECIPE.name}: {why}")
    if not (TS / "test_town_full3d_prune_ground.py").is_file():
        errs.append("test_town_full3d_prune_ground.py (ground_ray_px cpu/cuda parity) must stay")
    if r.count("sky=ZS.load_sky(sc, rows, ") != 2:
        errs.append(f"{RECIPE.name}: the repair-round and gate certificates must pass the staged Sky_ bins")
    if "ZS.ground_split(sc, cam, self.floor, yb, xb, self.fid_rest_np, self.z0_np, cov_np,\n" \
            "                                             self.fid_env_np)" not in \
            (TS / "town_gpu_kernels.py").read_text(encoding="utf-8"):
        errs.append("town_gpu_kernels.py: the cuda ground split must re-decide its borderline px with the reference")
    if 'add_argument("--device", choices=["cpu", "cuda"]' not in g or "def _gap_cuda(" not in g \
            or "self.TP.zbuffer(self.sc.cam, P, F, sup=1)" not in g:
        errs.append(f"{GC.name}: the --device switch and the cpu reference path must stay next to the cuda path")
    if not (TS / GC_PARITY_TEST).is_file():
        errs.append(f"{GC_PARITY_TEST}: missing (the ground-contact cuda path needs its parity test)")
    for f, sig, ref in (("stronghold_full3d_periphery.py", "def bake_piece(baker, field, floor, cam, pc: dict, device",
                         "GT.bake_piece(baker, field, floor, cam, pc)"),
                        ("stronghold_full3d_terrain.py", "def raymarch(cam, field: Field, px, py, t0=5.0, t1=None, device",
                         "GT.raymarch(cam, field, px, py, t0, t1)")):
        src = (TS / f).read_text(encoding="utf-8")
        if sig not in src or ref not in src or "GK.resolve_device(device)" not in src:
            errs.append(f"{f}: the device switch (cpu reference body + cuda dispatch to town_gpu_terrain) must stay")
    m = (TS / "town_full3d_mech.py").read_text(encoding="utf-8")
    if "def fit_wheel(F, rect, lid: str, e: dict, device" not in m or "GM.wheel_grid_scores(" not in m             or "b = max((_wheel_score(D, ev, ever, cx, cy, 1.0, 0.0, s, ks), s) for s in steps)" not in m:
        errs.append("town_full3d_mech.py: fit_wheel's device switch and its cpu re-score of the near-best cells must stay")
    if not (TS / MECH_PARITY_TEST).is_file():
        errs.append(f"{MECH_PARITY_TEST}: missing (the wheel hub grid's cuda path needs its parity test)")
    if not (TS / TERRAIN_PARITY_TEST).is_file():
        errs.append(f"{TERRAIN_PARITY_TEST}: missing (the terrain bake / raymarch cuda path needs its parity test)")
    # the houses lane's foot check (Castle zs_v6 2026-10-01: hand label boxes cut through the painted walls, so the
    # fitted models floated 4-7 m over the painted ground): fit fails closed on it, stage refuses without its record
    hs = HOUSES.read_text(encoding="utf-8")
    for name, val in (("FOOT_ROW_PX", "4"), ("FOOT_TOL", "0.08"), ("FOOT_FLOAT_MAX", "0.25"), ("FOOT_MIN_PX", "8")):
        if not re.search(rf"^{name}\s*=\s*{re.escape(val)}\b", hs, re.M):
            errs.append(f"{HOUSES.name}: {name} must stay {val} (the foot check)")
    for needle, why in (("    foot = foot_check(hd, peers, sc, st)\n", "fit must run the foot check"),
                        ('raise SystemExit(f"fit: foot check fails for labels', "fit must fail closed on the foot check"),
                        ("    require_foot(dirs)\n", "stage must require a passing foot_contact.json"),
                        ("& ~self.sky & ~self.prop", "the fit's ground ring must exclude the propMask px")):
        if needle not in hs:
            errs.append(f"{HOUSES.name}: {why}")
    for name, val in (("REST_PAINT_CHROMA", "8.0"), ("REST_PAINT_MIN_SUM", "60.0"), ("REST_PAINT_AREA", "400")):
        if not re.search(rf"^{name}\s*=\s*{re.escape(val)}\b", r, re.M):
            errs.append(f"{RECIPE.name}: {name} must stay {val} (the rest-paint term)")
    # the smoke / flame exclusion class (coordinator decision 2026-10-02): fixed kinds, 2 px dilation, caps, and the
    # emitter requirement; widening any of them is a new decision, not an edit
    for name, val in (("REST_PAINT_FX_KINDS", '{"smoke": "Fx_Smoke_", "flame": "Fx_Flame_"}'),
                      ("REST_PAINT_FX_DILATE_PX", "2"), ("REST_PAINT_FX_MAX_PX", "6000"),
                      ("REST_PAINT_FX_MAX_SHARE", "0.25")):
        if not re.search(rf"^{name}\s*=\s*{re.escape(val)}\s*$", r, re.M):
            errs.append(f"{RECIPE.name}: {name} must stay {val} (the rest-paint smoke / flame exclusion class)")
    for needle, why in (('            if not emit:\n                continue\n', "an effect without its staged emitter "
                         "is not excluded"),
                        ("            if int(e_l.sum()) > cap:\n                fail(", "a layer's exclusion over its cap "
                         "fails closed"),
                        ('            px_cap = int(ov["pxCap"]) if ov else REST_PAINT_FX_MAX_PX\n'
                         '            cap = min(px_cap, share * fxm[l]["spritePx"])',
                         "a layer's cap is the smaller of REST_PAINT_FX_MAX_PX (an approved entry's pxCap) and its "
                         "sprite share"),
                        ('"fxExcludedPx": int(excl.sum()), "fxExcluded": ex_by', "the excluded px are recorded per "
                         "state and layer"),
                        ('"fxExcludedByState": fx_excluded_by_state(g["restPaint"])', "final reports the per-layer "
                         "excluded px of every state"),
                        # per-layer share overrides: only the ones the coordinator approved by name (2026-10-02)
                        ('REST_PAINT_FX_SHARE_APPROVED = {\n'
                         '    ("bulwark", "tbbumr01"): {"share": 0.40, "pxCap": 8000, "reason": "pyre layer: painting '
                         'is mostly its own flame"},\n'
                         '    ("necropolis", "tbncspec"): {"share": 0.40, "pxCap": 21000,\n'
                         '                                 "reason": "Cover of Darkness: painting is mostly its own '
                         'black smoke"},\n}\n', "the approved overrides are exactly Bulwark's pyre (40 %, 8000 px) and "
                         "Necropolis' Cover of Darkness (40 %, 21000 px): a new one is a new decision"),
                        ('        raise SystemExit(f"town recipe: REST_PAINT_FX_SHARE_APPROVED{_k} must be', "an approved "
                         "entry without share / pxCap / reason fails at import"),
                        ('        if not ok_ or ap_ is None or not REST_PAINT_FX_MAX_SHARE < float(o["share"]) <= '
                         'ap_["share"]:', "load_recipe refuses an override outside the approved table"),
                        ('**({"shareOverride": share_override[l]} if share_override and l in share_override else {}),',
                         "the report names an overridden layer"),
                        # known min_ gaps: only the ones the coordinator approved by name (2026-10-02)
                        ('REST_PAINT_KNOWN_GAPS_APPROVED = {\n'
                         '    ("factory", "min_tbfacas2"): {"layer": "tbfacas2", "maxPx": 590,\n'
                         '                                  "reason": "Meshy T2 cas2 spire over painted sky; same gap '
                         'installed in pb_v1"},\n'
                         '    ("bulwark", "min_tbbucstl"): {"layer": "tbbucstl", "maxPx": 1336,\n'
                         '                                  "reason": "Meshy T2 Castle tower crenels over painted sky; '
                         'same gap installed in pb_v1"},\n'
                         '    ("bulwark", "min_tbbubl01"): {"layer": "tbbucstl", "maxPx": 1336,\n'
                         '                                  "reason": "Meshy T2 Castle tower crenels over painted sky; '
                         'same gap installed in pb_v1"},\n}\n', "the approved known gaps are exactly Factory's "
                         "min_tbfacas2 (590 px) and Bulwark's min_tbbucstl / min_tbbubl01 (1336 px): a new one is a new "
                         "decision"),
                        ('            or not str(_k[1]).startswith("min_"):', "only min_ states are eligible"),
                        ("    apply_known_gaps(by, known_gaps)\n", "rest_paint applies the known gaps"),
                        ('"knownGaps": {s: v["knownGap"] for s, v in by.items() if "knownGap" in v}}',
                         "the result records the known gaps"),
                        ('{k: g["restPaint"][k] for k in ("pass", "maxComponentPx", "failing", "knownGaps")}',
                         "final reports the known gaps")):
        if needle not in r:
            errs.append(f"{RECIPE.name}: rest paint: {why}")
    if "    import town_t2_props as PR\n" not in hs or "        if PR.check():\n" not in hs:
        errs.append(f"{HOUSES.name}: stage must re-run the props check (a moved house can expose a prop at rest)")
    pr = (TS / "town_t2_props.py").read_text(encoding="utf-8")
    if "for st, ls in BS.enumerate_states(SC.FP, SC.layer_map()).items():" not in pr or "Fo = Fs_[npr[ow_]]" not in pr:
        errs.append("town_t2_props.py: check must measure rest visibility in every build state, staged props excluded")
    # scoped floating-rule exemptions (coordinator 2026-10-02, finish lane): exactly Stronghold's ridge-top butte, pinned
    # to its pb_v1 base and its measured elevation; only the elevation term, at the pinned value (a new entry is a new
    # decision)
    for needle, why in (('FLOAT_EXEMPT_APPROVED = {\n'
                         '    ("stronghold", "butte"): {"base": (154.4405, 31.3531, 152.9652), "minElevationDeg": -8.39,\n',
                         "the approved floating exemptions are exactly Stronghold's butte at its pinned base and "
                         "elevation"),
                        ("FLOAT_EXEMPT_BASE_TOL = 0.01 ", "the exemption's base pin tolerance is 0.01 m"),
                        ("FLOAT_EXEMPT_ELEV_TOL = 0.01 ", "the exemption's elevation pin tolerance is 0.01 deg"),
                        ('        if set(f) != {"minElevationDeg"} or abs(f["minElevationDeg"] - ex["minElevationDeg"]) '
                         '> FLOAT_EXEMPT_ELEV_TOL:\n', "only the elevation term at the pinned value is exempted"),
                        ('    rep["exempt"] = apply_float_exempt(SC.FACTION, rep["floating"], pl["instances"])\n',
                         "check applies the exemptions and records them")):
        if needle not in pr:
            errs.append(f"town_t2_props.py: float exemption: {why}")
    if not re.search(r'^FLOAT_EXEMPT_APPROVED = \{\n    \("stronghold", "butte"\): \{[^}]*\},\n\}\n', pr, re.M):
        errs.append("town_t2_props.py: float exemption: FLOAT_EXEMPT_APPROVED must hold exactly one entry")
    # fit's foot slide: only a scale about the rest camera (base and scale x k: every rest px kept), bounded
    if not re.search(r"^FOOT_SLIDE_MAX\s*=\s*1\.5\b", hs, re.M) or \
            'x["base"] = (c + (np.asarray(x["base"]) - c) * k).tolist()' not in hs or \
            'x["scale"] = float(x["scale"] * k)' not in hs:
        errs.append(f"{HOUSES.name}: the foot slide must stay a scale about the rest camera bounded by FOOT_SLIDE_MAX 1.5")
    # sprite ground decals (town_full3d_sprite_decal.py): before the repair rounds (the rounds certify them), the
    # rest-paint term's own thresholds pick the px, no quad across a depth step, building-depth role ray
    dc_path = TS / "town_full3d_sprite_decal.py"
    dc = dc_path.read_text(encoding="utf-8") if dc_path.is_file() else ""
    if not re.search(r"^DEPTH_JUMP\s*=\s*0\.05\b", dc, re.M) or "q_ok = q_any & q_env & (jump <= DEPTH_JUMP)" not in dc:
        errs.append(f"{dc_path.name}: missing, or a decal quad may span a depth step (DEPTH_JUMP 0.05)")
    i_dc, i_rounds = r.find("    if \"decal\" in r:\n        import town_full3d_sprite_decal as DC"), r.find("    # ---- 4. repair rounds")
    if i_dc < 0 or i_rounds < 0 or i_dc > i_rounds or \
            ('REST_PAINT_MIN_SUM, fx_masks={l: v["mask"] for l, v in fxm.items() if v["mask"] is not None},\n'
             '                     layer_depth="layerDepth" in r["decal"])\n        decal = ') not in r:
        errs.append(f"{RECIPE.name}: the decal step must run before the repair rounds with the rest-paint thresholds "
                    "and the rest-paint fx masks")
    if "            inside &= ~fxm\n" not in dc:
        errs.append(f"{dc_path.name}: a layer's staged smoke / flame px (fx_masks) must never be laid as a decal")
    bd_src = (TS / "town_full3d_building_depth.py").read_text(encoding="utf-8")
    if 'if name == f"Mesh_Decal_{lid}":' not in bd_src or '        return "decal"' not in bd_src or \
            'if r in ("fx", "cloth", "decal")' not in (TS / "town_full3d_building_seams.py").read_text(encoding="utf-8"):
        errs.append("town_full3d_building_depth.py: Mesh_Decal_<layer> must be measured (role decal; no building seam)")
    ldi = LDI.read_text(encoding="utf-8")
    if not re.search(r'add_argument\("--back-rule", default="cap"', ldi):
        errs.append(f"{LDI.name}: --back-rule must default to cap (the installed rule)")
    if not re.search(r'add_argument\("--keep-rounds", type=int, default=KEEP_ROUNDS', ldi):
        errs.append(f"{LDI.name}: --keep-rounds must default to KEEP_ROUNDS")
    if not re.search(r"^KEEP_ROUNDS = 4\b", ldi, re.M):
        errs.append(f"{LDI.name}: KEEP_ROUNDS must stay 4")
    fl = FLAP.read_text(encoding="utf-8")
    for name, val in (("FLAP_HIDE", "1.01"), ("FLAP_UV_TOL", "0.5"), ("STEP_EPS", "0.02")):
        if not re.search(rf"^{name}\s*=\s*{re.escape(val)}\b", fl, re.M):
            errs.append(f"{FLAP.name}: {name} must stay {val} (a flap stays hidden at rest, on the residual's own texels)")
    if 'mi = b["vMap"][g["lipVertex"]]' not in r or "FL.uv_affine_charts(bx, by, b[\"f\"], b[\"uv\"], shown, b[\"tex\"]) if len(shown)" not in r:
        errs.append(f"{RECIPE.name}: rule flap must take each flap vertex's uv from its lip vertex's chart map")
    for t in UNIT_TESTS:                        # pure numpy, seconds: the rule flap and the fork inheritance
        q = subprocess.run([sys.executable, str(TS / t)], cwd=str(ROOT), capture_output=True, text=True, timeout=300)
        if q.returncode:
            errs.append(f"{t}: {((q.stdout + q.stderr).strip().splitlines() or ['failed'])[-1]}")
    sys.path.insert(0, str(TS))
    import town_full3d_recipe as R
    for p in sorted(RECIPES.glob("*.json")):
        try:
            R.load_recipe(p)
        except SystemExit as e:
            errs.append(str(e))
    return errs


def staged_errors() -> list[str]:
    errs = []
    q = subprocess.run([sys.executable, str(TS / GPU_PARITY_TEST)], cwd=str(ROOT), capture_output=True, text=True,
                       timeout=1200)
    out = [l for l in (q.stdout + q.stderr).splitlines() if l.startswith(("FAIL", "SKIP", "town gpu")) or " poses, " in l]
    for l in out:
        print(f"{GPU_PARITY_TEST}: {l}")
    if q.returncode:
        errs.append(f"{GPU_PARITY_TEST}: {(out or ['failed'])[-1]}")
    q = subprocess.run([sys.executable, str(TS / TERRAIN_PARITY_TEST)], cwd=str(ROOT), capture_output=True, text=True,
                       timeout=1200)
    tail = ((q.stdout + q.stderr).strip().splitlines() or ["failed"])[-1]
    print(f"{TERRAIN_PARITY_TEST}: {tail}")
    if q.returncode:
        errs.append(f"{TERRAIN_PARITY_TEST}: " + ("; ".join(l for l in (q.stdout + q.stderr).splitlines()
                                                           if l.startswith("FAIL")) or tail))
    q = subprocess.run([sys.executable, str(TS / MECH_PARITY_TEST)], cwd=str(ROOT), capture_output=True, text=True,
                       timeout=900)
    tail = ((q.stdout + q.stderr).strip().splitlines() or ["failed"])[-1]
    print(f"{MECH_PARITY_TEST}: {tail}")
    if q.returncode:
        errs.append(f"{MECH_PARITY_TEST}: " + ("; ".join(l for l in (q.stdout + q.stderr).splitlines()
                                                        if l.startswith("FAIL")) or tail))
    fa, cand = GC_PARITY_SCENE
    if (ROOT / "artifacts" / f"homm3_{fa}_full3d" / "candidates" / cand).is_dir():
        import os
        q = subprocess.run([sys.executable, str(TS / GC_PARITY_TEST), "--quick"], cwd=str(ROOT), capture_output=True,
                           text=True, timeout=1200,
                           env={**os.environ, "TOWN_FULL3D_FACTION": fa, "TOWN_FULL3D_CANDIDATE": cand})
        tail = ((q.stdout + q.stderr).strip().splitlines() or ["failed"])[-1]
        print(f"{GC_PARITY_TEST}: {tail}")
        if q.returncode:
            errs.append(f"{GC_PARITY_TEST}: {tail}")
    else:
        print(f"{GC_PARITY_TEST}: SKIP {fa}/{cand} is not staged here")
    for p in sorted(RECIPES.glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        q = subprocess.run([sys.executable, str(RECIPE), "verify", str(p)], cwd=str(ROOT), capture_output=True,
                           text=True, timeout=900)
        out = (q.stdout + q.stderr).strip().splitlines()
        tail = out[-1] if out else ""
        print(f"{p.name}: {tail}")
        if q.returncode:
            errs.append(f"{p.name} ({rec.get('faction')}/{rec.get('candidate')}): {tail}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--static-only", action="store_true")
    a = ap.parse_args()
    errs = static_errors()
    if not a.static_only:
        errs += staged_errors()
    for e in errs:
        print("FAIL", e)
    if errs:
        return 1
    print("town zero-streak contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
