"""Dungeon's own ambient kinds (loaded by town_full3d_ambient.py stage): bats fluttering out of cave mouths, water
drops falling from stalactites, crystal veins that throb, eyes that open and blink, arcane wisps spiralling up a
spire, bioluminescent spores, fungus lanterns, sulfur vents, a cave's slow breath, algae ripples on the lake and
glow-worm threads on the ceiling.

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), velocity curves in one system all [min, max] pairs, orbital/radial
curves all [min, max] pairs.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

import town_full3d_ambient as TA
import stronghold_full3d_fx as SF


def bat_png(path: Path):
    """A bat silhouette, wings spread with scalloped trailing edges and ears, white on black, 128 x 64."""
    import cv2
    from PIL import Image
    im = np.zeros((64, 128), np.uint8)
    pts = np.array([[64, 24], [56, 22], [40, 14], [20, 12], [4, 20], [12, 26], [18, 36], [26, 32], [32, 42],
                    [40, 36], [48, 44], [56, 38], [64, 46], [72, 38], [80, 44], [88, 36], [96, 42], [102, 32],
                    [110, 36], [116, 26], [124, 20], [108, 12], [88, 14], [72, 22]], np.int32)
    cv2.fillPoly(im, [pts], 255)
    cv2.ellipse(im, (64, 32), (5, 10), 0, 0, 360, 255, -1)
    cv2.fillPoly(im, [np.array([[59, 24], [60, 15], [63, 22], [65, 22], [68, 15], [69, 24]], np.int32)], 255)
    im = cv2.GaussianBlur(im, (0, 0), 0.7)
    path.parent.mkdir(parents=True, exist_ok=True)
    TA.unlink(path)
    Image.fromarray(np.dstack([im] * 3)).save(path)


def k_bats(X: TA.K, nm):
    """Bats fluttering in and out of a cave mouth: radius (px of the loop they swing), count (alive), period (s per
    loop), span (px wingspan), life (s; each bat fades in from and back into the dark), colour (dark), flap (wing
    beats per life, at most 3 -- the size curve has 8 keys), out (as for birds)."""
    pth = TA.S.STAGE / X.key / "amb_bat.png"
    bat_png(pth)
    asset = f"{TA.S.ASSET_ROOT}/{X.key}/amb_bat.png"
    mat = X.M.material("Homm3ConfluxVfxUber", [X.M.tex("_Texture", asset, clamp=True),
                                               X.M.tex("_Mask", asset, clamp=True)],
                       {"_Min": 0.05, "_Max": 0.5, "_Lerp": 1.0, "_Multiply": 1.0, "_Blend": 1.0, "_xSpeed01": 0,
                        "_ySpeed01": 0, "_xSpeed02": 0, "_ySpeed02": 0, "_UseTwo": 0.0, "_CameraOffset": 0.0,
                        "_UseCamOffset": 0.0}, {"_Color": X.col([0.07, 0.06, 0.06]) + [1.0]})
    r = X.px("radius", 40)
    per = float(X.e.get("period", 3.0))
    n = int(X.e.get("count", 3))
    span = X.px("span", 6)
    life = float(X.e.get("life", per * 1.2))
    # wing beats: the vertical size snaps between spread and folded (8 keys: 3.5 beats over a life)
    flap = [0, 1, 0.14, 0.5, 0.28, 1, 0.43, 0.5, 0.57, 1, 0.71, 0.5, 0.86, 1, 1, 0.55]
    w = 2 * math.pi / per
    return [X.group(nm, [SF.psys("bats", mat, lifetime=[life * 0.8, life * 1.2], speed=[0], size=[span * 0.8, span],
                                 sizeY=[span * 0.55, span * 0.65], sizeKeys=[0, 1, 1, 1], sizeYKeys=flap,
                                 rate=round(n / life, 3), maxParticles=n * 3, shape="circle", radius=r,
                                 radiusThickness=0.5, shapeRot=[90, 0, 0], orbitalY=[w * 0.8, w * 1.25],
                                 radial=[-r * 0.05, r * 0.05], velX=[-X.m * 2, X.m * 2], velY=[-X.m * 1.5, X.m * 2.5],
                                 velZ=[-X.m, X.m], color=[1, 1, 1, 1], alphaKeys=[0, 0, 0.15, 1, 0.85, 1, 1, 0],
                                 noise=r * 0.35, noiseFreq=1.4, noiseScroll=0.8, customUV=False)])]


def k_drips(X: TA.K, nm):
    """Water drops falling from stalactite tips: w (px, the band of tips), fall (px a drop travels), rate (/s), drop
    (px), colour (pale wet glint), life (s)."""
    w = X.px("w", 60)
    life = float(X.e.get("life", 0.9))
    v = X.px("fall", 60) / life
    rate = float(X.e.get("rate", 1.5))
    sp = X.px("drop", 1.6)
    return [X.group(nm, [SF.psys("drips", X.A["glint"], lifetime=[life * 0.85, life * 1.15], speed=[0],
                                 velX=[0, 0], velY=[-v * 1.15, -v * 0.85], velZ=[0, 0],
                                 size=[sp * 0.7, sp * 1.1], rate=rate, maxParticles=max(6, int(rate * life * 3)),
                                 shape="box", shapeScale=[w, X.m, X.m], color=X.col([0.7, 0.85, 0.95]) + [1.0],
                                 alphaKeys=[0, 0, 0.1, 1, 0.8, 0.8, 1, 0], sizeKeys=[0, 0.6, 0.2, 1, 1, 0.8],
                                 customUV=False)])]


THROB = [0, 0, 0.35, 0.15, 0.5, 1, 0.62, 0.25, 0.8, 0.6, 1, 0]   # a slow double heartbeat over one life


def k_crystal_pulse(X: TA.K, nm):
    """A crystal vein in the rock that throbs: soft glow cores spread over a box swelling and fading in a double beat,
    with a few hard sparks on the facets. w, h (px), core (px), count (cores alive), period (s per beat), colour,
    colour2 (cores pick between the two), intensity (0..1), spark (px), sparks (/s)."""
    w, h = X.px("w", 40), X.px("h", 30)
    per = float(X.e.get("period", 4.0))
    n = int(X.e.get("count", 3))
    core = X.px("core", 10)
    c1 = X.col([0.7, 0.5, 1.0])
    c2 = [float(x) for x in X.e.get("colour2", c1)]
    a = float(X.e.get("intensity", 0.35))
    sp = X.px("spark", 2.6)
    rate = float(X.e.get("sparks", 1.0))
    return [X.group(nm, [SF.psys("crystal_core", X.A["glow"], lifetime=[per * 0.9, per * 1.1], speed=[0],
                                 size=[core * 0.7, core * 1.3], rate=round(n / per, 3), maxParticles=n * 2 + 2,
                                 shape="box", shapeScale=[w, h, min(w, h) * 0.1], color=c1 + [a], color2=c2 + [a],
                                 alphaKeys=THROB, sizeKeys=[0, 0.7, 0.5, 1, 1, 0.8], customUV=False),
                         SF.psys("crystal_spark", X.A["glint"], lifetime=[0.25, 0.5], speed=[0],
                                 size=[sp * 0.6, sp * 1.2], rate=rate, maxParticles=8, shape="box",
                                 shapeScale=[w, h, min(w, h) * 0.1], color=[1, 1, 1, 1], color2=c2 + [1.0],
                                 alphaKeys=[0, 0, 0.2, 1, 1, 0], sizeKeys=[0, 0.2, 0.3, 1, 1, 0],
                                 rotation=[0, 90], customUV=False)])]


def k_eye_flicker(X: TA.K, nm):
    """Eyes that slowly open, stare, blink once and close (the beholder pillar, the Guardian's sockets, a manticore in
    its den): w, h (px, where eyes may open), eye (px), count (open at once), life (s an eye stays open), colour,
    intensity (0..1)."""
    w, h = X.px("w", 30), X.px("h", 30)
    life = float(X.e.get("life", 4.5))
    n = int(X.e.get("count", 2))
    e = X.px("eye", 5)
    a = float(X.e.get("intensity", 0.6))
    blink = [0, 0.15, 0.15, 1, 0.55, 1, 0.6, 0.08, 0.66, 1, 0.9, 1, 1, 0.1]
    return [X.group(nm, [SF.psys("eyes", X.A["glow"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[e * 1.6, e * 2.0], sizeY=[e * 0.8, e * 1.0], sizeKeys=[0, 1, 1, 1],
                                 sizeYKeys=blink, rate=round(n / life, 3), maxParticles=n * 2 + 1, shape="box",
                                 shapeScale=[w, h, min(w, h) * 0.1], color=X.col([1.0, 0.85, 0.3]) + [a],
                                 alphaKeys=[0, 0, 0.15, 1, 0.85, 1, 1, 0], customUV=False)])]


def k_arcane_wisps(X: TA.K, nm):
    """Arcane wisps winding up round a spire in a tightening helix and burning out at the top: radius (px at the base),
    rise (px), period (s per turn), count (alive), spark (px), colour, colour2, life (s)."""
    r = X.px("radius", 24)
    life = float(X.e.get("life", 4.0))
    vy = X.px("rise", 60) / life
    per = float(X.e.get("period", 2.2))
    n = int(X.e.get("count", 6))
    sp = X.px("spark", 3.2)
    w = 2 * math.pi / per
    c1 = X.col([0.72, 0.45, 1.0])
    c2 = [float(x) for x in X.e.get("colour2", [0.45, 0.8, 1.0])]
    return [X.group(nm, [SF.psys("wisps", X.A["glint"], lifetime=[life * 0.85, life * 1.15], speed=[0],
                                 size=[sp * 0.7, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="circle", radius=r, radiusThickness=0.05, shapeRot=[90, 0, 0],
                                 orbitalX=[0, 0], orbitalY=[w * 0.9, w * 1.1], orbitalZ=[0, 0],
                                 radial=[-r / life * 0.7, -r / life * 0.5],
                                 velX=[0, 0], velY=[vy * 0.85, vy * 1.15], velZ=[0, 0],
                                 color=c1 + [1.0], color2=c2 + [1.0], alphaKeys=[0, 0, 0.1, 1, 0.7, 0.9, 1, 0],
                                 sizeKeys=[0, 0.6, 0.15, 1, 0.75, 0.8, 1, 0.1], customUV=False)])]


def k_spores(X: TA.K, nm):
    """Bioluminescent spores shed off fungus caps: born over a band, they lift, wander on a slow lazy noise and
    twinkle out. w (px), rise (px over a life), rate (/s), spore (px), colour, colour2, life (s)."""
    w = X.px("w", 50)
    life = float(X.e.get("life", 5.0))
    vy = X.px("rise", 30) / life
    rate = float(X.e.get("rate", 2.0))
    sp = X.px("spore", 2.4)
    c1 = X.col([0.6, 1.0, 0.5])
    c2 = [float(x) for x in X.e.get("colour2", [1.0, 0.85, 0.4])]
    return [X.group(nm, [SF.psys("spores", X.A["glint"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 velX=[-vy * 0.3, vy * 0.3], velY=[vy * 0.5, vy * 1.2], velZ=[-vy * 0.2, vy * 0.2],
                                 size=[sp * 0.5, sp * 1.2], rate=rate, maxParticles=max(8, int(rate * life * 2)),
                                 shape="box", shapeScale=[w, X.m * 3, w * 0.3], color=c1 + [1.0], color2=c2 + [1.0],
                                 alphaKeys=[0, 0, 0.15, 1, 0.35, 0.4, 0.55, 1, 0.75, 0.35, 1, 0],
                                 noise=w * 0.25, noiseFreq=0.25, noiseScroll=0.2, customUV=False)])]


def k_fungus_lantern(X: TA.K, nm):
    """A fungus-cap lantern (dungeon street light): a soft glow breathing slowly, each light drifting between two hues,
    with a faint halo. size (px), period (s), colour, colour2, intensity (0..1)."""
    s = X.px("size", 12)
    per = float(X.e.get("period", 4.0))
    a = float(X.e.get("intensity", 0.4))
    c1 = X.col([0.55, 1.0, 0.75])
    c2 = [float(x) for x in X.e.get("colour2", [1.0, 0.75, 0.4])]
    return [X.group(nm, [SF.psys("fungus_core", X.A["glow"], lifetime=[per * 0.8, per * 1.2], speed=[0],
                                 size=[s * 0.8, s * 1.1], rate=round(2.2 / per, 3), maxParticles=5, radius=s * 0.03,
                                 color=c1 + [a], color2=c2 + [a], alphaKeys=[0, 0, 0.4, 1, 0.7, 0.8, 1, 0],
                                 customUV=False),
                         SF.psys("fungus_halo", X.A["glow"], lifetime=[per * 1.5, per * 2.0], speed=[0],
                                 size=[s * 2.4, s * 3.0], rate=round(1.2 / per, 3), maxParticles=3, radius=s * 0.03,
                                 color=c1 + [a * 0.3], alphaKeys=[0, 0, 0.5, 1, 1, 0], customUV=False)])]


def k_sulfur_vent(X: TA.K, nm):
    """Heavy sulfur fumes welling out of a heap and rolling sideways along the ground rather than rising: w (px), rise
    (px), spread (px/s sideways), puff (px), colour, alpha, rate (/s), life (s)."""
    w = X.px("w", 40)
    life = float(X.e.get("life", 5.0))
    vy = X.px("rise", 18) / life
    vx = X.px("spread", 6)
    sz = X.px("puff", 16)
    rate = float(X.e.get("rate", 1.6))
    return [X.group(nm, [SF.psys("sulfur", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-vx, vx], velY=[vy * 0.5, vy * 1.1], velZ=[-vx * 0.3, vx * 0.3],
                                 size=[sz * 0.7, sz * 1.1], rate=rate, maxParticles=max(6, int(rate * life * 2)),
                                 shape="box", shapeScale=[w, X.m * 2, w * 0.3],
                                 color=X.col([0.85, 0.8, 0.35]) + [X.op(0.3)],
                                 alphaKeys=TA.sqk([0, 0, 0.25, 1, 0.55, 0.75, 1, 0]), sizeKeys=[0, 0.5, 1, 2.6],
                                 rotation=[0, 360], rotSpeed=[-12, 12], noise=sz * 0.2, noiseFreq=0.3,
                                 customUV=False)])]


def k_cave_breath(X: TA.K, nm):
    """A cave's slow breath: warm haze exhaled from a mouth in long swells, drifting out and up (the dragon's lair, the
    labyrinth): w (px of the mouth), reach (px it drifts), dir [dx, dy] (screen, y down), puff (px), colour, alpha,
    life (s), count (alive)."""
    w = X.px("w", 40)
    life = float(X.e.get("life", 6.0))
    v = X.px("reach", 50) / life
    dx, dy = X.e.get("dir", [0.3, -1])
    nd = math.hypot(dx, dy) or 1
    sz = X.px("puff", 24)
    n = int(X.e.get("count", 4))
    return [X.group(nm, [SF.psys("breath", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[v * dx / nd * 0.7, v * dx / nd * 1.3],
                                 velY=[-v * dy / nd * 0.7, -v * dy / nd * 1.3], velZ=[-v * 0.1, v * 0.1],
                                 size=[sz * 0.7, sz * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, w * 0.2, w * 0.2],
                                 color=X.col([0.6, 0.4, 0.3]) + [X.op(0.2)],
                                 alphaKeys=TA.sqk([0, 0, 0.3, 1, 0.45, 0.6, 0.6, 0.9, 1, 0]),
                                 sizeKeys=[0, 0.4, 1, 2.0], rotation=[0, 360], rotSpeed=[-10, 10], noise=sz * 0.25,
                                 noiseFreq=0.35, customUV=False)])]


def k_lake_shimmer(X: TA.K, nm):
    """Glowing algae stirred on still underground water: flat rings that open out on the surface and fade. w, h (px),
    ring (px across at full size), rate (/s), life (s), colour, intensity (0..1)."""
    w, h = X.px("w", 300), X.px("h", 80)
    ring = X.px("ring", 26)
    life = float(X.e.get("life", 3.0))
    rate = float(X.e.get("rate", 1.5))
    a = float(X.e.get("intensity", 0.3))
    return [X.group(nm, [SF.psys("shimmer", X.A["glow"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[ring * 0.8, ring * 1.2], sizeY=[ring * 0.2, ring * 0.28],
                                 sizeKeys=[0, 0.2, 1, 1.3], sizeYKeys=[0, 0.2, 1, 1.3], rate=rate,
                                 maxParticles=max(6, int(rate * life * 2)), shape="box",
                                 shapeScale=[w, h * 0.2, h], color=X.col([0.4, 1.0, 0.85]) + [a],
                                 alphaKeys=[0, 0, 0.2, 1, 1, 0], customUV=False)])]


def k_glowworms(X: TA.K, nm):
    """Glow-worm threads hanging from the cavern roof: still, thin vertical beads of cold light that brighten and dim
    out of step. w, h (px), count (alive), bead (px), colour, life (s)."""
    w, h = X.px("w", 200), X.px("h", 80)
    life = float(X.e.get("life", 7.0))
    n = int(X.e.get("count", 14))
    b = X.px("bead", 2.4)
    return [X.group(nm, [SF.psys("glowworms", X.A["glint"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 size=[b * 0.7, b * 1.1], sizeY=[b * 2.2, b * 4.0], rate=round(n / life, 3),
                                 maxParticles=n * 2, shape="box", shapeScale=[w, h, w * 0.1],
                                 color=X.col([0.45, 0.9, 1.0]) + [1.0], color2=[0.7, 1.0, 0.85, 1.0],
                                 alphaKeys=[0, 0, 0.3, 0.8, 0.5, 0.4, 0.7, 1, 1, 0], customUV=False)])]


KINDS = {"bats": k_bats, "drips": k_drips, "crystal_pulse": k_crystal_pulse, "eye_flicker": k_eye_flicker,
         "arcane_wisps": k_arcane_wisps, "spores": k_spores, "fungus_lantern": k_fungus_lantern,
         "sulfur_vent": k_sulfur_vent, "cave_breath": k_cave_breath, "lake_shimmer": k_lake_shimmer,
         "glowworms": k_glowworms}
