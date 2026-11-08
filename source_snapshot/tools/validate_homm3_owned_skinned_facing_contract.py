"""Owned skinned units must face the way native Olden Era units face.

Native unit prefabs put the mesh along the first child's +Z and the presentation yaw on that child
(scale_roll / Scale_roll / Scale_roll_pos): +90 on 165 of 176 battle prefabs, an authored per-unit yaw
toward the camera on <unit>_map prefabs (SquadDrawer.Init never rotates the map prefab root).

Our owned-skinned prefab carries an "Orientation" child. The fleet asset convention: the idle-0 mesh faces
OwnedSkinnedBindFacingYaw = -60 (one hex side) inside Orientation - the capture/idle-0 lanes wrap their
fitted bind there, and the battle side heading (left 150 / right -30) has always compensated it. Every
plugin lane sets Orientation = native presentation yaw - (-60): battle (native +90 / -90), the adventure
map and vanilla-donor preview (the native model's scale_roll yaw), the synthetic preview (battle-prefab +90).

Default mode (OfflineUnlockMod BeforeBuild):
  * plugin source: the fleet constant, the rule, and its use in all four lanes (battle values unchanged);
  * every lab prefab under oldenera_factions/Assets/CustomUnits/homm3_lab/*/OwnedSkinned: Orientation yaw
    +90 with no tilt / mirror under an identity root, and the idle-0 limb-line forward inside Orientation
    within FLEET_TOL of -60. Lanes and units that sit elsewhere are named, with a reason, in
    tools/homm3_owned_skinned_facing_allowlist.json; an entry that no longer applies fails (the list only shrinks);
  * every built DEF-retarget delivery GLB (tools/homm3_def_retarget_delivery/*.json selections):
    Unit_Idle frame 0 faces glTF +Z within 45 degrees (that lane's own convention, recorded in the allowlist).
Bundle mode (--bundle-dir D --name-prefix P ..., slice / mocap payload gates):
  the same Orientation, lane-marker and bind-facing checks on the prefabs inside built or installed bundles.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
VISUALS = PLUGIN / "Homm3ImportVisuals.cs"
LAB_BUILDER = ROOT / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.DefRetarget.cs"
LAB_ROOT = ROOT / "oldenera_factions/Assets/CustomUnits/homm3_lab"
SELECTIONS = ROOT / "tools/homm3_def_retarget_delivery"
ALLOWLIST = ROOT / "tools/homm3_owned_skinned_facing_allowlist.json"
ORIENTATION = "Orientation"
MARKER = "__homm3_skinned_battle_lane__"
NATIVE_YAW = 90.0
YAW_TOL = 0.5
GLB_FORWARD_TOL = 45.0
FLEET_BIND_YAW = -60.0  # Homm3ImportVisuals.OwnedSkinnedBindFacingYaw
FLEET_TOL = 45.0
DEF_LANE = "def_retarget"
# Limb pairs that define an idle-0 forward (the body's left-right line x up), first match wins. A mount's
# thighs outrank the rider's; Bip01 thighs cover the native-donor quadrupeds; arms cover the DEF elementals.
LIMB_PAIRS = (
    ("mount:Bip01_L_Thigh", "mount:Bip01_R_Thigh"),
    ("mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"),
    ("rider:mixamorig:LeftUpLeg", "rider:mixamorig:RightUpLeg"),
    ("Bip01_L_Thigh", "Bip01_R_Thigh"),
    ("LeftUpLeg", "RightUpLeg"),
    ("LeftArm", "RightArm"),
)


def yaw_pitch_roll(q) -> tuple[float, float]:
    """(yaw of the rotated +Z in degrees, tilt of the rotated +Y from vertical in degrees)."""
    x, y, z, w = q
    fwd = (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y))
    up = (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w))
    return math.degrees(math.atan2(fwd[0], fwd[2])), math.degrees(math.acos(max(-1.0, min(1.0, up[1]))))


def check_orientation(label: str, q, scale, errors: list[str]) -> str:
    yaw, tilt = yaw_pitch_roll(q)
    if abs(((yaw - NATIVE_YAW) + 180) % 360 - 180) > YAW_TOL or tilt > YAW_TOL:
        errors.append(f"{label}: Orientation yaw {yaw:.1f} tilt {tilt:.1f}; the native unit-prefab convention is yaw {NATIVE_YAW:.0f}, no tilt")
    if min(scale) <= 0:
        errors.append(f"{label}: Orientation scale {tuple(scale)} mirrors the unit")
    return f"yaw={yaw:.1f}"


# ---- plugin / builder source -------------------------------------------------------------------

def method_body(text: str, signature: str) -> str:
    i = text.find(signature)
    if i < 0:
        return ""
    j = text.index("{", i)
    depth = 0
    for k in range(j, len(text)):
        depth += {"{": 1, "}": -1}.get(text[k], 0)
        if depth == 0:
            return text[j:k + 1]
    return ""


def check_sources(errors: list[str]) -> None:
    visuals = VISUALS.read_text(encoding="utf-8-sig")
    if "internal const float OwnedSkinnedBindFacingYaw = -60f;" not in visuals:
        errors.append("Homm3ImportVisuals.cs: OwnedSkinnedBindFacingYaw must be -60f (the fleet bind convention the battle heading was tuned on)")
    if "internal const float NativeBattleScaleRollYaw = 90f;" not in visuals:
        errors.append("Homm3ImportVisuals.cs: NativeBattleScaleRollYaw must be 90f")
    rule = method_body(visuals, "internal static float OwnedSkinnedOrientationYawFor(")
    if "return nativePresentationYaw - OwnedSkinnedBindFacingYaw;" not in rule:
        errors.append("OwnedSkinnedOrientationYawFor must return the native presentation yaw minus OwnedSkinnedBindFacingYaw")
    facing = method_body(visuals, "internal static bool TryApplyOwnedSkinnedNativeModelFacing(")
    finder = method_body(visuals, "private static Transform FindNativeModelFacingNode(")
    if '"scale_roll", StringComparison.OrdinalIgnoreCase' not in finder:
        errors.append("FindNativeModelFacingNode no longer finds the native scale_roll child")
    if ("LogError" not in facing or "var yaw = OwnedSkinnedOrientationYawFor(nativeYaw);" not in facing
            or "Quaternion.Euler(0f, yaw, 0f)" not in facing):
        errors.append("TryApplyOwnedSkinnedNativeModelFacing must fail closed (LogError) and set the fleet rule's pure yaw")
    map_body = method_body(visuals, "static void FinishOwnedSkinnedAdventureMapPresentation(")
    m = map_body.find('TryApplyOwnedSkinnedNativeModelFacing(shell, visual, "map", log)')
    if m < 0 or m < map_body.find("AlignOwnedSkinnedFeetToDonor(null, visual)"):
        errors.append("map lane: FinishOwnedSkinnedAdventureMapPresentation must apply the shell's scale_roll yaw after the fits")
    prev = method_body(visuals, "internal static void PlaceOwnedSkinnedPreviewAtVanillaMeshPose(")
    p = prev.find('TryApplyOwnedSkinnedNativeModelFacing(vanillaDonor, skinned, "preview", log)')
    if p < 0 or p > prev.find("AlignOwnedSkinnedPreviewToDonorCenter(vanillaDonor, skinned)") or p < prev.find("EnsureOwnedSkinnedDeliveryOrientation(skinned, log)"):
        errors.append("preview lane: PlaceOwnedSkinnedPreviewAtVanillaMeshPose must apply the vanilla model's scale_roll yaw after zeroing and before centering")
    q = prev.find('TryApplyOwnedSkinnedBattlePrefabFacing(skinned, "preview-synthetic", log)')
    if q < 0 or q > prev.rfind("AlignOwnedSkinnedPreviewToParentSlot(skinned)"):
        errors.append("synthetic preview lane: the no-donor branch must apply the battle-prefab facing before centering on the slot")
    synth = method_body(visuals, "internal static bool TryApplyOwnedSkinnedBattlePrefabFacing(")
    if "OwnedSkinnedOrientationYawFor(NativeBattleScaleRollYaw)" not in synth or "LogError" not in synth:
        errors.append("TryApplyOwnedSkinnedBattlePrefabFacing must fail closed and set OwnedSkinnedOrientationYawFor(NativeBattleScaleRollYaw)")
    side = method_body(visuals, "internal static bool TryApplyOwnedSkinnedSideFacing(")
    if "OwnedSkinnedOrientationYawFor(leftSide ? NativeBattleScaleRollYaw : -NativeBattleScaleRollYaw)" not in side:
        errors.append("battle lane: side facing must be OwnedSkinnedOrientationYawFor(+/-NativeBattleScaleRollYaw) = left 150 / right -30 (unchanged)")
    builder = LAB_BUILDER.read_text(encoding="utf-8-sig")
    if "private const float DefRetargetOrientationYaw = 90f;" not in builder:
        errors.append("DefRetarget lab builder: DefRetargetOrientationYaw must be 90f (native battle-prefab scale_roll yaw)")
    bake = builder.find("instance.transform.Find(DefRetargetOrientationName).localRotation = Quaternion.Euler(0f, DefRetargetOrientationYaw, 0f);")
    save = builder.find("PrefabUtility.SaveAsPrefabAsset(instance, prefabPath, out saved);")
    if bake < 0 or save < 0 or bake > save:
        errors.append("DefRetarget lab builder: Orientation yaw must be baked onto the prefab instance before SaveAsPrefabAsset")
    if "private const float DefRetargetBindFacingYaw = -60f;" not in builder:
        errors.append("DefRetarget lab builder: DefRetargetBindFacingYaw must be -60f (the fleet bind convention)")
    wrap = builder.find("ApplyDefRetargetBindFacing(instance.transform.Find(DefRetargetOrientationName), glbTopLevel);")
    vfx = builder.find("built = BuildVfxNodes(instance, body, plan, hasAtlas, vfxRoot, spec.labSid);")
    if wrap < 0 or vfx < 0 or wrap < vfx or wrap > save:
        errors.append("DefRetarget lab builder: the -60 bind wrap must be applied after the VFX nodes are built and before SaveAsPrefabAsset")
    if "which would overwrite the bind facing wrap" not in builder:
        errors.append("DefRetarget lab builder: clips animating a top-level GLB node's pose must be refused")
    # Attack facing turns the battle root so the *body* faces the target. The lane marker is +90 on both sides,
    # while the body frame differs by side (left 150 / right -30 on Orientation); a marker-based turn left
    # right-side attackers facing away (skinnedDelta -180).
    body_fwd = method_body(visuals, "private static bool TryGetOwnedSkinnedBodyForwardInRoot(")
    if ("OwnedSkinnedBodyRotation(node)" not in body_fwd or "FindOwnedSkinnedSideFacingNode(battleRoot)" not in body_fwd
            or "Quaternion.Inverse(battleRoot.transform.rotation)" not in body_fwd):
        errors.append("TryGetOwnedSkinnedBodyForwardInRoot must read the body frame (OwnedSkinnedBodyRotation of the side-facing node) in the battle root's space")
    for sig in ("internal static bool TryApplySkinnedBattleTargetFacing(", "internal static float MeasureSkinnedTargetFacingDelta("):
        body = method_body(visuals, sig)
        if "TryGetOwnedSkinnedBodyForwardInRoot(battleRoot" not in body or "SkinnedBattleLaneMarkerName" in body:
            errors.append(f"{sig.split('(')[0].split()[-1]} must take the target-facing forward from the body frame, never the lane marker")
    apply_body = method_body(visuals, "internal static bool TryApplySkinnedBattleTargetFacing(")
    if "LogError" not in apply_body:
        errors.append("TryApplySkinnedBattleTargetFacing must fail closed (LogError) when the body frame is missing")
    body_rot = method_body(visuals, "internal static Quaternion OwnedSkinnedBodyRotation(")
    if "Quaternion.Euler(0f, OwnedSkinnedBindFacingYaw, 0f)" not in body_rot:
        errors.append("OwnedSkinnedBodyRotation must turn Orientation by OwnedSkinnedBindFacingYaw")
    fx = (ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3MeshFx.cs").read_text(encoding="utf-8-sig")
    look = (ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3UnitLookVfxRuntime.cs").read_text(encoding="utf-8-sig")
    if "Homm3ImportVisuals.OwnedSkinnedBodyRotation(slot.Orientation)" not in fx:
        errors.append("Homm3MeshFx body-orient basis must be the body frame (OwnedSkinnedBodyRotation), not Orientation")
    if "Homm3ImportVisuals.OwnedSkinnedBodyRotation(_orientation) * Vector3.forward" not in look:
        errors.append("Homm3UnitLookVfxRuntime mirror must read the body forward (OwnedSkinnedBodyRotation), not Orientation.forward")


# ---- idle-0 bind facing (fleet convention) -------------------------------------------------------

def _qmat(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def bind_forward_yaw(nodes: dict, orientation) -> tuple[float | None, str | None]:
    """Idle-0 (rest) limb-line forward yaw in Unity degrees inside Orientation.

    nodes: key -> (name, parent key or None, (px,py,pz), (qx,qy,qz,qw), (sx,sy,sz)). Unity is left-handed:
    a character facing +Z has its right side on +X, so forward = (right - left) x up = (-dz, 0, dx).
    The lab prefabs' Hips sit at identity at idle frame 0, so the rest pose is the idle-0 pose.
    """
    by_name: dict = {}
    for key, node in nodes.items():
        by_name.setdefault(node[0], []).append(key)

    def chain_pos(key):
        p = [0.0, 0.0, 0.0]
        while key != orientation:
            if key is None or key not in nodes:
                return None
            _, parent, t, q, sc = nodes[key]
            R = _qmat(q)
            p = [sum(R[r][c] * sc[c] * p[c] for c in range(3)) + t[r] for r in range(3)]
            key = parent
        return p

    def pos(name):
        # A bundle holds several prefabs with the same bone names; use the copy under this Orientation.
        for key in by_name.get(name, ()):
            p = chain_pos(key)
            if p is not None:
                return p
        return None

    for left, right in LIMB_PAIRS:
        a, b = pos(left), pos(right)
        if a is None or b is None:
            continue
        dx, dz = b[0] - a[0], b[2] - a[2]
        return math.degrees(math.atan2(-dz, dx)), left
    # Limbless fliers (serpent fly): the same wing-root pair the delivery-GLB check measures (glb_idle0_forward).
    for left in sorted(n for n in by_name if n.startswith("Wing") and n.endswith("L_00") and n[:-4] + "R_00" in by_name):
        a, b = pos(left), pos(left[:-4] + "R_00")
        if a is None or b is None:
            continue
        dx, dz = b[0] - a[0], b[2] - a[2]
        return math.degrees(math.atan2(-dz, dx)), left
    return None, None


def load_allowlist(errors: list[str]) -> dict:
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    if data.get("schema") != "homm3_owned_skinned_facing_allowlist.v1":
        errors.append(f"{ALLOWLIST.name}: unexpected schema {data.get('schema')!r}")
    for key in ("lanes", "units"):
        for sid, row in (data.get(key) or {}).items():
            if not str(row.get("reason", "")).strip():
                errors.append(f"{ALLOWLIST.name}: {key}.{sid} has no reason")
    return data


def _off(yaw: float, want: float) -> float:
    return abs(((yaw - want) + 180) % 360 - 180)


def check_bind_facing(label: str, sid: str, lane: str | None, yaw: float | None, pair: str | None,
                      allow: dict, seen: dict, errors: list[str], notes: list[str]) -> None:
    lane_row = (allow.get("lanes") or {}).get(lane) if lane else None
    seen.setdefault(sid, []).append((yaw, lane))
    shown = None if yaw is None else round(yaw, 1)
    if lane_row:
        want = float(lane_row["bindFacingYaw"])
        tol = float(lane_row.get("tolerance", FLEET_TOL))
        if yaw is None or _off(yaw, want) > tol:
            errors.append(f"{label}: {lane} lane bind forward {shown} is not within {tol:.0f} of that lane's recorded {want:.0f}")
        notes.append(f"{label}: bind forward {shown} ({pair}; lane {lane})")
        return
    ok = yaw is not None and _off(yaw, FLEET_BIND_YAW) <= FLEET_TOL
    if not ok and sid not in (allow.get("units") or {}):
        what = "has no measurable left/right limb pair" if yaw is None else f"idle-0 forward {yaw:.1f} ({pair})"
        errors.append(f"{label}: {what}; the fleet convention is {FLEET_BIND_YAW:.0f} +/- {FLEET_TOL:.0f} inside Orientation "
                      f"(fix the asset, or record the unit with a reason in {ALLOWLIST.name})")
    notes.append(f"{label}: bind forward {shown} ({pair})")


def check_allowlist_current(allow: dict, seen: dict, errors: list[str], *, complete: bool) -> None:
    """complete=True (lab mode) also refuses entries that name no current prefab."""
    for sid in (allow.get("units") or {}):
        rows = seen.get(sid)
        if not rows:
            if complete:
                errors.append(f"{ALLOWLIST.name}: units.{sid} names no owned skinned lab prefab; remove it")
            continue
        if all(y is not None and _off(y, FLEET_BIND_YAW) <= FLEET_TOL for y, _ in rows):
            errors.append(f"{ALLOWLIST.name}: units.{sid} now meets the fleet convention; remove it")
        if any(lane and lane in (allow.get("lanes") or {}) for _, lane in rows):
            errors.append(f"{ALLOWLIST.name}: units.{sid} is covered by its lane entry; remove it")


# ---- lab prefabs (Unity YAML) --------------------------------------------------------------------

def vec(s: str) -> dict:
    return {k: float(v) for k, v in re.findall(r"(\w+): ([-\d.eE]+)", s)}


def parse_prefab(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    docs = re.split(r"^--- !u!(\d+) &(-?\d+).*$", text, flags=re.M)
    names, transforms = {}, {}
    for i in range(1, len(docs), 3):
        cls, fid, body = docs[i], docs[i + 1], docs[i + 2]
        if cls == "1":
            m = re.search(r"m_Name: (.*)", body)
            names[fid] = m.group(1).strip() if m else "?"
        elif cls == "4":
            transforms[fid] = {
                "go": re.search(r"m_GameObject: \{fileID: (-?\d+)\}", body).group(1),
                "father": re.search(r"m_Father: \{fileID: (-?\d+)\}", body).group(1),
                "rot": vec(re.search(r"m_LocalRotation: \{([^}]*)\}", body).group(1)),
                "pos": vec(re.search(r"m_LocalPosition: \{([^}]*)\}", body).group(1)),
                "scl": vec(re.search(r"m_LocalScale: \{([^}]*)\}", body).group(1)),
            }
    return names, transforms


def check_lab_prefabs(errors: list[str], notes: list[str]) -> None:
    prefabs = sorted(glob.glob(str(LAB_ROOT / "*" / "OwnedSkinned" / "*owned_skinned.prefab")))
    if not prefabs:
        errors.append(f"no owned skinned lab prefabs under {LAB_ROOT}")
        return
    allow = load_allowlist(errors)
    seen: dict = {}
    checked = 0
    for p in prefabs:
        path = Path(p)
        sid = path.parents[1].name
        def_lane = (path.parent / "owned_skinned_def_retarget_report.json").is_file()
        names, trs = parse_prefab(path)
        roots = [k for k, t in trs.items() if t["father"] == "0"]
        orient = [k for k, t in trs.items() if names.get(t["go"]) == ORIENTATION]
        if not orient:
            if def_lane:
                errors.append(f"{sid}: def_retarget lab prefab has no Orientation node")
            continue
        checked += 1
        o = trs[orient[0]]
        if len(roots) != 1 or o["father"] != roots[0]:
            errors.append(f"{sid}: Orientation is not a direct child of the prefab root")
        r = trs[roots[0]]["rot"] if len(roots) == 1 else {}
        if r and (abs(r["x"]) + abs(r["y"]) + abs(r["z"]) > 1e-4):
            errors.append(f"{sid}: prefab root carries a rotation {r}; the facing belongs on Orientation")
        q = o["rot"]
        check_orientation(f"{sid} lab prefab", (q["x"], q["y"], q["z"], q["w"]), (o["scl"]["x"], o["scl"]["y"], o["scl"]["z"]), errors)
        nodes = {k: (names.get(t["go"], "?"), None if t["father"] == "0" else t["father"],
                     (t["pos"]["x"], t["pos"]["y"], t["pos"]["z"]),
                     (t["rot"]["x"], t["rot"]["y"], t["rot"]["z"], t["rot"]["w"]),
                     (t["scl"]["x"], t["scl"]["y"], t["scl"]["z"])) for k, t in trs.items()}
        yaw, pair = bind_forward_yaw(nodes, orient[0])
        check_bind_facing(f"{sid} lab prefab", sid, DEF_LANE if def_lane else None, yaw, pair, allow, seen, errors, notes)
    check_allowlist_current(allow, seen, errors, complete=True)
    notes.append(f"lab prefabs with Orientation checked: {checked} of {len(prefabs)}")


# ---- delivered DEF-retarget GLBs -----------------------------------------------------------------

def glb_idle0_forward(path: Path | bytes) -> tuple[float, float, float] | None:
    """Idle frame 0 forward (x, 0, z) on the XZ plane, or None when no rule can measure the rig (fail closed:
    callers refuse None). See glb_idle0_forward_rule for the rule classes. `path` may be the GLB's bytes (an
    in-memory delivery stage's output, deyaw_glb.deyaw_bytes)."""
    return glb_idle0_forward_rule(path)[0]


# Facing rules, one per rig class, first match wins (2026-09-27):
#   lateralPair  LeftArm/RightArm, LeftUpLeg/RightUpLeg or LeftShoulder/RightShoulder: forward = up x (left - right)
#   wingPair     no limb pair; a Wing*L_00 / Wing*R_00 pair (dragonfly line): the same cross product, first pair by name
#   headAxis     no pair at all (serpents, sandworms): the Head bone's own +Y (the bone's direction) on XZ, only when at
#                least HEAD_AXIS_MIN_HORIZONTAL of it is horizontal. Hips->Head is not used: a serpent's idle curls the
#                neck back over the body (sea serpent Spine->Neck reads 175 deg off), while the head keeps pointing
#                where the DEF's head points (sea serpent / haspid / abyss serpent / 4 sandworms: 0 .. 8 deg).
# A rig none of them measures returns (None, None, why): unmeasurable is a failure, never a pass.
HEAD_AXIS_MIN_HORIZONTAL = 0.5


def glb_idle0_forward_rule(path: Path | bytes) -> tuple[tuple[float, float, float] | None, str | None, str]:
    """(forward, rule, note) for a GLB's Unit_Idle frame 0 (a path or the GLB's bytes); forward None when unmeasurable."""
    b = bytes(path) if isinstance(path, (bytes, bytearray)) else Path(path).read_bytes()
    jl = struct.unpack("<I", b[12:16])[0]
    js = json.loads(b[20:20 + jl])
    bin0 = 20 + jl + 8

    def first(i):
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        w = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[a["type"]]
        return struct.unpack_from("<" + "f" * w, b, bin0 + bv.get("byteOffset", 0) + a.get("byteOffset", 0))

    local = {i: [n.get("translation", [0, 0, 0]), n.get("rotation", [0, 0, 0, 1]), n.get("scale", [1, 1, 1])]
             for i, n in enumerate(js["nodes"])}
    anim = next((a for a in js.get("animations", []) if a.get("name") == "Unit_Idle"), None)
    if anim is None:
        return None, None, "no Unit_Idle clip"
    for ch in anim["channels"]:
        path_ = ch["target"]["path"]
        if path_ in ("translation", "rotation", "scale"):
            local[ch["target"]["node"]][("translation", "rotation", "scale").index(path_)] = list(first(anim["samplers"][ch["sampler"]]["output"]))
    parent = {c: i for i, n in enumerate(js["nodes"]) for c in n.get("children", [])}

    def mat(i):
        t, (x, y, z, w), s = local[i]
        R = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
             [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
             [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        return [[R[r][c] * s[c] for c in range(3)] + [t[r]] for r in range(3)] + [[0, 0, 0, 1]]

    def mul(A, B):
        return [[sum(A[r][k] * B[k][c] for k in range(4)) for c in range(4)] for r in range(4)]

    cache = {}

    def world(i):
        if i not in cache:
            cache[i] = mul(world(parent[i]), mat(i)) if i in parent else mat(i)
        return cache[i]

    idx = {n.get("name"): i for i, n in enumerate(js["nodes"])}
    rule = None
    left = next((idx[n] for n in ("LeftArm", "LeftUpLeg", "LeftShoulder") if n in idx), None)
    right = next((idx[n] for n in ("RightArm", "RightUpLeg", "RightShoulder") if n in idx), None)
    if left is not None and right is not None:
        rule = "lateralPair"
    else:
        wings = sorted(n for n in idx if n and n.startswith("Wing") and n.endswith("L_00") and n[:-4] + "R_00" in idx)
        if wings:
            left, right, rule = idx[wings[0]], idx[wings[0][:-4] + "R_00"], "wingPair"
    if rule:
        L, R = world(left), world(right)
        lx, lz = L[0][3] - R[0][3], L[2][3] - R[2][3]
        if math.hypot(lx, lz) < 1e-6:
            return None, None, f"{rule}: the pair sits on one point"
        # glTF is right-handed, Y up: a character facing +Z has its left side on +X, so forward = up x left.
        return (-lz, 0.0, lx), rule, ""
    if "Head" in idx:
        H = world(idx["Head"])
        y = [H[0][1], H[1][1], H[2][1]]
        n = math.sqrt(sum(c * c for c in y))
        hor = math.hypot(y[0], y[2]) / max(n, 1e-12)
        if hor < HEAD_AXIS_MIN_HORIZONTAL:
            return None, None, f"headAxis: Head points {hor:.2f} horizontal (< {HEAD_AXIS_MIN_HORIZONTAL}); unmeasurable"
        return (y[0], 0.0, y[2]), "headAxis", f"horizontal share {hor:.2f}"
    return None, None, "no limb pair, no wing pair, no Head bone"


def check_delivery_glbs(errors: list[str], notes: list[str]) -> None:
    for sel_path in sorted(SELECTIONS.glob("*.json")):
        sel = json.loads(sel_path.read_text(encoding="utf-8"))
        if sel.get("schema") != "homm3_def_retarget_delivery_selection.v1":
            continue
        out = ROOT / sel["out"]
        for row in sel["units"]:
            glb = out / row["labSid"] / "delivered_idle_retimed.glb"
            if not glb.is_file():
                notes.append(f"{sel_path.stem}/{row['labSid']}: not built yet (no {glb.name})")
                continue
            f = glb_idle0_forward(glb)
            if f is None:
                errors.append(f"{sel_path.stem}/{row['labSid']}: cannot measure Unit_Idle frame-0 forward (no Unit_Idle or no Left/Right limb nodes)")
                continue
            ang = math.degrees(math.atan2(f[0], f[2]))
            if abs(ang) > GLB_FORWARD_TOL:
                errors.append(f"{sel_path.stem}/{row['labSid']}: Unit_Idle frame 0 faces glTF yaw {ang:.1f}; the lane requires +Z within {GLB_FORWARD_TOL:.0f}")
            notes.append(f"{sel_path.stem}/{row['labSid']}: idle-0 glTF yaw {ang:.1f}")


# ---- bundles -------------------------------------------------------------------------------------

def check_bundles(bundle_dir: Path, prefixes: list[str], errors: list[str], notes: list[str]) -> None:
    import UnityPy

    files = sorted(p for p in bundle_dir.iterdir() if p.is_file() and not p.suffix and any(p.name == x or (x.endswith("_") and p.name.startswith(x)) for x in prefixes))
    if not files:
        errors.append(f"no bundles in {bundle_dir} match {prefixes}")
    allow = load_allowlist(errors)
    seen: dict = {}
    for f in files:
        env = UnityPy.load(str(f))
        nodes: dict = {}
        for o in env.objects:
            if o.type.name != "Transform":
                continue
            t = o.read()
            q, sc, ps = t.m_LocalRotation, t.m_LocalScale, t.m_LocalPosition
            nodes[o.path_id] = (t.m_GameObject.read().m_Name, t.m_Father.path_id or None,
                                (ps.x, ps.y, ps.z), (q.x, q.y, q.z, q.w), (sc.x, sc.y, sc.z))
        roots = [k for k, n in nodes.items() if n[1] is None]
        prefabs = [k for k in roots if any(n[1] == k and n[0] == MARKER for n in nodes.values())]
        if not prefabs:
            errors.append(f"{f.name}: no owned skinned prefab (lane marker) found")
        for root in prefabs:
            label = f"{f.name}:{nodes[root][0]}"
            kids = {n[0]: k for k, n in nodes.items() if n[1] == root}
            if ORIENTATION not in kids:
                errors.append(f"{label}: no Orientation child")
                continue
            orient = kids[ORIENTATION]
            o = nodes[orient]
            yaw_note = check_orientation(label, o[3], o[4], errors)
            myaw, _ = yaw_pitch_roll(nodes[kids[MARKER]][3])
            if abs(myaw - NATIVE_YAW) > YAW_TOL:
                errors.append(f"{label}: lane marker yaw {myaw:.1f} != {NATIVE_YAW:.0f}")
            yaw, pair = bind_forward_yaw(nodes, orient)
            lane = DEF_LANE if any(n[1] == orient and n[0].endswith("_Rig") for n in nodes.values()) else None
            check_bind_facing(label, bundle_lab_sid(f.name), lane, yaw, pair, allow, seen, errors, notes)
            notes.append(f"{label}: Orientation {yaw_note}")
    check_allowlist_current(allow, seen, errors, complete=False)


def bundle_lab_sid(bundle_name: str) -> str:
    """custom_units_<faction>_<labSid> -> labSid (lab sids start with h3_, hota_ or toa_)."""
    m = re.search(r"(h3_|hota_|toa_).*$", bundle_name)
    return m.group(0) if m else bundle_name


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle-dir", type=Path)
    ap.add_argument("--name-prefix", action="append", default=[],
                    help="exact bundle name, or a family prefix ending in '_' (custom_units_h3_mage must not select custom_units_h3_mage_upg_alt)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    errors: list[str] = []
    notes: list[str] = []
    check_sources(errors)
    if args.bundle_dir:
        check_bundles(args.bundle_dir, args.name_prefix, errors, notes)
    else:
        check_lab_prefabs(errors, notes)
        check_delivery_glbs(errors, notes)
    if args.verbose or errors:
        for n in notes:
            print("  " + n)
    if errors:
        for e in errors:
            print("FAIL " + e)
        return 1
    print(f"homm3 owned skinned facing contract OK ({len(notes)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
