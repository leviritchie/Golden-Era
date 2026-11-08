"""Surface attributes of a rebuilt mesh: the writer may replace them, and must refuse a broken shape.

`write_static_mesh_keep_pbr` exists to put a *rebuilt* surface back into its source's material.  A rebuild
- a remesh, a retopology, a decimation - authors its own vertices, so the source's NORMAL and TEXCOORD_0 are
the wrong length for it and cannot be copied onto them; the writer therefore takes optional replacements.
The three behaviours that matter, each pinned against a fixture whose content is known by hand:

* replacements are what lands in the file, byte for byte, and the source's own attributes do not;
* omitting them keeps the old behaviour, which is the source's attributes copied across a reorientation;
* a replacement of the wrong length or the wrong width is refused rather than silently truncated, because a
  glTF accessor count that disagrees with POSITION is a corrupt asset, not a mesh with missing UVs.

The contract validator requires this file to exist, so a future change cannot drop the guards silently.

    py -3 tools/homm3_meshy_frame_pose/test_glb_io_surface_attributes.py
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig import glb_io  # noqa: E402
from owned_rerig.glb_io import (  # noqa: E402
    load_mesh,
    load_render_surface,
    write_static_mesh_keep_pbr,
)

# A triangle whose widest axes are x and z, so ``should_reorient_y_up`` is False and the copied-attribute
# case is readable: no rotation is applied and the source's normals must survive unchanged.
SOURCE_POSITIONS = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 1.0]], dtype=np.float64)
SOURCE_NORMALS = np.array([[0.0, 0.0, 1.0]] * 3, dtype=np.float64)
SOURCE_UVS = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float64)


def _one_pixel_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), (200, 30, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _make_source(path: Path) -> None:
    """A one-triangle GLB carrying POSITION, NORMAL, TEXCOORD_0 and a 1x1 base-colour image."""
    blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []
    position = glb_io._append_array(blob, views, accessors, SOURCE_POSITIONS.astype(np.float32), "VEC3", 5126)
    normal = glb_io._append_array(blob, views, accessors, SOURCE_NORMALS.astype(np.float32), "VEC3", 5126)
    uv = glb_io._append_array(blob, views, accessors, SOURCE_UVS.astype(np.float32), "VEC2", 5126)
    index = glb_io._append_array(blob, views, accessors, np.array([0, 1, 2], dtype=np.uint32), "SCALAR", 5125)
    image = _one_pixel_png()
    offset = len(blob)
    blob.extend(image)
    glb_io._pad4(blob)
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(image)})
    document = {
        "asset": {"version": "2.0", "generator": "test_fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Mesh", "mesh": 0}],
        "meshes": [
            {
                "name": "Mesh",
                "primitives": [
                    {
                        "attributes": {"POSITION": position, "NORMAL": normal, "TEXCOORD_0": uv},
                        "indices": index,
                        "material": 0,
                    }
                ],
            }
        ],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
        "images": [{"mimeType": "image/png", "bufferView": len(views) - 1}],
        "textures": [{"source": 0}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
    }
    glb_io.write_glb(path, document, bytes(blob))


class SurfaceAttributeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self._temporary.name)
        self.source = self.directory / "source.glb"
        _make_source(self.source)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_replacements_are_written_and_the_sources_attributes_are_not(self) -> None:
        # A rebuilt surface: more vertices than the source, its own normals and UVs.
        positions = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 1.0], [0.0, 1.0, 1.0]], dtype=np.float64
        )
        normals = np.array([[0.0, 0.0, 1.0]] * 4, dtype=np.float64)
        uvs = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6], [0.7, 0.8]], dtype=np.float64)
        destination = self.directory / "rebuilt.glb"
        write_static_mesh_keep_pbr(
            self.source,
            destination,
            positions=positions,
            indices=np.array([0, 1, 2, 0, 2, 3], dtype=np.int64),
            normals=normals,
            uvs=uvs,
        )

        mesh = load_mesh(destination)
        surface = load_render_surface(destination)
        self.assertEqual(len(mesh.positions), 4)
        self.assertEqual(len(mesh.indices), 6)
        np.testing.assert_allclose(np.asarray(mesh.positions), positions, atol=1e-6)
        np.testing.assert_allclose(np.asarray(surface["normals"]), normals, atol=1e-6)
        np.testing.assert_allclose(np.asarray(surface["uvs"]), uvs, atol=1e-6)
        # The source's own attributes are the wrong length and must not appear anywhere in the file.
        self.assertNotEqual(len(surface["normals"]), len(SOURCE_NORMALS))
        # The material and its base-colour image come across from the source.
        self.assertEqual(list(surface["baseColorSize"]), [1, 1])
        self.assertTrue(np.array_equal(np.asarray(surface["baseColor"])[0, 0], [200, 30, 40]))

    def test_omitting_the_replacements_copies_the_sources_attributes(self) -> None:
        destination = self.directory / "copied.glb"
        write_static_mesh_keep_pbr(
            self.source,
            destination,
            positions=SOURCE_POSITIONS,
            indices=np.array([0, 1, 2], dtype=np.int64),
        )
        surface = load_render_surface(destination)
        self.assertEqual(len(surface["normals"]), 3)
        self.assertEqual(len(surface["uvs"]), 3)
        np.testing.assert_allclose(np.asarray(surface["normals"]), SOURCE_NORMALS, atol=1e-6)
        np.testing.assert_allclose(np.asarray(surface["uvs"]), SOURCE_UVS, atol=1e-6)

    def test_fail_closed_on_a_replacement_that_does_not_name_every_vertex(self) -> None:
        destination = self.directory / "broken.glb"
        positions = np.zeros((4, 3), dtype=np.float64)
        with self.assertRaises(ValueError) as short_normals:
            write_static_mesh_keep_pbr(
                self.source,
                destination,
                positions=positions,
                indices=np.array([0, 1, 2], dtype=np.int64),
                normals=np.zeros((3, 3), dtype=np.float64),
            )
        self.assertIn("normals must name every vertex", str(short_normals.exception))

        with self.assertRaises(ValueError) as short_uvs:
            write_static_mesh_keep_pbr(
                self.source,
                destination,
                positions=positions,
                indices=np.array([0, 1, 2], dtype=np.int64),
                uvs=np.zeros((3, 2), dtype=np.float64),
            )
        self.assertIn("uvs must name every vertex", str(short_uvs.exception))

        with self.assertRaises(ValueError) as wrong_width:
            write_static_mesh_keep_pbr(
                self.source,
                destination,
                positions=positions,
                indices=np.array([0, 1, 2], dtype=np.int64),
                uvs=np.zeros((4, 3), dtype=np.float64),
            )
        self.assertIn("uvs must be (N,2)", str(wrong_width.exception))

        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
