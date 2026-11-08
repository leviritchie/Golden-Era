#!/usr/bin/env python3
"""Eye-authored landmarks for lizardman g00_move (7 frames)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crusader_author_common import draw_overlay, joint_dict, write_authored_clip

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
ART = ROOT / "artifacts/lizardman_pose_pipeline"
FRAMES = ART / "source_frames" / "nn_upscale_g00_move"
OUT = ART / "out_fit" / "g00_move_authored"

# Facing-right walk; R*=nearer viewer. Bow on back (f0-f2,f6) or held (f3-f5).
# Each tuple eye-mapped against NN sprites 1090x1250.
FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — bow on back; R(near) leg forward, L(far) trailing
        "Nose": (889, 500),
        "Neck": (478, 572),
        "RShoulder": (480, 596),
        "RElbow": (500, 698),
        "RWrist": (450, 774),
        "WeaponTip": (520, 360),
        "LShoulder": (510, 585),
        "LElbow": (545, 668),
        "LWrist": (520, 738),
        "MidHip": (445, 810),
        "RHip": (555, 678),
        "RKnee": (565, 800),
        "RAnkle": (620, 1069),
        "LHip": (490, 665),
        "LKnee": (360, 820),
        "LAnkle": (320, 1077),
    },
    {  # f01 — pass; bow on back
        "Nose": (889, 490),
        "Neck": (468, 578),
        "RShoulder": (470, 600),
        "RElbow": (490, 702),
        "RWrist": (440, 778),
        "WeaponTip": (480, 350),
        "LShoulder": (500, 590),
        "LElbow": (535, 672),
        "LWrist": (510, 742),
        "MidHip": (435, 815),
        "RHip": (545, 682),
        "RKnee": (555, 805),
        "RAnkle": (600, 1088),
        "LHip": (480, 670),
        "LKnee": (350, 825),
        "LAnkle": (310, 1080),
    },
    {  # f02 — mid-stride gather; bow on back
        "Nose": (879, 490),
        "Neck": (460, 590),
        "RShoulder": (465, 605),
        "RElbow": (485, 708),
        "RWrist": (435, 782),
        "WeaponTip": (570, 360),
        "LShoulder": (495, 595),
        "LElbow": (530, 678),
        "LWrist": (505, 748),
        "MidHip": (430, 820),
        "RHip": (540, 688),
        "RKnee": (550, 810),
        "RAnkle": (545, 1095),
        "LHip": (475, 675),
        "LKnee": (345, 830),
        "LAnkle": (305, 1085),
    },
    {  # f03 — bow held; upper gold tip high-right
        "Nose": (949, 530),
        "Neck": (450, 610),
        "RShoulder": (455, 640),
        "RElbow": (485, 720),
        "RWrist": (520, 790),
        "WeaponTip": (799, 400),
        "LShoulder": (485, 620),
        "LElbow": (545, 680),
        "LWrist": (600, 730),
        "MidHip": (400, 860),
        "RHip": (510, 687),
        "RKnee": (555, 811),
        "RAnkle": (540, 1050),
        "LHip": (620, 687),
        "LKnee": (700, 820),
        "LAnkle": (730, 979),
    },
    {  # f04 — deep crouch; bow held overhead
        "Nose": (899, 500),
        "Neck": (410, 688),
        "RShoulder": (395, 728),
        "RElbow": (420, 798),
        "RWrist": (465, 848),
        "WeaponTip": (859, 380),
        "LShoulder": (445, 708),
        "LElbow": (495, 758),
        "LWrist": (555, 808),
        "MidHip": (375, 910),
        "RHip": (500, 900),
        "RKnee": (520, 1000),
        "RAnkle": (530, 1135),
        "LHip": (420, 895),
        "LKnee": (460, 1005),
        "LAnkle": (500, 1140),
    },
    {  # f05 — bow held; far leg forward
        "Nose": (889, 520),
        "Neck": (400, 688),
        "RShoulder": (385, 728),
        "RElbow": (410, 798),
        "RWrist": (455, 848),
        "WeaponTip": (859, 400),
        "LShoulder": (435, 708),
        "LElbow": (485, 758),
        "LWrist": (545, 798),
        "MidHip": (365, 905),
        "RHip": (490, 895),
        "RKnee": (450, 1005),
        "RAnkle": (420, 1135),
        "LHip": (410, 890),
        "LKnee": (480, 995),
        "LAnkle": (530, 1125),
    },
    {  # f06 — bow on back; near leg trails, far leg leads
        "Nose": (899, 570),
        "Neck": (448, 590),
        "RShoulder": (470, 602),
        "RElbow": (490, 705),
        "RWrist": (440, 780),
        "WeaponTip": (560, 360),
        "LShoulder": (500, 595),
        "LElbow": (535, 675),
        "LWrist": (510, 745),
        "MidHip": (430, 825),
        "RHip": (500, 690),
        "RKnee": (340, 830),
        "RAnkle": (310, 1085),
        "LHip": (560, 688),
        "LKnee": (580, 810),
        "LAnkle": (560, 1050),
    },
]


def main() -> int:
    # Patch unitSid in output after write_authored_clip (common helper hardcodes crusader).
    OUT.mkdir(parents=True, exist_ok=True)
    result = write_authored_clip(
        clip_id="g00_move",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "g00 move walk facing-right; R*=nearer viewer; Nose=snout tip; "
            "WeaponTip=upper bow tip (on back f0-f2,f6; held f3-f5); "
            "re-eyed all 7 NN sprites; not LK track"
        ),
    )
    kpt_path = Path(result["keypoints"])
    doc = json.loads(kpt_path.read_text(encoding="utf-8"))
    doc["unitSid"] = "h3_lizardman"
    kpt_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    result["unitSid"] = "h3_lizardman"
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
