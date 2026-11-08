"""Morph-weight keys bake_cs.py writes for one clip (pure; bake_cs.py runs it inside Blender, test_cs_weight_keys.py
tests it without bpy).

weight_keys(f0, f1, own, first) -> [(shape, frame, value), ...] in insertion order:
  own    [(frame, shape), ...]: the clip's own CS_ shapes, each keyed 1 on its frame and 0 on the frames either side
         (within the clip's f0..f1), the rule since the float64 bake;
  first  any shape of the bake (None when the bake made no shape at all): a clip with no shape of its own (every frame's
         correction under bake_cs's 1e-4: only rigid parts move, 2026-10-12 h3_sacred_phoenix Move/MoveStart/MoveEnd)
         keys it 0 at f0 and f1, so the export still writes that clip a morph-weight channel, all shapes 0 -- the
         bundle probe reads every clip's weight track (ship_def_retarget_slice.probe_frame_times: blendNone there).
A bake with no shape at all keys nothing (the GLB has no morph targets, and no weight channels).
"""
from __future__ import annotations


def weight_keys(f0: int, f1: int, own: list, first=None) -> list:
    if not own:
        return [] if first is None else [(first, ff, 0.0) for ff in sorted({f0, f1})]
    out = []
    for f, kb in own:
        for ff, val in ((f - 1, 0.0), (f, 1.0), (f + 1, 0.0)):
            if f0 <= ff <= f1:
                out.append((kb, ff, val))
    return out
