import unittest

import numpy as np
from PIL import Image

from skin_camera_registration import _chroma_error, _validate_inputs
from run_skin_mesh_pilot import expand_camera_to_full_canvas


class FullCanvasRegistrationTest(unittest.TestCase):
    def test_chroma_tie_break_distinguishes_front_back_texture(self):
        target = np.zeros((2, 2, 3), dtype=np.float64)
        target[..., 0] = 1.0
        opposite = np.zeros_like(target)
        opposite[..., 2] = 1.0
        alpha = np.ones((2, 2), dtype=np.float64)
        self.assertGreater(_chroma_error(opposite, target, alpha, alpha), 1.0)

    def test_canonical_tall_canvas_is_accepted_and_foreground_survives(self):
        size = (824, 1056)
        crop = {"left": -((max(size) - size[0]) // 2), "top": -((max(size) - size[1]) // 2), "size": max(size)}
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        image.putpixel((0, 0), (255, 255, 255, 255))
        image.putpixel((823, 1055), (255, 255, 255, 255))
        padded = image.crop((crop["left"], crop["top"], crop["left"] + crop["size"], crop["top"] + crop["size"]))
        self.assertEqual(padded.getpixel((116, 0))[3], 255)
        self.assertEqual(padded.getpixel((939, 1055))[3], 255)
        rgb = np.zeros((1, 224, 224, 3), dtype=np.float64)
        alpha = np.ones((1, 224, 224, 1), dtype=np.float64)
        distance = np.zeros((1, 224, 224), dtype=np.float64)
        _validate_inputs(vertices=np.zeros((1, 3)), target_rgb=rgb, target_alpha=alpha, target_distance=distance, resolution=224, source_crop=crop, source_size=size)

    def test_odd_canvas_uses_expand_camera_centering(self):
        size = (825, 1056)
        crop = {"left": -115, "top": 0, "size": 1056}
        rgb = np.zeros((1, 224, 224, 3), dtype=np.float64)
        alpha = np.ones((1, 224, 224, 1), dtype=np.float64)
        distance = np.zeros((1, 224, 224), dtype=np.float64)
        _validate_inputs(vertices=np.zeros((1, 3)), target_rgb=rgb, target_alpha=alpha, target_distance=distance, resolution=224, source_crop=crop, source_size=size)

    def test_arbitrary_oversize_crop_is_rejected(self):
        with self.assertRaises(ValueError):
            _validate_inputs(vertices=np.zeros((1, 3)), target_rgb=np.zeros((1, 224, 224, 3)), target_alpha=np.ones((1, 224, 224, 1)), target_distance=np.zeros((1, 224, 224)), resolution=224, source_crop={"left": -3, "top": -2, "size": 1060}, source_size=(824, 1056))

    def test_tall_wide_odd_and_square_rebase_is_identity(self):
        for width, height in ((824, 1056), (1056, 824), (825, 1056), (1056, 825), (224, 224)):
            with self.subTest(size=(width, height)):
                size = max(width, height)
                crop = {"left": -((size - width) // 2), "top": -((size - height) // 2), "size": size}
                _validate_inputs(vertices=np.zeros((1, 3)), target_rgb=np.zeros((1, 224, 224, 3)),
                    target_alpha=np.ones((1, 224, 224, 1)), target_distance=np.zeros((1, 224, 224)),
                    resolution=224, source_crop=crop, source_size=(width, height))
                camera = {"sourceSize": [width, height], "sourceCrop": crop,
                          "resolution": 224, "scale": 71.25, "offset": [86.5, 132.0]}
                self.assertEqual(expand_camera_to_full_canvas(camera), camera)
                shifted = dict(crop, left=crop["left"] - 1)
                with self.assertRaises(ValueError):
                    _validate_inputs(vertices=np.zeros((1, 3)), target_rgb=np.zeros((1, 224, 224, 3)),
                        target_alpha=np.ones((1, 224, 224, 1)), target_distance=np.zeros((1, 224, 224)),
                        resolution=224, source_crop=shifted, source_size=(width, height))


if __name__ == "__main__":
    unittest.main()
