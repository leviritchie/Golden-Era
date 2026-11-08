#!/usr/bin/env python3
# Python 3 port of tools/defextract.py (same logic, H3 .def → PNG + json).

import json
import os
import struct
import sys
from collections import defaultdict

import numpy as np
from PIL import Image


def extract_def(infile, outdir):
    with open(infile, "rb") as f:
        bn = os.path.basename(infile)
        bn = os.path.splitext(bn)[0].lower()
        t, _, _, blocks = struct.unpack("<IIII", f.read(16))
        palette = []
        for _ in range(256):
            r, g, b = struct.unpack("<BBB", f.read(3))
            palette.extend((r, g, b))
        offsets = defaultdict(list)
        for _ in range(blocks):
            bid, entries, _, _ = struct.unpack("<IIII", f.read(16))
            for _j in range(entries):
                f.read(13)  # names
            for _j in range(entries):
                offs, = struct.unpack("<I", f.read(4))
                offsets[bid].append(offs)
        outpath = os.path.join(outdir, "%s.dir" % bn)
        if os.path.exists(outpath):
            if not os.path.isdir(outpath):
                print("output path exists and is no directory", file=sys.stderr)
                return False
        else:
            os.mkdir(outpath)
        out_json = {"sequences": [], "type": t, "format": -1}
        firstfw, firstfh = -1, -1
        for bid, l in offsets.items():
            frames = []
            for j, offs in enumerate(l):
                f.seek(offs)
                pixeldata = b""
                _, fmt, fw, fh, w, h, lm, tm = struct.unpack(
                    "<IIIIIIii", f.read(32)
                )
                outname = os.path.join(outpath, "%02d_%02d.png" % (bid, j))
                if lm > fw or tm > fh:
                    print("margins (%dx%d) vs (%dx%d)" % (lm, tm, fw, fh), file=sys.stderr)
                    return False
                if firstfw == -1 and firstfh == -1:
                    firstfw = fw
                    firstfh = fh
                else:
                    if firstfw > fw:
                        fw = firstfw
                    if firstfw < fw:
                        print("inconsistent width", file=sys.stderr)
                        return False
                    if firstfh > fh:
                        fh = firstfh
                    if firstfh < fh:
                        print("inconsistent height", file=sys.stderr)
                        return False
                if out_json["format"] == -1:
                    out_json["format"] = fmt
                elif out_json["format"] != fmt:
                    print("format mismatch", file=sys.stderr)
                    return False
                frames.append(os.path.join("%s.dir" % bn, "%02d_%02d.png" % (bid, j)))
                if w != 0 and h != 0:
                    if fmt == 0:
                        pixeldata = f.read(w * h)
                    elif fmt == 1:
                        lineoffs = struct.unpack("<" + "I" * h, f.read(4 * h))
                        for lineoff in lineoffs:
                            f.seek(offs + 32 + lineoff)
                            totalrowlength = 0
                            while totalrowlength < w:
                                code, length = struct.unpack("<BB", f.read(2))
                                length += 1
                                if code == 0xFF:
                                    pixeldata += f.read(length)
                                else:
                                    pixeldata += length * bytes([code])
                                totalrowlength += length
                    elif fmt == 2:
                        lineoffs = struct.unpack("<" + "%dH" % h, f.read(2 * h))
                        f.read(2)
                        for lineoff in lineoffs:
                            if f.tell() != offs + 32 + lineoff:
                                f.seek(offs + 32 + lineoff)
                            totalrowlength = 0
                            while totalrowlength < w:
                                segment, = struct.unpack("<B", f.read(1))
                                code = segment >> 5
                                length = (segment & 0x1F) + 1
                                if code == 7:
                                    pixeldata += f.read(length)
                                else:
                                    pixeldata += length * bytes([code])
                                totalrowlength += length
                    elif fmt == 3:
                        nblocks = w // 32
                        lineoffs = [
                            struct.unpack(
                                "<" + "H" * nblocks, f.read(2 * nblocks)
                            )
                            for _i in range(h)
                        ]
                        for lineoff in lineoffs:
                            for i in lineoff:
                                if f.tell() != offs + 32 + i:
                                    f.seek(offs + 32 + i)
                                totalblocklength = 0
                                while totalblocklength < 32:
                                    segment, = struct.unpack("<B", f.read(1))
                                    code = segment >> 5
                                    length = (segment & 0x1F) + 1
                                    if code == 7:
                                        pixeldata += f.read(length)
                                    else:
                                        pixeldata += length * bytes([code])
                                    totalblocklength += length
                    else:
                        print("unknown format: %d" % fmt, file=sys.stderr)
                        return False
                    imp = Image.frombytes("P", (w, h), pixeldata)
                    imp.putpalette(palette)
                    imrgb = imp.convert("RGBA")
                    pixrgb = np.array(imrgb)
                    pixp = np.array(imp)
                    pixrgb[pixp == 0] = (0, 0, 0, 0)
                    pixrgb[pixp == 1] = (0, 0, 0, 0x40)
                    pixrgb[pixp == 4] = (0, 0, 0, 0x80)
                    pixrgb[pixp == 5] = (0, 0, 0, 0)
                    pixrgb[pixp == 6] = (0, 0, 0, 0x80)
                    pixrgb[pixp == 7] = (0, 0, 0, 0x40)
                    imrgb = Image.fromarray(pixrgb)
                    im = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
                    im.paste(imrgb, (lm, tm))
                else:
                    im = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
                im.save(outname)
            out_json["sequences"].append({"group": bid, "frames": frames})
        with open(os.path.join(outdir, "%s.json" % bn), "w", encoding="utf-8") as o:
            json.dump(out_json, o, indent=4)
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: %s input.def outdir" % sys.argv[0], file=sys.stderr)
        sys.exit(1)
    ok = extract_def(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
