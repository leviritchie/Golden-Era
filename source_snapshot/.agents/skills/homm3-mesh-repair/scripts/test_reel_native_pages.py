import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageSequence

import reel_native_pages as pages


class NativePagesTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[4]
        self.temp = tempfile.TemporaryDirectory(prefix="native-pages-test-", dir=root / "artifacts")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reel = self.root / "input.gif"
        self.out = self.root / "pages"

    def frame(self, size, color=17):
        image = Image.new("P", size, color)
        image.putpalette([channel for value in range(256) for channel in (value,) * 3])
        return image

    def save(self, frames, durations=None, **kwargs):
        frames[0].save(self.reel, save_all=True, append_images=frames[1:],
                       duration=durations or [100] * len(frames), loop=2,
                       optimize=False, **kwargs)

    def assert_roundtrip(self, page_size=(64, 72)):
        with patch.object(pages, "PAGE_SIZE", page_size):
            result = pages.build(self.reel, self.out)
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(manifest["schema"], "reel_native_pages.v2")
        self.assertFalse(manifest["resized"])
        self.assertEqual(manifest["reelSha256"], hashlib.sha256(self.reel.read_bytes()).hexdigest())
        self.assertEqual(manifest["loop"], 2)
        self.assertEqual(result["frames"], len(manifest["frames"]))
        loaded = {}
        for page in manifest["pages"]:
            path = Path(page["path"])
            self.assertEqual(page["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            with Image.open(path) as image:
                loaded[page["page"]] = image.copy()
            self.assertEqual(list(loaded[page["page"]].size), page["size"])
            self.assertLessEqual(page["size"][0], page_size[0])
            self.assertLessEqual(page["size"][1], page_size[1])
        occupied = {}
        with Image.open(self.reel) as reel:
            originals = [(f.convert("RGBA"), f.info.get("duration"))
                         for f in ImageSequence.Iterator(reel)]
        self.assertEqual(len(originals), len(manifest["frames"]))
        for number, (row, (original, duration)) in enumerate(zip(manifest["frames"], originals)):
            self.assertEqual(row["frame"], number)
            self.assertEqual(row["size"], list(original.size))
            self.assertEqual(row["durationMs"], duration)
            restored = Image.new("RGBA", original.size)
            coverage = set()
            for index, tile in enumerate(row["tiles"]):
                self.assertEqual(tile["tile"], index)
                left, top, right, bottom = tile["sourceBox"]
                x, y, end_x, end_y = tile["pageBox"]
                self.assertTrue(0 <= left < right <= original.width)
                self.assertTrue(0 <= top < bottom <= original.height)
                self.assertEqual((right - left, bottom - top), (end_x - x, end_y - y))
                page = loaded[tile["page"]]
                self.assertTrue(0 <= x < end_x <= page.width)
                self.assertTrue(0 <= y < end_y <= page.height)
                source_pixels = {(a, b) for a in range(left, right) for b in range(top, bottom)}
                self.assertTrue(coverage.isdisjoint(source_pixels))
                coverage.update(source_pixels)
                page_pixels = {(a, b) for a in range(x, end_x) for b in range(y, end_y)}
                previous = occupied.setdefault(tile["page"], set())
                self.assertTrue(previous.isdisjoint(page_pixels))
                previous.update(page_pixels)
                restored.paste(page.crop(tile["pageBox"]), (left, top))
            self.assertEqual(len(coverage), original.width * original.height)
            self.assertEqual(restored.tobytes(), original.tobytes())
            self.assertEqual(row["rgbaSha256"], hashlib.sha256(restored.tobytes()).hexdigest())
        return manifest

    def test_near_background_header_and_corner_pixels_survive(self):
        image = self.frame((60, 45))
        image.putpixel((2, 40), 24)
        image.putpixel((20, 1), 200)
        image.putpixel((59, 44), 240)
        self.save([image])
        manifest = self.assert_roundtrip()
        self.assertEqual(manifest["frames"][0]["tiles"][0]["sourceBox"], [0, 0, 60, 45])

    def test_uniform_frame_is_retained(self):
        self.save([self.frame((30, 35))])
        self.assert_roundtrip()

    def test_oversized_both_axes_tile_without_loss(self):
        image = self.frame((137, 113))
        for y in range(image.height):
            for x in range(image.width):
                image.putpixel((x, y), (x + 3 * y) % 256)
        self.save([image])
        manifest = self.assert_roundtrip()
        self.assertEqual(len(manifest["frames"][0]["tiles"]), 9)

    def test_exact_tile_boundary(self):
        self.save([self.frame((64, 50))])
        manifest = self.assert_roundtrip()
        self.assertEqual(len(manifest["pages"]), 1)
        self.assertEqual(manifest["frames"][0]["tiles"][0]["pageBox"], [0, 22, 64, 72])

    def test_multiple_frames_pack_wrap_and_keep_cadence(self):
        self.save([self.frame((20, 9), i) for i in (20, 40, 60, 80, 100, 120, 140)],
                  [40, 70, 100, 130, 160, 190, 220])
        manifest = self.assert_roundtrip()
        self.assertEqual(len(manifest["frames"]), 7)
        self.assertEqual(len(manifest["pages"]), 2)

    def test_transparent_pixels_and_disposal_are_preserved(self):
        first, second = self.frame((35, 35), 0), self.frame((35, 35), 0)
        first.putpixel((1, 1), 200)
        second.putpixel((30, 30), 220)
        self.save([first, second], transparency=0, disposal=2)
        self.assert_roundtrip()

    def test_existing_directory_is_untouched(self):
        self.out.mkdir()
        sentinel = self.out / "keep.txt"
        sentinel.write_text("unchanged")
        with self.assertRaisesRegex(ValueError, "fresh"):
            pages.build(self.reel, self.out)
        self.assertEqual(sentinel.read_text(), "unchanged")

    def test_invalid_reel_creates_no_output(self):
        self.reel.write_bytes(b"not an image")
        with self.assertRaises(OSError):
            pages.build(self.reel, self.out)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
