"""Lossless pages of decoded reel frames; not animation or geometry approval."""
import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageSequence

PAGE_SIZE = (2048, 1800)
LABEL_HEIGHT = 22


def build(reel, out):
    reel, out = Path(reel), Path(out)
    if out.exists():
        raise ValueError("Use a fresh review directory")
    reel_bytes = reel.read_bytes()
    page_width, page_height = PAGE_SIZE
    if page_width <= 0 or page_height <= LABEL_HEIGHT:
        raise ValueError("Page must leave room for native pixels below the label")
    pages, frames = [], []
    page = Image.new("RGBA", PAGE_SIZE, (17, 17, 17, 255))
    x = y = row_height = 0
    used_height = 0
    page_number = 0

    def flush():
        path = out / f"page_{page_number:03}.png"
        page.crop((0, 0, page_width, used_height)).save(path)
        pages.append({"page": page_number, "size": [page_width, used_height],
                      "path": path.resolve().as_posix(),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    with Image.open(io.BytesIO(reel_bytes)) as animation:
        out.mkdir(parents=True)
        for number, source in enumerate(ImageSequence.Iterator(animation)):
            # The renderer exports no trusted per-frame bounds alongside its GIF.
            # Keep the entire decoded canvas, including labels and background-like pixels.
            im = source.convert("RGBA")
            frame = {"frame": number, "size": list(im.size),
                     "durationMs": source.info.get("duration"),
                     "rgbaSha256": hashlib.sha256(im.tobytes()).hexdigest(), "tiles": []}
            for top in range(0, im.height, page_height - LABEL_HEIGHT):
                for left in range(0, im.width, page_width):
                    box = (left, top, min(im.width, left + page_width),
                           min(im.height, top + page_height - LABEL_HEIGHT))
                    tile = im.crop(box)
                    width, height = tile.width, tile.height + LABEL_HEIGHT
                    if x + width > page_width:
                        x, y, row_height = 0, y + row_height, 0
                    if y + height > page_height:
                        flush()
                        page_number += 1
                        page = Image.new("RGBA", PAGE_SIZE, (17, 17, 17, 255))
                        x = y = row_height = used_height = 0
                    tile_number = len(frame["tiles"])
                    # Clip labels to their own strip, never into neighboring native pixels.
                    label = Image.new("RGBA", (width, LABEL_HEIGHT), (17, 17, 17, 255))
                    ImageDraw.Draw(label).text((4, 3),
                        f"frame {number} tile {tile_number} | {frame['durationMs']} ms", fill="white")
                    page.paste(label, (x, y))
                    page.paste(tile, (x, y + LABEL_HEIGHT))
                    frame["tiles"].append({"tile": tile_number, "page": page_number,
                        "sourceBox": list(box),
                        "pageBox": [x, y + LABEL_HEIGHT, x + width, y + height]})
                    x += width
                    row_height = max(row_height, height)
                    used_height = max(used_height, y + height)
            frames.append(frame)
        flush()
    manifest = {"schema": "reel_native_pages.v2", "reel": reel.resolve().as_posix(),
                "reelSha256": hashlib.sha256(reel_bytes).hexdigest(),
                "contentBoundsPolicy": "full decoded frame; no trusted renderer bounds supplied",
                "frameIndexMeaning": "decoded reel index, not a master-sequence index",
                "boxConvention": "left, top, right, bottom; right/bottom exclusive",
                "loop": animation.info.get("loop"),
                "resized": False, "proof": "all decoded native frames; not visual approval",
                "frames": frames, "pages": pages}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"frames": len(frames), "pages": len(pages), "resized": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.reel, args.out)))
