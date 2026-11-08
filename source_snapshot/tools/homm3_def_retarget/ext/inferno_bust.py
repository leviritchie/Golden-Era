"""Bust meshes (hook for build_unit.py).

The efreet sultan's Meshy mesh is only the torso, arms and head; the DEF efreet is that torso on a
long flame tail. build_unit fits the sprite camera by matching the mesh's full height to idle
frame 0's opaque bbox, which would stretch the bust over the flame. after_pose points SPRITE at a
copy of the sprite info whose idle bbox keeps only the top "bustFraction" of its height (the
torso), so the camera maps the bust onto the DEF torso and the flame stays a sprite/Unity effect.

Unit config: "bustFraction": 0.5
"""
import json


def after_pose(g):
    frac = g["cfg"].get("bustFraction")
    if not frac:
        return
    sj = json.load(open(g["SPRITE"]))
    x0, y0, x1, y1 = sj["bbox0"]
    sj["bbox0"] = [x0, y0, x1, int(round(y0 + frac * (y1 - y0)))]
    path = g["OUT"] + ".sprite_bust.json"
    json.dump(sj, open(path, "w"))
    g["SPRITE"] = path
    print("BUST sprite bbox", [x0, y0, x1, y1], "->", sj["bbox0"])
