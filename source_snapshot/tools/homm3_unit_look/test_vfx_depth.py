"""vfx_depth: the unitPlane card is the DEF grid from the sprite camera, the classifier splits pieces as
documented, and the spec gate refuses malformed opt-in blocks.   python tools/homm3_unit_look/test_vfx_depth.py"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vfx_depth as VD  # noqa: E402

# the retarget sprite camera convention (azimuth -25 deg, elevation 10 deg from the unit front -y)
CAM = {"right": [0.9064682722091675, -0.422274112701416, 0.0],
       "up": [0.07344701141119003, 0.15766391158103943, 0.984757661819458],
       "forward": [0.41583767533302307, 0.8926515579223633, -0.17393209040164948], "pxPerUnit": 46.3}
CTX = {"vmeta": {"front": [0.0, -1.0, 0.0]}, "spritecam": CAM}


def test_cards_are_the_def_grid_from_the_sprite_camera():
    cv = VD.card_vectors(CTX)
    r, u, ppu = np.array(CAM["right"]), np.array(CAM["up"]), CAM["pxPerUnit"]
    du, dv = cv["sagittal"]
    assert abs(du @ r * ppu - 1) < 1e-9 and abs(du @ u) < 1e-9
    assert abs(dv @ r) < 1e-9 and abs(-dv @ u * ppu - 1) < 1e-9
    f, left, z = VD.unit_axes(CTX)
    assert abs(du @ left) < 1e-12 and abs(cv["cross"][0] @ z) < 1e-12        # sagittal in (front, up); cross in (front, left)
    assert VD.card_weights(np.array(CAM["forward"]), CTX, VD.DEFAULT_FADE)["sagittal"] == 1.0


def test_weights_turn_with_the_facing():
    f, left, z = VD.unit_axes(CTX)
    for az, want in ((-60, 1.0), (60, 1.0), (0, 0.0), (180, 0.0)):
        a, e = math.radians(az), math.radians(40)
        view = -((f * math.cos(a) + left * math.sin(a)) * math.cos(e) + z * math.sin(e))
        w = VD.card_weights(view, CTX, VD.DEFAULT_FADE)
        assert w["sagittal"] == want and w["cross"] == 1 - want, (az, w)


def test_warp_card_is_identity_in_the_sprite_view():
    cv = VD.card_vectors(CTX)
    r, u, ppu = np.array(CAM["right"]), np.array(CAM["up"]), CAM["pxPerUnit"]
    A, t = np.vstack([r * ppu, -u * ppu]), np.array([50.0, 40.0])
    cell = np.zeros((10, 16, 4), np.float32)
    cell[2:5, 3:12] = [1, 0.5, 0.25, 1]
    anc = np.array([0.1, -0.2, 0.3])
    got = VD.warp_card((80, 100), cell, anc, cv["sagittal"][0], cv["sagittal"][1], A, t)
    ref = VD.paste_billboard((80, 100), cell, A @ anc + t, 1.0)
    assert np.abs(got - ref).max() <= 1 / 255 + 1e-6      # paste_billboard round-trips through uint8


def test_piece_classes():
    m = np.zeros((60, 80), bool)
    m[28:33, 38:43] = True            # round, on the origin
    m[28:33, 60:66] = True            # round, 22 px away
    m[10:12, 10:40] = True            # a streak (card)
    m[44:52, 40:48] = True            # round, detached, below the origin: displaced
    m[31:37, 10:16] = True            # round, far: displaced
    out, rec = VD.split_pieces(m, (40.0, 30.0), VD.DEFAULT_ISO)
    assert out["isotropic"][30, 40] and out["displaced"][30, 62] and out["card"][11, 20] and out["displaced"][34, 12] and out["displaced"][48, 44]
    # a round blob attached to the emitter goes to the card (a displaced cell would detach it)
    j = np.zeros((60, 80), bool)
    j[26:35, 41:56] = True
    out, rec = VD.split_pieces(j, (40.0, 30.0), VD.DEFAULT_ISO)
    assert [x["class"] for x in rec] == ["card"], rec


def test_spec_gate():
    w = "vfx.layers[0]"
    assert VD.validate_layer({"render": "unitPlane", "unitPlane": {"fade": [0.3, 0.1]}}, w)
    assert VD.validate_layer({"render": "billboard", "unitPlane": {}}, w)
    assert VD.validate_layer({"render": "trail", "trail": {"historyKeys": 0}}, w)
    assert VD.validate_layer({"render": "trail", "trail": {"bogus": 1}}, w)
    assert not VD.validate_layer({"render": "unitPlane", "unitPlane": {"fade": [0.05, 0.25], "isoMaxAspect": 2.5}}, w)
    assert not VD.validate_layer({"render": "trail", "trail": {"bone": "RightHand", "reach": "auto", "historyKeys": 3}}, w)


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
