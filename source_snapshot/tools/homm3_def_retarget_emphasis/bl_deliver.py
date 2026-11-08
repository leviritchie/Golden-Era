"""One Blender process per unit for the emphasis pass (driven by deliver.py; never run on a build's own
.blend -- deliver.py hands it a work copy).

  blender -b <work.blend> -P bl_deliver.py -- <workdir> <retarget unit config.json>

Reads <workdir>/detect.json and <workdir>/cfg.json. Writes into <workdir>:
  keys_before.npz, plan.json (detection + per-clip plan; decision "unchanged" when nothing is flagged,
  in which case nothing else happens and the .blend is not saved), and, when emphasised:
  the saved work .blend (keys rewritten, corrective-smooth morphs re-baked by the shared bake_cs.py
  with the unit's own correctiveSmooth setting), renders_after/ (sprite + side views of the changed
  clips only, by the shared render_reel.py), stretch_after.json (shared stretch.py, every frame),
  keys_after.npz, work.glb (shared export_glb.py; exported last, the NLA layout is not saved).
The shared scripts are executed unmodified with their own argv.
"""
import bpy, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bl_keys  # noqa: E402
import emphasis as E  # noqa: E402

RT = os.path.join(E.ROOT, "tools", "homm3_def_retarget")
argv = sys.argv[sys.argv.index("--") + 1:]
WD, UCFG = argv[0], argv[1]
det = json.load(open(os.path.join(WD, "detect.json")))
cfg = json.load(open(os.path.join(WD, "cfg.json")))
ucfg = json.load(open(UCFG))
blend = bpy.data.filepath
fj = json.load(open(blend + ".frames.json"))


def run_shared(script, args, extra_globals=None):
    old = sys.argv
    sys.argv = [old[0], "--", *args]
    g = {"__name__": "__main__", "__file__": os.path.join(RT, script)}
    g.update(extra_globals or {})
    try:
        exec(compile(open(os.path.join(RT, script)).read(), os.path.join(RT, script), "exec"), g)
    finally:
        sys.argv = old


before = bl_keys.dump()
np.savez(os.path.join(WD, "keys_before.npz"), **before)
Q2, info = E.plan(before, det, cfg)
emph = [c for c, i in info.items() if i.get("emphasised")]
json.dump({"detect": det, "plan": info, "decision": "emphasised" if emph else "unchanged"},
          open(os.path.join(WD, "plan.json"), "w"), indent=1)
if not emph:
    print("EMPH_DELIVER unchanged")
    sys.exit(0)

n_master, rep = bl_keys.write(before["Q"], Q2, before["names"], fj["segments"])
json.dump(rep, open(os.path.join(WD, "actions.json"), "w"), indent=1)
print("EMPH_DELIVER keys written", n_master, json.dumps(rep))

sc = bpy.context.scene
cs = ucfg.get("correctiveSmooth", {})
if cs is not False:
    run_shared("bake_cs.py", [], {"CS_ITER": cs.get("iterations", 30), "CS_FACT": cs.get("factor", 0.7),
                                         "CS_EXCLUDE": cs.get("excludeBones", []), "__name__": "bake_cs"})
else:
    bpy.ops.wm.save_mainfile()
bl_keys.use_master()
key = next((o.data.shape_keys for o in bpy.data.objects if o.type == 'MESH' and o.data.shape_keys), None)

rd = os.path.join(WD, "renders_after"); os.makedirs(rd, exist_ok=True)
f0, f1 = sc.frame_start, sc.frame_end
cam0, rx, ry = sc.camera, sc.render.resolution_x, sc.render.resolution_y
for clip in emph:
    a, b = det[clip]["range"]
    sc.frame_start, sc.frame_end = a + 1, b
    run_shared("render_reel.py", [rd])
    sc.camera, sc.render.resolution_x, sc.render.resolution_y = cam0, rx, ry
sc.frame_start, sc.frame_end = f0, f1
for o in [o for o in bpy.data.objects if o.name.startswith("SideCam")]:
    bpy.data.objects.remove(o, do_unlink=True)

run_shared("stretch.py", [os.path.join(WD, "stretch_after.json")])
after = bl_keys.dump()
np.savez(os.path.join(WD, "keys_after.npz"), **after)
run_shared("export_glb.py", [os.path.join(WD, "work.glb")])
print("EMPH_DELIVER done", emph)
