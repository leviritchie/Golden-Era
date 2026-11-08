"""stride_match_glb.py: the plant transform must plant a shuffling walk's feet, keep other clips intact, refuse
flyers, and every stride-matched GLB on disk must still pass `check` (the foot-slip regression gate).

    python -m unittest tools/homm3_def_retarget_delivery/test_stride_match_glb.py

The synthetic biped runs everywhere; the on-disk check is skipped where artifacts/homm3_stride_match is absent.
Proof tier: generated artifact.
"""
from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stride_match_glb as S  # noqa: E402
import move_lowpass_glb as LP  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "artifacts/homm3_stride_match"
L = 7 / 12            # a DEF Move: keys at 1/12 .. 7/12 s, the last a copy of the first


def qx(a):
    return [float(np.sin(a / 2)), 0.0, 0.0, float(np.cos(a / 2))]


def synth_glb(lift_move: float = 0.0, amp: float = 0.12, paw: float | None = None, shin=None, hem=None) -> bytes:
    """Biped: Hips (0.5 up) with two hip-knee-ankle legs of 0.45; skinned points at the feet and at 1.0 (height 1).
    Unit_Move shuffles in place (thigh +-amp rad, some knee bend); Unit_Idle stands.
    paw: also hang a humanoid-rigged quadruped's front legs (LeftArm/RightArm chains, held still) whose hand joints
    sit 0.2 up -- above the legs' floor band -- with one skinned paw point each at this height.
    shin: also skin one point per leg to its shin (LeftLeg / RightLeg) at this rest position (x mirrored for the right).
    hem: also skin one point to Hips at this rest position (a robe hem that rides with the pelvis)."""
    names = ["Root", "Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot", "Body"]
    tr = [[0, 0, 0], [0, 0.5, 0], [0.1, 0, 0], [0, -0.22, 0], [0, -0.23, 0], [-0.1, 0, 0], [0, -0.22, 0],
          [0, -0.23, 0], [0, 0, 0]]
    kids = {0: [1], 1: [2, 5], 2: [3], 3: [4], 5: [6], 6: [7]}
    if paw is not None:
        names += ["LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand"]
        tr += [[0.1, 0, 0.3], [0, -0.15, 0], [0, -0.15, 0], [-0.1, 0, 0.3], [0, -0.15, 0], [0, -0.15, 0]]
        kids.update({1: [2, 5, 9, 12], 9: [10], 10: [11], 12: [13], 13: [14]})
    nodes = [{"name": n, "translation": tr[i], **({"children": kids[i]} if i in kids else {})}
             for i, n in enumerate(names)]
    nodes[0]["children"] = [1]
    nodes[8] = {"name": "Body", "mesh": 0, "skin": 0}
    world = {0: np.zeros(3)}
    for p, cs in kids.items():
        for c in cs:
            world[c] = world[p] + np.array(tr[c])
    world[1] = np.array(tr[1])
    joints = [1, 2, 3, 4, 5, 6, 7] + ([9, 10, 11, 12, 13, 14] if paw is not None else [])
    ibm = []
    for j in joints:
        m = np.eye(4); m[:3, 3] = -world[j]
        ibm.append(m.T.reshape(-1))
    verts = np.array([[0, 1.0, 0], [0.1, 0.05, 0.05], [-0.1, 0.05, 0.05], [0.1, 0.05, -0.05], [-0.1, 0.05, -0.05]])
    jidx = np.array([[0, 0, 0, 0], [3, 0, 0, 0], [6, 0, 0, 0], [3, 0, 0, 0], [6, 0, 0, 0]], np.uint16)
    if paw is not None:
        verts = np.vstack([verts, [[0.1, paw, 0.3], [-0.1, paw, 0.3]]])
        jidx = np.vstack([jidx, np.array([[9, 0, 0, 0], [12, 0, 0, 0]], np.uint16)])
    if shin is not None:
        verts = np.vstack([verts, [shin, [-shin[0], shin[1], shin[2]]]])
        jidx = np.vstack([jidx, np.array([[2, 0, 0, 0], [5, 0, 0, 0]], np.uint16)])
    if hem is not None:
        verts = np.vstack([verts, [hem]])
        jidx = np.vstack([jidx, np.array([[0, 0, 0, 0]], np.uint16)])
    wts = np.tile([1.0, 0, 0, 0], (len(verts), 1))
    blobs, views, accs = [], [], []

    def add(arr, typ, comp=5126):
        arr = np.ascontiguousarray(arr, dtype="<f4" if comp == 5126 else "<u2")
        off = sum(len(b) for b in blobs)
        raw = arr.tobytes(); raw += b"\0" * ((4 - len(raw) % 4) % 4)
        blobs.append(raw)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes})
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": int(arr.shape[0]), "type": typ}
        if typ == "SCALAR":
            a["min"] = [float(arr.min())]; a["max"] = [float(arr.max())]
        if typ == "VEC3" and comp == 5126:
            a["min"] = arr.min(0).tolist(); a["max"] = arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    pos = add(verts, "VEC3"); ji = add(jidx, "VEC4", 5123); wi = add(wts, "VEC4"); ib = add(np.array(ibm), "MAT4")
    t = np.arange(1, 8) / 12.0
    ph = (t - t[0]) / (L - t[0]) * 2 * np.pi
    tin = add(t[:, None], "SCALAR")
    chans, samps = [], []

    def track(node, path, vals):
        samps.append({"input": tin, "output": add(np.array(vals), "VEC4" if path == "rotation" else "VEC3"),
                      "interpolation": "LINEAR"})
        chans.append({"sampler": len(samps) - 1, "target": {"node": node, "path": path}})

    for side, (up, knee) in ((0.0, (2, 3)), (np.pi, (5, 6))):
        track(up, "rotation", [qx(amp * np.sin(p + side)) for p in ph])
        track(knee, "rotation", [qx(-0.25 * max(0.0, np.sin(p + side + np.pi / 2))) for p in ph])
    track(1, "translation", [[0, 0.5 + lift_move + 0.01 * np.cos(2 * p), 0] for p in ph])
    move = {"name": "Unit_Move", "channels": chans, "samplers": samps}
    it = add(np.array([[0.0], [1.0]]), "SCALAR")
    idle = {"name": "Unit_Idle", "samplers": [{"input": it, "output": add(np.array([[0, 0.5, 0], [0, 0.5, 0]]), "VEC3")}],
            "channels": [{"sampler": 0, "target": {"node": 1, "path": "translation"}}]}
    bin_ = b"".join(blobs)
    js = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 8]}], "nodes": nodes,
          "meshes": [{"primitives": [{"attributes": {"POSITION": pos, "JOINTS_0": ji, "WEIGHTS_0": wi}}]}],
          "skins": [{"joints": joints, "inverseBindMatrices": ib}], "animations": [idle, move],
          "buffers": [{"byteLength": len(bin_)}], "bufferViews": views, "accessors": accs}
    j = json.dumps(js).encode(); j += b" " * ((4 - len(j) % 4) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(j) + len(bin_)) + struct.pack("<II", len(j), 0x4E4F534A) + j
            + struct.pack("<II", len(bin_), 0x004E4942) + bin_)


def clip_bytes(g: S.Glb, name: str):
    a = g.anim(name)
    return [(ch["target"]["node"], ch["target"]["path"], g.read(a["samplers"][ch["sampler"]]["input"]).tobytes(),
             g.read(a["samplers"][ch["sampler"]]["output"]).tobytes()) for ch in a["channels"]]


class PlantTransform(unittest.TestCase):
    def test_plants_a_shuffle(self):
        g = S.Glb(synth_glb())
        h = S.body_height(g)
        self.assertAlmostEqual(h, 0.95, places=2)
        ms = 0.6 * h / L * S.PLAYBACK          # ground moves 0.6 body heights per cycle, at world scale 1
        before = S.measure(g, ms, 1.0, h, flier=False)
        self.assertFalse(before["airborne"])
        self.assertGreater(before["slipRatio"], 0.5)
        idle = clip_bytes(g, S.IDLE)
        rep = S.plant_transform(g, ms / S.PLAYBACK, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)
        g2 = S.Glb(g.to_bytes())
        after = S.measure(g2, ms, 1.0, h, flier=False)
        self.assertLessEqual(after["slipRatio"], 0.25, after)
        self.assertLessEqual(after["slipRatio"], S.DEFAULT_MAX_SLIP)
        self.assertLessEqual(after["requiredOverActual"], S.MAX_RATIO, after)
        self.assertEqual(rep["cadence"], 1.0)
        self.assertEqual(clip_bytes(g2, S.IDLE), idle)
        for c in rep["chains"].values():
            self.assertEqual(c["phaseFrom"], "own")

    def test_planted_feet_stand_on_the_idle_floor(self):
        """A source Move that sinks below the Idle floor is planted back ON it (the lowest foot vertex), not at the
        source's own sunken contact height (h3_boar_rider hind hooves were left at -0.053 H)."""
        g = S.Glb(synth_glb(lift_move=-0.03))
        h = S.body_height(g)
        body = S.skin_body(g)
        t0 = np.array([float(g.read(g.anim(S.IDLE)["samplers"][0]["input"])[0, 0])])
        idle_floor = S.skin_heights(body, g.world(g.sample_local(S.IDLE, t0)), [0]).min()
        ms = 0.6 * h / L * S.PLAYBACK
        grid = np.linspace(0, S.Glb(g.to_bytes()).clip_end(S.MOVE), 48)
        src_low = S.skin_heights(body, g.world(g.sample_local(S.MOVE, grid)), range(len(grid))).min()
        self.assertLess(src_low, idle_floor - 0.02)
        rep = S.plant_transform(g, ms / S.PLAYBACK, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)
        g2 = S.Glb(g.to_bytes())
        grid = np.linspace(0, g2.clip_end(S.MOVE), 97)
        lows = S.skin_heights(S.skin_body(g2), g2.world(g2.sample_local(S.MOVE, grid)), range(len(grid))).min(1)
        self.assertGreater(lows.min(), idle_floor - 1e-3)
        self.assertLess(lows.min(), idle_floor + 1e-3)
        for c in rep["chains"].values():
            self.assertGreater(c["stanceFloorShiftOverHeight"], 0.02)

    def _clearance(self, g2, rep):
        """Per planted chain, the lowest height above the Idle floor (x H) of its limb at swing keys and of its sole at
        stance keys, on the written Move's key grid."""
        h = S.body_height(g2)
        body = S.skin_body(g2)
        t0 = np.array([float(g2.read(g2.anim(S.IDLE)["samplers"][0]["input"])[0, 0])])
        floor = S.skin_heights(body, g2.world(g2.sample_local(S.IDLE, t0)), [0]).min()
        grid = g2.key_grid(S.MOVE)
        hts = S.skin_heights(body, g2.world(g2.sample_local(S.MOVE, grid)), range(len(grid))) - floor
        phase = (grid - grid[0]) / (grid[-1] - grid[0])
        out = {}
        for c in S.chains_of(g2):
            r = rep["chains"][c["name"]]
            top = c["joints"][0]
            sub = [top] + [i for i in range(len(g2.nodes)) if S._descends(g2, i, top)]
            limb = (body["W"] * np.isin(body["J"], sub)).sum(1) >= 0.5
            sole = S.sole_of(g2, body, c)[1]
            stance = ((phase - r["phase0"]) % 1.0) < r["stanceFraction"]
            out[c["name"]] = (float(hts[~stance][:, limb].min()) / h, float(hts[stance][:, sole].min()) / h)
        return out

    def test_swing_clearance_keeps_planted_limbs_on_or_above_the_idle_floor(self):
        """A shin point behind the knee (a heel spur) swings below the Idle floor when the IK folds the leg; ground_glb
        would stand it on the floor and float the stride plant (P2: h3_hell_hound, hota_cove_swashbuckler). The plant
        raises such keys by their deficit: every planted limb stays on or above the floor while it swings, and every
        sole while it stands. Without the passes the same Move is refused, never delivered under the floor."""
        shin = [0.1, 0.06, -0.08]
        g = S.Glb(synth_glb(shin=shin))
        h = S.body_height(g)
        rate = 0.6 * h / L
        iters = S.CLEARANCE_ITERS
        try:
            S.CLEARANCE_ITERS = 0
            with self.assertRaisesRegex(SystemExit, "stays below the Idle floor after 0 clearance passes"):
                S.plant_transform(S.Glb(synth_glb(shin=shin)), rate, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION,
                                  S.DEFAULT_LIFT)
        finally:
            S.CLEARANCE_ITERS = iters
        rep = S.plant_transform(g, rate, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)
        g2 = S.Glb(g.to_bytes())
        for nm, (swing, stance) in self._clearance(g2, rep).items():   # the written keys are float32: 1e-4 H slack
            self.assertGreaterEqual(swing, -1e-4, nm)
            self.assertGreaterEqual(stance, -1e-4, nm)
            self.assertGreater(rep["chains"][nm]["clearanceRaiseMaxOverHeight"], 0.01, nm)
        self.assertLessEqual(S.measure(g2, rate * S.PLAYBACK, 1.0, h, flier=False)["slipRatio"], S.DEFAULT_MAX_SLIP)

    def test_body_clearance_lifts_the_pelvis_over_a_low_hem(self):
        """A hem point that rides with the pelvis, in a Move whose body sinks below Idle, goes under the floor the
        planted soles stand on; ground_glb would stand it there and lift the soles off (P2: hota_cove_sorceress robe
        hem -0.057 H). The plant lifts the pelvis at those keys and re-solves the legs: nothing but a swinging limb's
        own clearance is left under the floor, and the report records the lift. With no passes it is refused."""
        hem = [0.0, 0.08, 0.1]
        h = S.body_height(S.Glb(synth_glb(lift_move=-0.04, hem=hem)))
        rate = 0.6 * h / L
        iters = S.CLEARANCE_ITERS
        try:
            S.CLEARANCE_ITERS = 0
            with self.assertRaisesRegex(SystemExit, "body .* H at key"):
                S.plant_transform(S.Glb(synth_glb(lift_move=-0.04, hem=hem)), rate, S.DEFAULT_MAX_DROP, h,
                                  S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)
        finally:
            S.CLEARANCE_ITERS = iters
        g = S.Glb(synth_glb(lift_move=-0.04, hem=hem))
        rep = S.plant_transform(g, rate, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)
        self.assertGreater(rep["bodyClearance"]["pelvisLiftMaxOverHeight"], 0.0)
        g2 = S.Glb(g.to_bytes())
        body = S.skin_body(g2)
        t0 = np.array([float(g2.read(g2.anim(S.IDLE)["samplers"][0]["input"])[0, 0])])
        floor = S.skin_heights(body, g2.world(g2.sample_local(S.IDLE, t0)), [0]).min()
        grid = g2.key_grid(S.MOVE)
        hts = S.skin_heights(body, g2.world(g2.sample_local(S.MOVE, grid)), range(len(grid))) - floor
        self.assertGreaterEqual(float(hts[:, -1].min()) / h, -1e-4)    # the hem, last vertex
        for nm, (swing, stance) in self._clearance(g2, rep).items():
            self.assertGreaterEqual(swing, -1e-4, nm)
            self.assertGreaterEqual(stance, -1e-4, nm)

    def test_clearance_is_a_no_op_where_nothing_dips(self):
        """A Move whose planted limbs never go under the floor keeps the plant's keys bit for bit: the result equals
        the run with no clearance pass at all, and the report records no raise."""
        g = S.Glb(synth_glb())
        h = S.body_height(g)
        rate = 0.6 * h / L
        rep = S.plant_transform(g, rate, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)
        iters = S.CLEARANCE_ITERS
        try:
            S.CLEARANCE_ITERS = 0
            g0 = S.Glb(synth_glb())
            S.plant_transform(g0, rate, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)
        finally:
            S.CLEARANCE_ITERS = iters
        self.assertEqual(g.to_bytes(), g0.to_bytes())
        for c in rep["chains"].values():
            self.assertNotIn("clearanceRaiseMaxOverHeight", c)

    def test_zero_weight_foot_leaf_takes_its_sole_from_the_weighted_ancestor(self):
        """A contact leaf with no vertex weight (HorseXXHoof) plants on its lowest weighted ancestor's sole; a chain
        with no weighted bone at all is refused."""
        g = S.Glb(synth_glb(lift_move=-0.03))
        acc = g.json["meshes"][0]["primitives"][0]["attributes"]["JOINTS_0"]
        ji = g.read(acc).astype(int)
        ji[ji == 3] = 2       # the feet's vertices move to the shins (LeftLeg / RightLeg): the Foot bones own nothing
        ji[ji == 6] = 5
        a = g.json["accessors"][acc]
        bv = g.json["bufferViews"][a["bufferView"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        g.bin[off:off + ji.size * 2] = ji.astype("<u2").tobytes()
        h = S.body_height(g)
        ms = 0.6 * h / L * S.PLAYBACK
        rep = S.plant_transform(g, ms / S.PLAYBACK, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)
        self.assertEqual({c["soleFrom"] for c in rep["chains"].values()}, {"LeftLeg", "RightLeg"})
        g = S.Glb(synth_glb())
        ji = g.read(acc).astype(int)
        ji[ji != 0] = 0       # every vertex on Hips: no leg bone owns anything
        g.bin[off:off + ji.size * 2] = ji.astype("<u2").tobytes()
        with self.assertRaisesRegex(SystemExit, "no vertex is weighted to any bone of the chain"):
            S.plant_transform(g, ms / S.PLAYBACK, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)

    def test_a_planted_arm_chain_is_judged_by_its_sole(self):
        """A humanoid-rigged quadruped's front paw joint sits a chain-specific height above its sole
        (hota_factory_armadillo: paws 0.08-0.11 H, legs 0.03 H). measure() keeps the joint band for every chain, except
        that an arm chain apply planted is on the floor when its SOLE is: otherwise apply's own planted paws leave the
        scored set and the unit is refused at every maxDrop. An unplanted arm, or a planted paw held high, stays out."""
        g = S.Glb(synth_glb(paw=0.05))
        h = S.body_height(g)
        ms = 0.6 * h / L * S.PLAYBACK
        arms = frozenset(S.ARM_CHAINS)
        self.assertEqual(set(S.measure(g, ms, 1.0, h, flier=False)["grounded"]), {"LeftUpLeg", "RightUpLeg"})
        self.assertEqual(set(S.measure(g, ms, 1.0, h, flier=False, planted=arms)["grounded"]),
                         {"LeftUpLeg", "RightUpLeg", "LeftArm", "RightArm"})
        g = S.Glb(synth_glb(paw=0.15))
        self.assertEqual(set(S.measure(g, ms, 1.0, h, flier=False, planted=arms)["grounded"]),
                         {"LeftUpLeg", "RightUpLeg"})

    def test_short_legs_speed_the_clip_up_capped(self):
        g = S.Glb(synth_glb())
        h = S.body_height(g)
        ms = 2.5 * h / L * S.PLAYBACK          # far beyond a 0.45 leg's reach: cadence takes the rest, capped
        rep = S.plant_transform(g, ms / S.PLAYBACK, S.DEFAULT_MAX_DROP, h, S.DEFAULT_MAX_EXCURSION, S.DEFAULT_LIFT)
        self.assertEqual(rep["cadence"], S.DEFAULT_MAX_CADENCE)
        self.assertGreater(rep["cadenceNeeded"], S.DEFAULT_MAX_CADENCE)
        self.assertAlmostEqual(S.Glb(g.to_bytes()).clip_end(S.MOVE), L / S.DEFAULT_MAX_CADENCE, places=5)

    def test_flier_class_comes_from_the_table_not_the_move(self):
        g = S.Glb(synth_glb(lift_move=0.3))
        h = S.body_height(g)
        self.assertTrue(S.measure(g, 5.0, 1.0, h, flier=True)["airborne"])
        walker = S.measure(g, 5.0, 1.0, h, flier=False)     # a lifted walk is still a walk: measured and flagged
        self.assertFalse(walker["airborne"])
        self.assertTrue(walker["floorLiftFlag"])
        self.assertTrue(S.unit_flier("h3_royal_griffin"))
        self.assertFalse(S.unit_flier("h3_goblin"))
        with self.assertRaises(SystemExit):
            S.unit_flier("no_such_unit")

    def test_every_retarget_unit_is_classified(self):
        # fail closed: a unit config the flier table does not classify cannot be stride matched or frozen
        for cfg in sorted((ROOT / "tools/homm3_def_retarget/units").glob("*.json")):
            S.unit_flier(cfg.stem)
            S.unit_stride_exempt(cfg.stem)
            S.unit_stride_options(cfg.stem)     # strideMatch knobs parse (fail closed on anything else)
            LP.unit_lowpass_options(cfg.stem)   # moveLowPass parses, and only on fliers / strideExempt units

    def test_mount_legs_replace_the_riders_arms(self):
        names = ["Hips", "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
                 "FL1", "FL2", "FL3", "FR1", "FR2", "FR3", "RL1", "RL2", "RL3", "RR1", "RR2", "RR3"]

        class Rig:
            pass
        for keep, want in ((19, ["FL", "FR", "RL", "RR"]), (7, [])):      # arms alone are arms
            Rig.names = names[:keep]
            Rig.parent = {i: i - 1 for i, n in enumerate(Rig.names) if n[-1] in "23" or n.endswith(("ForeArm", "Hand"))}
            self.assertEqual([c["name"] for c in S.chains_of(Rig)], want)

    def test_necropolis_horse_legs_replace_the_riders_legs(self):
        legs = [f"Horse{s}{k}" for s in ("LF", "RF", "LH", "RH") for k in ("Up", "Low", "Hoof")]

        class Rig:
            names = ["Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot"] + legs
            parent = {1: 0, 2: 1, 3: 2, 4: 0, 5: 4, 6: 5}
        for i, n in enumerate(Rig.names):
            if n.endswith(("Low", "Hoof")):
                Rig.parent[i] = i - 1
        self.assertEqual([c["name"] for c in S.chains_of(Rig)], ["HorseLF", "HorseRF", "HorseLH", "HorseRH"])
        self.assertEqual(S.root_swing("HorseLF"), S.MOUNT_ROOT_SWING)
        Rig.names = [n for n in Rig.names if not n.endswith("Hoof")]      # an old build without the hoof leaf
        with self.assertRaises(SystemExit):
            S.chains_of(Rig)

    def test_stance_phase(self):
        n = 120
        ph = np.arange(n) / n
        z = np.where(ph < 0.6, 0.5 - ph / 0.6, -0.5 + (ph - 0.6) / 0.4)   # back for 60 %, forward for 40 %
        st = S.stance_phase(np.roll(z, 30), np.zeros(n))
        self.assertAlmostEqual(st["beta"], 0.6, delta=0.05)
        self.assertAlmostEqual(st["phase0"], 0.25, delta=0.05)
        self.assertEqual(S.paired("LeftUpLeg"), "RightUpLeg")
        self.assertEqual(S.paired("QFL"), "QFR")


class MoveSpeedSource(unittest.TestCase):
    """The ground speed a Move is matched to: an adopted game sid's normalized target, else the Core view row; never
    a speed derived from the clip's own stride (user, 2026-09-28: normalize speed, adjust stride)."""

    def test_adopted_sid_takes_the_normalized_target(self):
        from unittest.mock import patch
        table = {"h3_x_upg": {"class": "c", "targetMoveSpeed": 5.5, "refs": ["a", "b"], "reason": "r"}}
        with patch.object(S, "import_row", lambda u: {"gameUnitSids": ["h3_x_upg"]}),                 patch("validate_unit_move_speed_normalization_contract.adopted_targets", lambda: table),                 patch.object(S, "core_view_move_speed", lambda u, ids: self.fail("Core view read for an adopted sid")):
            src = S.move_speed_source("h3_lab_x")
        self.assertEqual((src["moveSpeed"], src["source"]), (5.5, "normalized:c"))

    def test_unadopted_sid_takes_the_core_view_row(self):
        from unittest.mock import patch
        with patch.object(S, "import_row", lambda u: {"gameUnitSids": ["h3_y"]}),                 patch("validate_unit_move_speed_normalization_contract.adopted_targets", lambda: {}),                 patch.object(S, "core_view_move_speed", lambda u, ids: 3.3):
            src = S.move_speed_source("h3_lab_y")
        self.assertEqual((src["moveSpeed"], src["source"]), (3.3, "coreView"))

    def test_conflicting_targets_are_refused(self):
        from unittest.mock import patch
        table = {"g1": {"class": "a", "targetMoveSpeed": 4.0, "refs": [], "reason": "r"},
                 "g2": {"class": "b", "targetMoveSpeed": 5.0, "refs": [], "reason": "r"}}
        with patch.object(S, "import_row", lambda u: {"gameUnitSids": ["g1", "g2"]}),                 patch("validate_unit_move_speed_normalization_contract.adopted_targets", lambda: table):
            with self.assertRaises(SystemExit):
                S.move_speed_source("lab")


class MoveLowPass(unittest.TestCase):
    def test_lowpass_scales_only_above_the_cutoff(self):
        g = S.Glb(synth_glb())
        idle = clip_bytes(g, S.IDLE)
        nodes = LP.lowpass_move(g, 0.2)
        g2 = S.Glb(g.to_bytes())
        self.assertEqual(clip_bytes(g2, S.IDLE), idle)
        self.assertTrue(nodes)
        a = g2.anim(S.MOVE)
        for ch in a["channels"]:
            if ch["target"]["path"] == "rotation":
                v = g2.read(a["samplers"][ch["sampler"]]["output"])
                self.assertTrue(np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5))


class OnDiskGate(unittest.TestCase):
    def test_stride_matched_glbs_pass_check(self):
        glbs = sorted(OUT.glob("*/*_stride_matched.glb")) if OUT.is_dir() else []
        if not glbs:
            self.skipTest(f"no stride-matched GLBs under {OUT}")
        for p in glbs:
            r = S.check_glb(p, S.DEFAULT_MAX_SLIP)
            self.assertTrue(r["ok"], r)
            self.assertLessEqual(r["slipRatio"], r["stampSlipRatioAfter"] + 1e-4, r)


class LegDeltas(unittest.TestCase):
    """strideMatch.legDeltas: DEF-frame leg turns after the plant, on the board's DEF grid, swing-weighted."""

    def turn_deg(self, g, before, bone, t):
        from scipy.spatial.transform import Rotation as Rot
        j = g.names.index(bone)
        q1 = g.sample_local(S.MOVE, np.array([t]))[j][1][0]
        return float(np.degrees((Rot.from_quat(before[j][1][0]).inv() * Rot.from_quat(q1)).magnitude()))

    def test_clip_start_is_the_boards(self):
        g = S.Glb(synth_glb())
        t0, t1 = S.move_clip_start(g)
        self.assertAlmostEqual(t0, 1 / 12, places=5); self.assertAlmostEqual(t1, L, places=5)
        # the board's rule (gltf_scene.clip_range): a stage that prepends a 0 s key to one channel moves nothing
        a = g.anim(S.MOVE); j = g.names.index("LeftLeg"); grid = np.concatenate([[0.0], g.key_grid(S.MOVE)])
        S.write_channels(g, a, grid, {(j, "rotation"): g.sample_local(S.MOVE, grid)[j][1]})
        self.assertAlmostEqual(S.move_clip_start(S.Glb(g.to_bytes()))[0], 1 / 12, places=5)

    def test_turn_lands_on_its_def_frame(self):
        g = S.Glb(synth_glb())
        t0, t1 = S.move_clip_start(g); n = 6; step = (t1 - t0) / n
        times = [t0 + i * step for i in range(n)]
        before = [g.sample_local(S.MOVE, np.array([t])) for t in times]
        rep = S.apply_leg_deltas(g, {"LeftLeg": [30.0, 0, 0, 0, 0, 0]}, [0, 0, 1])
        self.assertEqual(rep["clipStart"], round(t0, 5))
        g = S.Glb(g.to_bytes())
        self.assertAlmostEqual(self.turn_deg(g, before[0], "LeftLeg", times[0]), 30.0, delta=0.5)
        for i in (2, 3, 4):
            self.assertLess(self.turn_deg(g, before[i], "LeftLeg", times[i]), 0.5)

    def test_swing_power_leaves_the_stance_alone(self):
        g = S.Glb(synth_glb())
        t0, t1 = S.move_clip_start(g)
        ts = np.linspace(t0, t1, 7)
        before = [g.sample_local(S.MOVE, np.array([t])) for t in ts]
        S.apply_leg_deltas(g, {"LeftLeg": [30.0] * 4}, [0, 0, 1], {"LeftLeg": {"phase0": 0.0, "stanceFraction": 0.5}}, 1.0)
        g = S.Glb(g.to_bytes())
        for t, b in zip(ts, before):
            u = (t / t1) % 1.0
            d = self.turn_deg(g, b, "LeftLeg", t)
            if u < 0.5 - 0.1:
                self.assertLess(d, 0.5)
        mid = t1 * 0.75                                  # mid swing: sin(pi * 0.5) = full turn
        ref = S.Glb(synth_glb()).sample_local(S.MOVE, np.array([mid]))
        self.assertAlmostEqual(self.turn_deg(g, ref, "LeftLeg", mid), 30.0, delta=3.0)

    def test_swing_power_needs_the_chain_phase(self):
        g = S.Glb(synth_glb())
        with self.assertRaises(SystemExit):
            S.apply_leg_deltas(g, {"LeftLeg": [10.0] * 4}, [0, 0, 1], {}, 1.0)


if __name__ == "__main__":
    unittest.main()
