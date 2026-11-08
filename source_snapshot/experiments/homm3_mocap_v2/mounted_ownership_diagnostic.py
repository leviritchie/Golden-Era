"""CPU-only ownership diagnostic for the frozen mounted wolf-rider skin."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

try:
    from .donor_eagle import skin_dense
except ImportError:
    from donor_eagle import skin_dense

DEFAULT_FREEZE = Path("artifacts/homm3_mocap_v2/shape_preserved/h3_wolf_rider/preparation_frozen.json")


def _rotation(axis, angle):
    axis = np.asarray(axis, dtype=float); axis /= np.linalg.norm(axis)
    x, y, z = axis; c, s = np.cos(angle), np.sin(angle); C = 1 - c
    return np.array([[x*x*C+c, x*y*C-z*s, x*z*C+y*s], [y*x*C+z*s, y*y*C+c, y*z*C-x*s],
                     [z*x*C-y*s, z*y*C+x*s, z*z*C+c]])


def probe(vertices, triangles, weights, names, parents, rest, inverse_bind, joint_name, regions=None, degrees=30.0, axis=(1.0, 0.0, 0.0)):
    index = {str(n): i for i, n in enumerate(names)}
    if joint_name not in index:
        raise ValueError(f"joint not present: {joint_name}")
    target = index[joint_name]
    axis = np.asarray(axis, dtype=float)
    if np.linalg.norm(axis) < 1e-8: raise ValueError("probe axis must be non-zero")
    R = _rotation(axis, np.deg2rad(degrees))
    bind = np.repeat(np.eye(4)[None], len(names), axis=0); bind[:, :3, 3] = rest
    for i in range(len(names)):
        ancestor = i
        while ancestor >= 0 and ancestor != target:
            ancestor = int(parents[ancestor])
        if ancestor == target:
            T = np.eye(4); T[:3, :3] = R; T[:3, 3] = rest[target] - R @ rest[target]
            bind[i] = T @ bind[i]
    moved = skin_dense(vertices, weights, bind, inverse_bind)
    delta = np.linalg.norm(moved - vertices, axis=1)
    edge0 = np.linalg.norm(vertices[triangles[:, 1]] - vertices[triangles[:, 0]], axis=1)
    edge1 = np.linalg.norm(vertices[triangles[:, 2]] - vertices[triangles[:, 1]], axis=1)
    edge2 = np.linalg.norm(vertices[triangles[:, 0]] - vertices[triangles[:, 2]], axis=1)
    after = (np.linalg.norm(moved[triangles[:, 1]] - moved[triangles[:, 0]], axis=1) /
             np.maximum(edge0, 1e-8) + np.linalg.norm(moved[triangles[:, 2]] - moved[triangles[:, 1]], axis=1) /
             np.maximum(edge1, 1e-8) + np.linalg.norm(moved[triangles[:, 0]] - moved[triangles[:, 2]], axis=1) /
             np.maximum(edge2, 1e-8)) / 3
    order = np.argsort(np.abs(after - 1))[::-1][:10]
    pairs = [] if regions is None else [[str(regions[v]) for v in triangles[i]] for i in order]
    return {"joint": joint_name, "degrees": degrees, "axis": [float(x) for x in axis], "metric": "meanEdgeLengthRatio",
            "vertexMovement": {"max": float(delta.max()), "mean": float(delta.mean()), "movedFraction": float(np.mean(delta > 1e-7))},
            "topTriangleStretch": [{"triangle": int(i), "factor": float(after[i]), "regions": pairs[k]} for k, i in enumerate(order)], "moved": moved}


def _contact_sheet(poses, labels, triangles, regions, path):
    """Depth-sorted orthographic diagnostic, fixed uniform scale across poses."""
    colors = {"mount": (215,105,65), "rider": (65,145,215), "weapon": (225,205,70)}
    palette=[colors['weapon' if str(regions[t[0]])=='weapon' else ('rider' if str(regions[t[0]]).startswith('rider_') else 'mount')] for t in triangles]
    allpoints=np.concatenate(poses);frames=[]
    planes=((2,1,0),(0,1,2),(2,0,1))
    for vertices,label in zip(poses,labels):
        image=Image.new('RGB',(900,330),(30,30,34));draw=ImageDraw.Draw(image)
        for panel,(a,b,depth) in enumerate(planes):
            coords=vertices[:,(a,b)];bounds=allpoints[:,(a,b)];lo=bounds.min(axis=0);hi=bounds.max(axis=0)
            xy=(coords-(lo+hi)/2)*(270/max(hi-lo));xy[:,1]*=-1;xy+=np.array([panel*300+150,175])
            order=np.argsort(vertices[triangles,depth].mean(axis=1))
            for i in order:draw.polygon([tuple(xy[v]) for v in triangles[i]],fill=palette[i])
            draw.text((panel*300+4,6),('Side','Front','Top')[panel],fill='white')
        draw.text((4,312),label+'; orange mount / blue rider / yellow weapon',fill='white');frames.append(image)
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=650,loop=0)
    sheet=Image.new('RGB',(900,330*len(frames)),(30,30,34))
    for i,im in enumerate(frames):sheet.paste(im,(0,330*i))
    sheet.save(path.with_suffix('.png'))


def diagnose(freeze_path: str, output: str, preview: str | None = None) -> dict:
    freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8")); skin_path = Path(freeze["researchSkin"])
    with np.load(skin_path, allow_pickle=False) as z:
        vertices, triangles, weights, names = z["vertices"], z["triangles"], z["weights"], z["names"]
        parents, rest, inverse_bind, regions = z["parents"], z["restAnchors"], z["inverseBind"], z["regions"]
        uvs, albedo = z["uvs"], z["albedo"]
    probes = {}
    poses=[vertices];labels=['Rest']
    for joint in ("rider:mixamorig:RightArm", "rider:mixamorig:LeftArm", "mount:Bip01_Neck"):
        for sign in (-1, 1):
            label = f"{joint} {'-' if sign < 0 else '+'}30deg"
            result = probe(vertices, triangles, weights, names, parents, rest, inverse_bind, joint, regions, sign * 30.0, axis=(1.0, 0.0, 0.0))
            moved = result.pop("moved")
            poses.append(moved);labels.append(label)
            actor = "rider" if joint.startswith("rider:") else "mount"
            other = np.array([(str(r).startswith('mount_') if actor=='rider' else str(r).startswith('rider_') or str(r)=='weapon') for r in regions])
            result["unmovingActorLeakage"] = {"max": float(np.linalg.norm(moved[other] - vertices[other], axis=1).max(initial=0.0)),
                                               "mean": float(np.linalg.norm(moved[other] - vertices[other], axis=1).mean())}
            probes[label] = result
    if preview:
        _contact_sheet(poses, labels, triangles, regions, Path(preview))
    output_path = Path(output)
    if preview:
        report_preview = str(Path(preview).resolve())
    else:
        report_preview = None
    output_path.write_text(json.dumps({"freeze": str(Path(freeze_path).resolve()), "probes": probes,
                                       "previewGIF": report_preview}, indent=2) + "\n", encoding="utf-8")
    return json.loads(output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--freeze", default=str(DEFAULT_FREEZE)); parser.add_argument("--output", required=True); parser.add_argument("--preview")
    args = parser.parse_args(); print(json.dumps(diagnose(args.freeze, args.output, args.preview), indent=2))
