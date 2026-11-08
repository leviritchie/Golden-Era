"""Depth-displaced billboard: sprite pixels in 3D from Video Depth Anything maps.

This is not a character mesh and not the skinned-mesh battle lane. Each opaque
sprite pixel stays a billboard sample and is placed in 3D along the billboard
normal using the matching VDA depth value.
"""
from geometry import BillboardPoints, billboard_points_from_frame, load_depth01
from render import render_billboard_points
from synthetic_crusader import synthetic_crusader_move_frames

__all__ = [
    "BillboardPoints",
    "billboard_points_from_frame",
    "load_depth01",
    "render_billboard_points",
    "synthetic_crusader_move_frames",
]
