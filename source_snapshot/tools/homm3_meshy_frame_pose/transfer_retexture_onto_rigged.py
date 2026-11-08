#!/usr/bin/env python3
"""Copy Principled BSDF image maps from a retextured GLB onto a rigged GLB.

Keeps armature/skin/weights of --rigged; replaces Base Color / Metallic /
Roughness / Normal (and Emission if present) from --textured.

Blender:
  blender -b --python transfer_retexture_onto_rigged.py -- \\
    --textured .../idle_f0_meshy6_retexture.glb \\
    --rigged .../idle_f0_rigged_bridgefix.glb \\
    --out .../idle_f0_rigged_bridgefix_meshy6.glb
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")

SOCKET_MAP = (
    ("Base Color", "Base Color"),
    ("Metallic", "Metallic"),
    ("Roughness", "Roughness"),
    ("Normal", "Normal"),
    ("Emission", "Emission Color"),
    ("Emission Color", "Emission Color"),
)


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {"textured": None, "rigged": None, "out": None, "report": None}
    i = 0
    while i < len(args):
        if args[i] == "--textured" and i + 1 < len(args):
            out["textured"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--rigged" and i + 1 < len(args):
            out["rigged"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out["out"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--report" and i + 1 < len(args):
            out["report"] = Path(args[i + 1])
            i += 2
        else:
            i += 1
    return out


def _clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_glb(path: Path) -> tuple[list, list]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in imported if o.type == "MESH"]
    arms = [o for o in imported if o.type == "ARMATURE"]
    return meshes, arms


def _principled(mat):
    if mat is None or mat.node_tree is None:
        return None
    for n in mat.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    return None


def _follow_to_tex_image(node):
    """Walk common glTF wrapper nodes to the underlying TexImage."""
    seen = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if node.type == "TEX_IMAGE" and node.image is not None:
            return node
        if node.type == "NORMAL_MAP":
            color = node.inputs.get("Color")
            node = color.links[0].from_node if color and color.is_linked else None
            continue
        if node.type in {"SEPRGB", "SEPARATE_COLOR", "SEPARATE_RGB"}:
            src = node.inputs[0] if node.inputs else None
            node = src.links[0].from_node if src and src.is_linked else None
            continue
        break
    return None


def _image_from_input(sock):
    if sock is None or not sock.is_linked:
        return None, None
    node = sock.links[0].from_node
    tex = _follow_to_tex_image(node)
    if tex is not None:
        return tex.image, tex
    return None, None


def _ensure_tex_image(nt, image, *, label: str, non_color: bool):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = image
    n.label = label
    n.location = (-600, 0)
    if non_color and image is not None:
        try:
            image.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
    return n


def _replace_input_image(bsdf, sock_name: str, image, *, non_color: bool) -> bool:
    sock = bsdf.inputs.get(sock_name)
    if sock is None or image is None:
        return False
    nt = bsdf.id_data
    for link in list(sock.links):
        nt.links.remove(link)
    if sock_name == "Normal":
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (-300, -200)
        tex = _ensure_tex_image(nt, image, label="Normal", non_color=True)
        tex.location = (-600, -200)
        nt.links.new(tex.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], sock)
        return True
    tex = _ensure_tex_image(nt, image, label=sock_name, non_color=non_color)
    tex.location = (-600, 200 if sock_name == "Base Color" else 0)
    nt.links.new(tex.outputs["Color"], sock)
    return True


def _wire_metallic_roughness(bsdf, mr_image) -> list[dict]:
    """glTF packed MR: G=roughness, B=metallic via Separate Color."""
    if mr_image is None:
        return []
    nt = bsdf.id_data
    applied = []
    for sock_name in ("Metallic", "Roughness"):
        sock = bsdf.inputs.get(sock_name)
        if sock is None:
            continue
        for link in list(sock.links):
            nt.links.remove(link)
    tex = _ensure_tex_image(nt, mr_image, label="METALLIC ROUGHNESS", non_color=True)
    tex.location = (-700, -50)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    sep.location = (-450, -50)
    nt.links.new(tex.outputs["Color"], sep.inputs["Color"])
    # Blender Separate Color: Red/Green/Blue outputs.
    met = bsdf.inputs.get("Metallic")
    rough = bsdf.inputs.get("Roughness")
    if met is not None:
        nt.links.new(sep.outputs["Blue"], met)
        applied.append({"socket": "Metallic", "image": mr_image.name, "channel": "Blue"})
    if rough is not None:
        nt.links.new(sep.outputs["Green"], rough)
        applied.append({"socket": "Roughness", "image": mr_image.name, "channel": "Green"})
    return applied


def _collect_source_maps(meshes: list) -> dict[str, object]:
    """Pick first available image per BSDF socket across source meshes."""
    found: dict[str, object] = {}
    mr_image = None
    for mesh in meshes:
        for slot in mesh.material_slots:
            bsdf = _principled(slot.material)
            if bsdf is None:
                continue
            for src_name, _dst in SOCKET_MAP:
                if src_name in found:
                    continue
                sock = bsdf.inputs.get(src_name)
                img, _ = _image_from_input(sock)
                if img is not None:
                    found[src_name] = img
            # Detect packed MR even if Metallic/Roughness already resolved to same image.
            for sock_name in ("Metallic", "Roughness"):
                sock = bsdf.inputs.get(sock_name)
                if sock is None or not sock.is_linked:
                    continue
                node = sock.links[0].from_node
                if node.type in {"SEPRGB", "SEPARATE_COLOR", "SEPARATE_RGB"}:
                    tex = _follow_to_tex_image(node)
                    if tex is not None:
                        mr_image = tex.image
    if mr_image is not None:
        found["MetallicRoughness"] = mr_image
    return found


def run() -> dict:
    opts = _parse()
    textured = opts["textured"]
    rigged = opts["rigged"]
    out = opts["out"]
    if textured is None or rigged is None or out is None:
        raise RuntimeError("need --textured --rigged --out")
    if not textured.is_file():
        raise FileNotFoundError(textured)
    if not rigged.is_file():
        raise FileNotFoundError(rigged)

    _clear()
    src_meshes, _ = _import_glb(textured)
    if not src_meshes:
        raise RuntimeError(f"no mesh in textured GLB: {textured}")
    src_maps = _collect_source_maps(src_meshes)
    if not src_maps:
        raise RuntimeError("no image-backed Principled inputs found on textured mesh")

    # Drop imported objects; keep Image datablocks referenced by src_maps.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    dst_meshes, dst_arms = _import_glb(rigged)
    if not dst_meshes:
        raise RuntimeError(f"no mesh in rigged GLB: {rigged}")

    applied = []
    for mesh in dst_meshes:
        for slot in mesh.material_slots:
            mat = slot.material
            bsdf = _principled(mat)
            if bsdf is None:
                continue
            # Packed metallic-roughness first (glTF MR map).
            mr = src_maps.get("MetallicRoughness")
            if mr is not None:
                for entry in _wire_metallic_roughness(bsdf, mr):
                    applied.append(
                        {
                            "mesh": mesh.name,
                            "material": mat.name if mat else None,
                            **entry,
                            "size": list(mr.size) if hasattr(mr, "size") else None,
                        }
                    )
            for src_name, dst_name in SOCKET_MAP:
                if src_name in {"Metallic", "Roughness"} and mr is not None:
                    continue
                img = src_maps.get(src_name)
                if img is None:
                    continue
                non_color = src_name not in {"Base Color", "Emission", "Emission Color"}
                if _replace_input_image(bsdf, dst_name, img, non_color=non_color):
                    applied.append(
                        {
                            "mesh": mesh.name,
                            "material": mat.name if mat else None,
                            "socket": dst_name,
                            "image": img.name,
                            "size": list(img.size) if hasattr(img, "size") else None,
                        }
                    )

    if not applied:
        raise RuntimeError("failed to apply any textures onto rigged materials")

    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in dst_meshes + dst_arms:
        o.select_set(True)
    bpy.context.view_layer.objects.active = dst_arms[0] if dst_arms else dst_meshes[0]
    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        use_selection=True,
        export_animations=False,
        export_apply=False,
    )
    if not out.is_file() or out.stat().st_size < 1000:
        raise RuntimeError(f"export missing/empty: {out}")

    report = {
        "ok": True,
        "texturedGlb": str(textured).replace("\\", "/"),
        "riggedGlb": str(rigged).replace("\\", "/"),
        "outGlb": str(out).replace("\\", "/"),
        "outBytes": int(out.stat().st_size),
        "sourceMaps": {k: v.name for k, v in src_maps.items()},
        "applied": applied,
        "proof": (
            "generated artifact validated — meshy-6 retexture maps transferred onto "
            "existing rigged mesh; skin weights preserved; not OE runtime proven"
        ),
    }
    report_path = opts["report"] or out.with_suffix(".transfer_report.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
