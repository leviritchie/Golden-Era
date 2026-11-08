"""Seed a unit's 27 Mixamo joint positions from Meshy's UniRig skeleton.

Usage: blender -b --factory-startup -P auto_joints.py -- <mesh_smartrigged.glb> <out.json>

UniRig's *weights* are unusable on these meshes, but its humanoid joint *layout* is
a reasonable seed. The mapping is structural, not by name:
  spine  = the chain from the root whose subtree climbs highest
  arms   = the two widest-reaching branches off the spine (one per side of x)
  legs   = root/low-spine chains ending in a near-horizontal foot segment near the
           ground (this rejects the vertical robe/skirt chains Meshy adds)
Anything that cannot be found is left out and reported; the result must be checked
with a skeleton overlay before use, and hand-edited where the seed is wrong.
"""
import bpy, sys, json
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=argv[0])
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
M = arm.matrix_world
H = lambda b: M @ b.head_local
Tl = lambda b: M @ b.tail_local

def chain_down(b):
    """Follow a single-child chain; stop at a branch point (fingers) or a leaf."""
    out = [b]
    while len(out[-1].children) == 1:
        out.append(out[-1].children[0])
    return out

def top_z(b):
    return max([Tl(b).z] + [top_z(c) for c in b.children])

def all_desc(b):
    yield b
    for c in b.children:
        yield from all_desc(c)

root = next(b for b in arm.data.bones if b.parent is None)
def find_spine_and_arms(central_first):
    spine = [root]
    while spine[-1].children:
        # stay on the centre line: a raised arm holding a weapon can out-climb the head
        central = [c for c in spine[-1].children if abs(H(c).x) < 0.04] if central_first else []
        nxt = max(central or spine[-1].children, key=top_z)
        if top_z(nxt) < Tl(spine[-1]).z - 0.05:
            break
        spine.append(nxt)
    spine_set = set(b.name for b in spine)
    cands = [c for s in spine for c in s.children if c.name not in spine_set and H(c).z > H(root).z + 0.15]
    arms = {}
    for side, sgn in (("Left", 1), ("Right", -1)):
        cs = [c for c in cands if sgn * max((H(d).x for d in all_desc(c)), key=abs) > 0.08]
        if cs:
            arms[side] = max(cs, key=reach_x)
    return spine, spine_set, arms

def reach_x(b):
    return max(abs(H(d).x) for d in all_desc(b))

spine, spine_set, arms = find_spine_and_arms(True)
if not arms:
    spine, spine_set, arms = find_spine_and_arms(False)

# legs: chains off the root / first spine bones whose end has a horizontal foot near the ground
def is_leg(c):
    ch = chain_down(c)
    if len(ch) < 3:
        return False
    low = min(Tl(b).z for b in ch)
    foot = [b for b in ch if Tl(b).z < 0.15 and abs(Tl(b).z - H(b).z) < 0.8 * (Tl(b) - H(b)).length]
    return low < 0.12 and bool(foot)
legs = {}
for side, sgn in (("Left", 1), ("Right", -1)):
    cs = [c for c in arm.data.bones if c.name not in spine_set and c.parent is not None
          and 0.25 < H(c).z < H(root).z + 0.15 and sgn * H(c).x > 0.02
          and (c.parent.name in spine_set or sgn * H(c.parent).x <= 0.02) and is_leg(c)]
    if cs:
        legs[side] = max(cs, key=lambda c: abs(H(c).x) + len(chain_down(c)) * 0.01)

J = {}
HINTS = {}
branch = min((H(a) for a in arms.values()), key=lambda p: -p.z, default=None)
neck_i = max((i for i, s in enumerate(spine) if any(c.name in [k.name for k in s.children] for c in arms.values())), default=len(spine) // 2)
hips = H(root); neck = H(spine[neck_i]) if arms else H(spine[len(spine) // 2])
J["Hips"] = hips
for k, f in (("Spine", 0.25), ("Spine1", 0.5), ("Spine2", 0.78)):
    J[k] = hips.lerp(neck, f)
J["Neck"] = neck
above = spine[neck_i + 1:]
J["Head"] = H(above[0]) if above else neck + Vector((0, 0, 0.1))
J["HeadTop_End"] = Tl(spine[-1])
if (J["HeadTop_End"] - J["Head"]).length < 0.1:
    J["HeadTop_End"] = J["Head"] + Vector((0, 0, 0.2))
for side, a in arms.items():
    ch = chain_down(a)
    pts = [H(b) for b in ch] + [Tl(ch[-1])]
    if len(pts) < 5:
        pts += [pts[-1]] * (5 - len(pts))
    J[f"{side}Shoulder"], J[f"{side}Arm"], J[f"{side}ForeArm"], J[f"{side}Hand"] = pts[0], pts[1], pts[2], pts[3]
    # held prop hint: the path from the wrist to its farthest descendant (a weapon or staff
    # when it runs well past the fingers)
    far = max(all_desc(ch[-1]), key=lambda d: (Tl(d) - pts[3]).length)
    path = []
    b = far
    while b is not None and b.name != ch[-1].name:
        path.append(Tl(b)); b = b.parent
    path = [pts[3]] + path[::-1]
    if (path[-1] - pts[3]).length > 0.3:
        HINTS[side + "Hand"] = [[round(c, 3) for c in p] for p in path]
    # a short step past the wrist: the farthest descendant can be a held weapon, not a finger
    J[f"{side}Hand_End"] = pts[3] + (pts[3] - pts[2]).normalized() * 0.09
for side, l in legs.items():
    ch = chain_down(l)
    pts = [H(b) for b in ch] + [Tl(ch[-1])]
    pts += [pts[-1]] * max(0, 5 - len(pts))
    J[f"{side}UpLeg"], J[f"{side}Leg"], J[f"{side}Foot"] = pts[0], pts[1], pts[2]
    J[f"{side}ToeBase"], J[f"{side}Toe_End"] = pts[3], pts[-1]
# mirror a side that was not found from the side that was
for a, b in (("Left", "Right"), ("Right", "Left")):
    for part in ("Shoulder", "Arm", "ForeArm", "Hand", "Hand_End", "UpLeg", "Leg", "Foot", "ToeBase", "Toe_End"):
        if a + part in J and b + part not in J:
            v = J[a + part]; J[b + part] = Vector((-v.x, v.y, v.z)); print("MIRRORED", b + part)
out = {k: [round(v.x, 3), round(v.y, 3), round(v.z, 3)] for k, v in J.items()}
json.dump(dict(out, _propHints=HINTS) if HINTS else out, open(argv[1], "w"), indent=1)
print("PROPHINTS", {k: (len(v), v[0], v[-1]) for k, v in HINTS.items()})
print("AUTOJOINTS arms", {k: v.name for k, v in arms.items()}, "legs", {k: v.name for k, v in legs.items()},
      "spine", [b.name for b in spine], "missing", sorted(set(
          ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End"] +
          [f"{s}{p}" for s in ("Left", "Right") for p in ("Shoulder", "Arm", "ForeArm", "Hand", "Hand_End", "UpLeg", "Leg", "Foot", "ToeBase", "Toe_End")]) - set(out)))
