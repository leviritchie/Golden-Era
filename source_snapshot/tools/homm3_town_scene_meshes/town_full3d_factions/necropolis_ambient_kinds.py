"""Necropolis's own ambient kinds (loaded by town_full3d_ambient.py stage): souls spiralling up in a widening funnel
with comet tails, will-o'-wisp ghost lights wandering, dead leaves tumbling down, green grave mist pooling flat on the
ground, crows flapping in a ragged flock, crows perched on ridges flicking their wings, a sickly light seeping from a
crypt crack with vapour spilling out, paired eye sockets that kindle and dim, carved runes lighting one at a time,
a spectral toll pulse off the bell tower, grave earth stirring, bone dust sifting from a ledge, souls drawn INTO the
necromancy amplifier, candle flames behind given windows, shadow tendrils curling out of a doorway and witchfire
tongues on braziers.

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), velocity curves in one system all [min, max] pairs, orbital/radial
curves all [min, max] pairs. Local +x is screen right, +y up (as the shared kinds assume).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

import town_full3d_ambient as TA
import stronghold_full3d_fx as SF


# ------------------------------------------------------------------------------------------------ silhouettes
def _save(im, path: Path):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    TA.unlink(path)
    Image.fromarray(np.dstack([im] * 3)).save(path)


def crow_png(path: Path):
    """A crow in flight: broad wings with fingered primaries, a wedge tail, a heavy beak; white on black, 128 x 64."""
    import cv2
    im = np.zeros((64, 128), np.uint8)
    wing = np.array([[64, 30], [50, 24], [34, 20], [18, 22], [6, 28], [10, 30], [4, 34], [12, 34], [8, 38], [18, 37],
                     [16, 41], [28, 38], [44, 38], [58, 40], [64, 42]], np.int32)
    cv2.fillPoly(im, [wing], 255)
    cv2.fillPoly(im, [np.array([[128 - x, y] for x, y in wing], np.int32)], 255)
    cv2.ellipse(im, (64, 36), (6, 10), 0, 0, 360, 255, -1)
    cv2.fillPoly(im, [np.array([[59, 44], [69, 44], [72, 56], [56, 56]], np.int32)], 255)   # wedge tail
    cv2.fillPoly(im, [np.array([[61, 27], [67, 27], [64, 19]], np.int32)], 255)             # head + beak
    _save(cv2.GaussianBlur(im, (0, 0), 0.7), path)


def crow_perch_png(path: Path):
    """A crow sitting side-on: hunched body, round head, thick beak, tail angled down, legs; white on black, 64 x 64."""
    import cv2
    im = np.zeros((64, 64), np.uint8)
    cv2.ellipse(im, (30, 34), (14, 10), -20, 0, 360, 255, -1)           # body
    cv2.circle(im, (42, 22), 7, 255, -1)                                # head
    cv2.fillPoly(im, [np.array([[47, 19], [58, 23], [47, 26]], np.int32)], 255)   # beak
    cv2.fillPoly(im, [np.array([[18, 36], [4, 50], [10, 52], [24, 42]], np.int32)], 255)   # tail
    cv2.line(im, (30, 43), (28, 54), 255, 2)
    cv2.line(im, (35, 42), (36, 54), 255, 2)
    _save(cv2.GaussianBlur(im, (0, 0), 0.6), path)


def leaf_png(path: Path):
    """A curled dead leaf with lobes and a stem; white on black, 64 x 64."""
    import cv2
    im = np.zeros((64, 64), np.uint8)
    pts = np.array([[32, 6], [38, 14], [46, 12], [44, 22], [54, 26], [46, 32], [52, 42], [40, 40], [36, 52], [32, 46],
                    [28, 52], [24, 40], [12, 42], [18, 32], [10, 26], [20, 22], [18, 12], [26, 14]], np.int32)
    cv2.fillPoly(im, [pts], 255)
    cv2.line(im, (32, 46), (32, 60), 255, 2)
    _save(cv2.GaussianBlur(im, (0, 0), 0.6), path)


def clod_png(path: Path):
    """A ragged clod of grave earth; white on black, 32 x 32."""
    import cv2
    im = np.zeros((32, 32), np.uint8)
    cv2.fillPoly(im, [np.array([[16, 4], [24, 8], [28, 16], [24, 26], [14, 28], [6, 22], [5, 12], [10, 6]], np.int32)],
                 255)
    _save(cv2.GaussianBlur(im, (0, 0), 0.8), path)


def wisp_png(path: Path):
    """A soft, ragged smoke tendril (taller than wide): a blurred noisy blob, white on black, 64 x 96."""
    import cv2
    rng = np.random.default_rng(7)
    im = np.zeros((96, 64), np.float32)
    for _ in range(14):
        cx, cy = 32 + rng.normal(0, 6), rng.uniform(18, 80)
        cv2.circle(im, (int(cx), int(cy)), int(rng.uniform(6, 13)), float(rng.uniform(0.5, 1.0)), -1)
    im = cv2.GaussianBlur(im, (0, 0), 6)
    im = np.clip(im / max(im.max(), 1e-6) * 255, 0, 255).astype(np.uint8)
    _save(im, path)


def sil_mat(X: TA.K, name: str, draw, colour):
    """An alpha-blended silhouette material (as the shared birds) from a generated white-on-black png."""
    pth = TA.S.STAGE / X.key / f"amb_nc_{name}.png"
    draw(pth)
    asset = f"{TA.S.ASSET_ROOT}/{X.key}/amb_nc_{name}.png"
    return X.M.material("Homm3ConfluxVfxUber", [X.M.tex("_Texture", asset, clamp=True),
                                                X.M.tex("_Mask", asset, clamp=True)],
                        {"_Min": 0.05, "_Max": 0.5, "_Lerp": 1.0, "_Multiply": 1.0, "_Blend": 1.0, "_xSpeed01": 0,
                         "_ySpeed01": 0, "_xSpeed02": 0, "_ySpeed02": 0, "_UseTwo": 0.0, "_CameraOffset": 0.0,
                         "_UseCamOffset": 0.0}, {"_Color": list(colour) + [1.0]})


def _c2(X: TA.K, default):
    return [float(x) for x in X.e.get("colour2", default)]


# ------------------------------------------------------------------------------------------------ souls
def k_soul_spiral(X: TA.K, nm):
    """Souls winding up round a pillar in a WIDENING funnel, each a comet with a pale tail (stretched along its path):
    radius (px at the base), rise (px), period (s per turn), count (alive), soul (px), colour, colour2, life (s)."""
    r = X.px("radius", 26)
    life = float(X.e.get("life", 5.0))
    vy = X.px("rise", 120) / life
    per = float(X.e.get("period", 3.0))
    n = int(X.e.get("count", 7))
    s = X.px("soul", 7)
    w = 2 * math.pi / per
    return [X.group(nm, [SF.psys("souls", X.A["glow"], lifetime=[life * 0.85, life * 1.15], speed=[0],
                                 size=[s * 0.8, s * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="circle", radius=r, radiusThickness=0.1, shapeRot=[90, 0, 0],
                                 orbitalX=[0, 0], orbitalY=[w * 0.9, w * 1.1], orbitalZ=[0, 0],
                                 radial=[r / life * 0.3, r / life * 0.6],
                                 velX=[0, 0], velY=[vy * 0.8, vy * 1.2], velZ=[0, 0],
                                 color=X.col([0.55, 1.0, 0.75]) + [float(X.e.get("intensity", 0.7))],
                                 color2=_c2(X, [0.75, 0.9, 1.0]) + [float(X.e.get("intensity", 0.7))],
                                 alphaKeys=[0, 0, 0.15, 1, 0.6, 0.8, 1, 0], sizeKeys=[0, 0.5, 0.2, 1, 1, 0.3],
                                 renderMode=1, lengthScale=1.0, velocityScale=float(X.e.get("tail", 0.35)),
                                 customUV=False)])]


def k_soul_drain(X: TA.K, nm):
    """Souls drawn INTO a point (the amplifier's maw): green sparks born on a wide ring spiral inward, brightening and
    shrinking as they are swallowed. radius (px), period (s per turn), count, spark (px), colour, colour2, life (s),
    rise (px the ring lifts over a life)."""
    r = X.px("radius", 60)
    life = float(X.e.get("life", 3.5))
    per = float(X.e.get("period", 2.5))
    n = int(X.e.get("count", 12))
    sp = X.px("spark", 4)
    vy = X.px("rise", 10) / life
    w = 2 * math.pi / per
    return [X.group(nm, [SF.psys("drain", X.A["glint"], lifetime=[life * 0.9, life * 1.1], speed=[0],
                                 size=[sp * 0.8, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="circle", radius=r, radiusThickness=0.08, shapeRot=[90, 0, 0],
                                 orbitalX=[0, 0], orbitalY=[w * 0.9, w * 1.1], orbitalZ=[0, 0],
                                 radial=[-r / life * 1.0, -r / life * 0.85],
                                 velX=[0, 0], velY=[vy * 0.7, vy * 1.3], velZ=[0, 0],
                                 color=X.col([0.5, 1.0, 0.55]) + [1.0], color2=_c2(X, [0.8, 1.0, 0.9]) + [1.0],
                                 alphaKeys=[0, 0, 0.2, 0.45, 0.75, 1, 1, 0], sizeKeys=[0, 1, 0.8, 0.8, 1, 0.2],
                                 customUV=False)])]


def k_ghost_lights(X: TA.K, nm):
    """Will-o'-wisps: a few cold soft lights wandering on a slow broad noise, swelling and guttering out of step.
    w, h (px), count (alive), wisp (px), colour, colour2, intensity (0..1), life (s), wander (px/s noise)."""
    w, h = X.px("w", 120), X.px("h", 60)
    life = float(X.e.get("life", 8.0))
    n = int(X.e.get("count", 3))
    s = X.px("wisp", 36)
    a = float(X.e.get("intensity", 0.5))
    wd = X.px("wander", 12)          # noise strength (px/s): how far a wisp strays from where it was born
    return [X.group(nm, [SF.psys("wisp_halo", X.A["glow"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 size=[s * 0.8, s * 1.2], rate=round(n / life, 3), maxParticles=n * 2 + 1,
                                 shape="box", shapeScale=[w, h, w * 0.2],
                                 color=X.col([0.55, 0.9, 1.0]) + [a], color2=_c2(X, [0.6, 1.0, 0.7]) + [a],
                                 alphaKeys=[0, 0, 0.18, 1, 0.32, 0.35, 0.5, 0.95, 0.68, 0.25, 0.84, 0.85, 1, 0],
                                 noise=wd, noiseFreq=0.12, noiseScroll=0.06, customUV=False)])]


# ------------------------------------------------------------------------------------------------ ground
def k_grave_mist(X: TA.K, nm):
    """Grave mist pooling flat on the ground: wide low wisps that barely drift, swell and thin (squashed puffs, a
    sickly green-grey). w, h (px), drift (px/s, either way), puff (px across), flat (height share), colour, alpha,
    count, life (s)."""
    w, h = X.px("w", 300), X.px("h", 40)
    life = float(X.e.get("life", 16))
    n = int(X.e.get("count", 7))
    v = X.px("drift", 2)
    sz = X.px("puff", max(float(X.e.get("h", 40)) * 2.5, 80))
    fl = float(X.e.get("flat", 0.4))
    lift = sz * fl * float(X.e.get("lift", 0.3))     # sheets sit ON the ground, not half sunk into it
    return [X.group(nm, [SF.psys("grave_mist", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-v, v], velY=[-v * 0.05, v * 0.1], velZ=[-v * 0.3, v * 0.3],
                                 size=[sz * 0.8, sz * 1.25], sizeY=[sz * fl * 0.8, sz * fl * 1.2],
                                 sizeKeys=[0, 0.7, 0.5, 1, 1, 1.25], sizeYKeys=[0, 0.6, 0.5, 1, 1, 1.1],
                                 rate=round(n / life, 3), maxParticles=n * 2, shape="box",
                                 shapeScale=[w, h * 0.3, h], shapePos=[0, lift, 0],
                                 color=X.col([0.6, 0.72, 0.6]) + [X.op(0.35)],
                                 alphaKeys=TA.sqk([0, 0, 0.3, 1, 0.55, 0.7, 0.75, 1, 1, 0]), rotation=[-8, 8],
                                 customUV=False)])]


def k_dead_leaves(X: TA.K, nm):
    """Dead leaves letting go of a bough and tumbling down on a lazy sway: w (px of bough), fall (px), rate (/s),
    leaf (px), colour (dry brown), life (s), wind (px/s sideways)."""
    mat = sil_mat(X, "leaf", leaf_png, X.col([0.36, 0.25, 0.14]))
    w = X.px("w", 80)
    life = float(X.e.get("life", 6.0))
    v = X.px("fall", 120) / life
    wind = X.px("wind", 6)
    lf = X.px("leaf", 6)
    rate = float(X.e.get("rate", 0.8))
    return [X.group(nm, [SF.psys("leaves", mat, lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[wind * 0.4, wind * 1.4], velY=[-v * 1.2, -v * 0.8], velZ=[-v * 0.1, v * 0.1],
                                 size=[lf * 0.7, lf * 1.2], sizeY=[lf * 0.5, lf * 1.0],
                                 sizeKeys=[0, 1, 1, 1], sizeYKeys=[0, 1, 0.2, 0.3, 0.4, 1, 0.6, 0.25, 0.8, 1, 1, 0.4],
                                 rate=rate, maxParticles=max(6, int(rate * life * 2)), shape="box",
                                 shapeScale=[w, X.m * 6, w * 0.3], color=[1, 1, 1, 1], color2=[0.75, 0.7, 0.6, 1],
                                 alphaKeys=[0, 0, 0.06, 1, 0.85, 1, 1, 0], rotation=[0, 360], rotSpeed=[-160, 160],
                                 noise=w * 0.2 + X.m * 8, noiseFreq=0.35, customUV=False)])]


def k_grave_stir(X: TA.K, nm):
    """Grave earth stirring (the dead digging out): now and then a spurt of brown dust and a few clods flicking up out
    of the hole. w (px of the hole), rise (px), rate (spurts /s), puff (px), colour."""
    mat = sil_mat(X, "clod", clod_png, [0.16, 0.12, 0.09])
    w = X.px("w", 24)
    life = float(X.e.get("life", 1.6))
    vy = X.px("rise", 18) / life
    sz = X.px("puff", 22)
    rate = float(X.e.get("rate", 0.5))
    cl = X.px("clod", 3.5)
    return [X.group(nm, [SF.psys("grave_dust", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-vy * 0.4, vy * 0.4], velY=[vy * 0.6, vy * 1.1], velZ=[-vy * 0.2, vy * 0.2],
                                 size=[sz * 0.7, sz * 1.1], rate=rate, maxParticles=8, shape="box",
                                 shapeScale=[w, X.m * 2, w * 0.4], color=X.col([0.62, 0.54, 0.44]) + [X.op(float(X.e.get("alpha", 0.6)))],
                                 alphaKeys=TA.sqk([0, 0, 0.1, 1, 0.4, 0.5, 1, 0]), sizeKeys=[0, 0.4, 1, 1.8],
                                 rotation=[0, 360], rotSpeed=[-20, 20], customUV=False),
                         SF.psys("grave_clods", mat, lifetime=[0.5, 0.9], speed=[0],
                                 velX=[-vy * 1.2, vy * 1.2], velY=[vy * 1.5, vy * 2.5], velZ=[-vy * 0.3, vy * 0.3],
                                 size=[cl * 0.6, cl * 1.2], rate=rate * 3, maxParticles=10, shape="box",
                                 shapeScale=[w * 0.6, X.m, w * 0.3], color=[1, 1, 1, 1],
                                 alphaKeys=[0, 0, 0.1, 1, 0.7, 1, 1, 0], sizeKeys=[0, 1, 1, 0.6],
                                 rotation=[0, 360], rotSpeed=[-200, 200], customUV=False)])]


def k_bone_dust(X: TA.K, nm):
    """Pale bone dust sifting down off a ledge in slow, swaying specks: w (px), fall (px), rate (/s), speck (px),
    colour, life (s)."""
    w = X.px("w", 100)
    life = float(X.e.get("life", 4.0))
    v = X.px("fall", 40) / life
    sp = X.px("speck", 3.0)
    rate = float(X.e.get("rate", 3))
    return [X.group(nm, [SF.psys("bone_dust", X.A["glint"], lifetime=[life * 0.7, life * 1.2], speed=[0],
                                 velX=[-v * 0.2, v * 0.2], velY=[-v * 1.2, -v * 0.7], velZ=[-v * 0.1, v * 0.1],
                                 size=[sp * 0.6, sp * 1.1], rate=rate, maxParticles=max(8, int(rate * life * 2)),
                                 shape="box", shapeScale=[w, X.m * 3, w * 0.2],
                                 color=X.col([0.85, 0.82, 0.7]) + [1.0],
                                 alphaKeys=[0, 0, 0.15, 0.8, 0.5, 0.5, 0.7, 0.75, 1, 0],
                                 noise=X.m * 4, noiseFreq=0.6, customUV=False)])]


# ------------------------------------------------------------------------------------------------ crows
CROW_FLAP = [0, 1, 0.06, 0.3, 0.12, 1, 0.18, 0.3, 0.24, 1, 0.62, 1, 0.68, 0.3, 0.74, 1]   # flap-flap-flap, glide, flap


def k_crows(X: TA.K, nm):
    """A ragged flock of crows: flap-flap-glide on a loose loop with jittery turns (not a soaring raptor). radius (px),
    count, period (s per loop), span (px wingspan), life (s), colour (black), out (as for birds)."""
    mat = sil_mat(X, "crow", crow_png, X.col([0.05, 0.05, 0.06]))
    r = X.px("radius", 50)
    per = float(X.e.get("period", 9.0))
    n = int(X.e.get("count", 4))
    span = X.px("span", 9)
    life = float(X.e.get("life", per * 1.4))
    w = 2 * math.pi / per
    return [X.group(nm, [SF.psys("crows", mat, lifetime=[life * 0.9, life * 1.1], speed=[0], size=[span * 0.85, span],
                                 sizeY=[span * 0.5, span * 0.55], sizeKeys=[0, 1, 1, 1], sizeYKeys=CROW_FLAP,
                                 rate=round(n / life, 3), maxParticles=n * 2, shape="circle", radius=r,
                                 radiusThickness=0.5, shapeRot=[90, 0, 0], orbitalX=[0, 0],
                                 orbitalY=[-w * 1.2, -w * 0.8], orbitalZ=[0, 0], radial=[-r * 0.02, r * 0.02],
                                 velX=[-X.m, X.m], velY=[-X.m * 0.8, X.m * 0.8], velZ=[-X.m, X.m],
                                 color=[1, 1, 1, 1], alphaKeys=[0, 0, 0.06, 1, 0.94, 1, 1, 0],
                                 noise=r * 0.2, noiseFreq=0.5, noiseScroll=0.3, customUV=False)])]


def k_crow_perch(X: TA.K, nm):
    """Crows perched along a ridge, each sitting a long while and now and then flicking its wings (a quick
    widening): w (px of ridge), count (sitting), size (px tall), life (s each sits), colour."""
    mat = sil_mat(X, "crow_perch", crow_perch_png, X.col([0.05, 0.05, 0.06]))
    w = X.px("w", 40)
    s = X.px("size", 7)
    life = float(X.e.get("life", 22))
    n = int(X.e.get("count", 2))
    flick = [0, 1, 0.42, 1, 0.45, 1.7, 0.48, 1, 0.8, 1, 0.83, 1.6, 0.86, 1, 1, 1]
    return [X.group(nm, [SF.psys("perched", mat, lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[s * 0.9, s * 1.1], sizeY=[s * 0.9, s * 1.1], sizeKeys=flick,
                                 sizeYKeys=[0, 1, 1, 1], rate=round(n / life, 3), maxParticles=n * 2 + 1,
                                 shape="box", shapeScale=[w, X.m, X.m], color=[1, 1, 1, 1],
                                 alphaKeys=[0, 0, 0.03, 1, 0.97, 1, 1, 0], customUV=False)])]


# ------------------------------------------------------------------------------------------------ crypt lights
def k_crypt_seep(X: TA.K, nm):
    """A sickly light leaking from a crypt crack, breathing slowly, with green vapour spilling out and creeping along
    the ground: w, h (px of the crack), colour, intensity (0..1), period (s per breath), spill (px/s sideways),
    puff (px), alpha (vapour), rate (vapour /s)."""
    w, h = X.px("w", 6), X.px("h", 40)
    per = float(X.e.get("period", 5.0))
    a = float(X.e.get("intensity", 0.4))
    v = X.px("spill", 5)
    sz = X.px("puff", 30)
    rate = float(X.e.get("rate", 0.8))
    c = X.col([0.55, 1.0, 0.45])
    return [X.group(nm, [SF.psys("seep_light", X.A["glow"], lifetime=[per * 0.9, per * 1.1], speed=[0],
                                 size=[max(w, h * 0.3) * 1.6, max(w, h * 0.3) * 2.0], sizeY=[h * 1.1, h * 1.3],
                                 rate=round(2.0 / per, 3), maxParticles=5, shape="box",
                                 shapeScale=[w * 0.3, h * 0.2, X.m], color=c + [a],
                                 alphaKeys=[0, 0, 0.35, 1, 0.5, 0.7, 0.65, 1, 1, 0], customUV=False),
                         SF.psys("seep_vapour", X.A["puff"], lifetime=[per * 0.9, per * 1.3], speed=[0],
                                 velX=[-v, v], velY=[-v * 0.25, v * 0.05], velZ=[-v * 0.4, 0],
                                 size=[sz * 0.6, sz * 1.0], rate=rate, maxParticles=max(6, int(rate * per * 3)),
                                 shape="box", shapeScale=[w, h * 0.6, X.m], color=c + [X.op(float(X.e.get("alpha", 0.3)))],
                                 alphaKeys=TA.sqk([0, 0, 0.2, 1, 0.6, 0.6, 1, 0]), sizeKeys=[0, 0.4, 1, 2.0],
                                 rotation=[0, 360], rotSpeed=[-15, 15], customUV=False)])]


def k_skull_eyes(X: TA.K, nm):
    """A skull's eye sockets kindling: two cold points at sep (px) apart that slowly brighten, hold, and gutter, with a
    soft halo. sep (px), eye (px), colour, intensity (0..1), period (s), tilt (px the right eye sits lower)."""
    sep = X.px("sep", 10)
    e = X.px("eye", 4)
    per = float(X.e.get("period", 4.5))
    a = float(X.e.get("intensity", 0.6))
    tilt = X.px("tilt", 0)
    c = X.col([0.5, 1.0, 0.5])
    keys = [0, 0, 0.3, 0.5, 0.45, 1, 0.6, 0.9, 0.75, 1, 1, 0]
    out = []
    for side, dy in ((-1, 0.0), (1, -tilt)):
        p = [side * sep / 2, dy, 0.0]
        out += [SF.psys(f"eye{'lr'[side > 0]}", X.A["glint"], lifetime=[per * 0.95, per * 1.05], speed=[0],
                        size=[e * 0.9, e * 1.1], rate=round(1.6 / per, 3), maxParticles=3, radius=X.m * 0.05,
                        shapePos=p, color=c + [1.0], alphaKeys=keys, customUV=False),
                SF.psys(f"halo{'lr'[side > 0]}", X.A["glow"], lifetime=[per * 0.95, per * 1.05], speed=[0],
                        size=[e * 3.0, e * 3.6], rate=round(1.6 / per, 3), maxParticles=3, radius=X.m * 0.05,
                        shapePos=p, color=c + [a], alphaKeys=keys, customUV=False)]
    return [X.group(nm, out)]


def k_rune_pulse(X: TA.K, nm):
    """Carved runes lighting up one at a time and fading, like a slow incantation crawling over the stone: w, h (px),
    rune (px wide; drawn 1.8x tall), count (lit at once), life (s), colour, colour2, intensity (halo 0..1)."""
    w, h = X.px("w", 30), X.px("h", 60)
    r = X.px("rune", 4)
    life = float(X.e.get("life", 3.0))
    n = int(X.e.get("count", 2))
    a = float(X.e.get("intensity", 0.3))
    c1 = X.col([0.7, 0.45, 1.0])
    c2 = _c2(X, [0.45, 1.0, 0.7])
    return [X.group(nm, [SF.psys("rune", X.A["glint"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[r * 0.8, r * 1.1], sizeY=[r * 1.6, r * 2.0], rate=round(n / life, 3),
                                 maxParticles=n * 2 + 1, shape="box", shapeScale=[w, h, X.m * 0.2],
                                 color=c1 + [1.0], color2=c2 + [1.0], alphaKeys=[0, 0, 0.25, 1, 0.55, 0.8, 1, 0],
                                 customUV=False),
                         SF.psys("rune_halo", X.A["glow"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[r * 4, r * 5], rate=round(n / life, 3), maxParticles=n * 2 + 1, shape="box",
                                 shapeScale=[w, h, X.m * 0.2], color=c1 + [a], color2=c2 + [a],
                                 alphaKeys=[0, 0, 0.3, 1, 1, 0], customUV=False)])]


def k_toll_pulse(X: TA.K, nm):
    """The bell tolls for the dead: a pale spectral wave swelling out of the belfry every period and fading as it
    widens. size (px across at its widest), period (s), colour, intensity (0..1)."""
    s = X.px("size", 90)
    per = float(X.e.get("period", 7.0))
    a = float(X.e.get("intensity", 0.18))
    return [X.group(nm, [SF.psys("toll", X.A["glow"], lifetime=[per * 0.55, per * 0.6], speed=[0],
                                 size=[s, s], rate=round(1.0 / per, 4), maxParticles=2, radius=X.m * 0.05,
                                 color=X.col([0.7, 0.95, 0.85]) + [a], alphaKeys=[0, 0, 0.06, 1, 0.4, 0.5, 1, 0],
                                 sizeKeys=[0, 0.12, 0.3, 0.6, 1, 1], customUV=False),
                         SF.psys("toll_core", X.A["glow"], lifetime=[per * 0.25, per * 0.3], speed=[0],
                                 size=[s * 0.25, s * 0.3], rate=round(1.0 / per, 4), maxParticles=2,
                                 radius=X.m * 0.05, color=X.col([0.7, 0.95, 0.85]) + [a * 2.2],
                                 alphaKeys=[0, 0, 0.1, 1, 1, 0], customUV=False)])]


# ------------------------------------------------------------------------------------------------ flames, shadow
def k_candle_row(X: TA.K, nm):
    """Candles burning behind given windows: one small flickering flame light per window, each out of step.
    windows: [[dx, dy], ...] px offsets from the anchor (screen, y down); size (px), colour, colour2, intensity."""
    s = X.px("size", 8)
    a = float(X.e.get("intensity", 0.5))
    c1 = X.col([1.0, 0.45, 0.25])
    c2 = _c2(X, [1.0, 0.65, 0.3])
    pats = [[0, 0, 0.1, 1, 0.25, 0.6, 0.45, 1, 0.7, 0.75, 1, 0],
            [0, 0, 0.15, 0.8, 0.3, 1, 0.5, 0.55, 0.75, 1, 1, 0],
            [0, 0, 0.12, 1, 0.4, 0.85, 0.55, 0.5, 0.8, 0.95, 1, 0]]
    out = []
    for i, (dx, dy) in enumerate(X.e.get("windows", [[0, 0]])):
        life = 0.5 + 0.17 * (i % 3)
        out.append(SF.psys(f"candle{i}", X.A["glow"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                           size=[s * 0.85, s * 1.15], sizeY=[s * 1.1, s * 1.4], rate=round(2.8 / life, 3),
                           maxParticles=6, radius=X.m * 0.1, shapePos=[dx * X.m, -dy * X.m, 0.0],
                           color=c1 + [a], color2=c2 + [a], alphaKeys=pats[i % 3], customUV=False))
    return [X.group(nm, out)]


def k_shadow_wisps(X: TA.K, nm):
    """Shadow tendrils curling up out of a dark doorway: near-black alpha smoke that writhes on a tight noise and
    thins as it climbs. w (px), rise (px), puff (px), colour (dark), alpha, rate (/s), life (s)."""
    w = X.px("w", 20)
    life = float(X.e.get("life", 4.0))
    vy = X.px("rise", 40) / life
    sz = X.px("puff", 22)
    rate = float(X.e.get("rate", 1.4))
    mat = sil_mat(X, "shadow", wisp_png, X.col([0.07, 0.05, 0.1]))     # alpha-blended: dark reads (puff does not)
    return [X.group(nm, [SF.psys("shadow", mat, lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-vy * 0.25, vy * 0.25], velY=[vy * 0.6, vy * 1.1], velZ=[-vy * 0.3, 0],
                                 size=[sz * 0.6, sz * 1.0], sizeY=[sz * 1.0, sz * 1.5], sizeKeys=[0, 0.5, 1, 1.4],
                                 sizeYKeys=[0, 0.4, 1, 1.8], rate=rate, maxParticles=max(6, int(rate * life * 2)),
                                 shape="box", shapeScale=[w, X.m * 3, w * 0.3],
                                 color=[1, 1, 1, X.op(float(X.e.get("alpha", 0.55)))],
                                 alphaKeys=TA.sqk([0, 0, 0.2, 1, 0.6, 0.6, 1, 0]), rotation=[-20, 20],
                                 rotSpeed=[-40, 40], noise=sz * 0.08, noiseFreq=0.8, noiseScroll=0.3,
                                 customUV=False)])]


def k_witchfire(X: TA.K, nm):
    """Cold witchfire on a brazier or a staff head: green tongues licking up fast and pinching out, over a steady
    pale glow. width (px), rise (px), tongue (px), colour, colour2, rate (/s), intensity (0..1)."""
    w = X.px("width", 8)
    life = float(X.e.get("life", 0.6))
    vy = X.px("rise", 14) / life
    t = X.px("tongue", 6)
    rate = float(X.e.get("rate", 9))
    a = float(X.e.get("intensity", 0.45))
    c1 = X.col([0.45, 1.0, 0.5])
    c2 = _c2(X, [0.4, 0.9, 1.0])
    return [X.group(nm, [SF.psys("tongues", X.A["glint"], lifetime=[life * 0.6, life * 1.2], speed=[0],
                                 velX=[-vy * 0.1, vy * 0.1], velY=[vy * 0.7, vy * 1.2], velZ=[0, 0],
                                 size=[t * 0.6, t * 0.9], sizeY=[t * 1.2, t * 1.8], sizeKeys=[0, 1, 1, 0.2],
                                 sizeYKeys=[0, 0.6, 0.4, 1, 1, 0.3], rate=rate,
                                 maxParticles=max(10, int(rate * life * 2)), shape="box",
                                 shapeScale=[w, X.m, w * 0.3], color=c1 + [1.0], color2=c2 + [1.0],
                                 alphaKeys=[0, 0, 0.15, 1, 0.6, 0.6, 1, 0], customUV=False),
                         SF.psys("witch_glow", X.A["glow"], lifetime=[0.8, 1.4], speed=[0],
                                 size=[w * 2.6, w * 3.2], rate=2.5, maxParticles=5, radius=X.m * 0.2,
                                 color=c1 + [a], alphaKeys=TA.FLICKER["candle"], customUV=False)])]


def k_forge_spits(X: TA.K, nm):
    """The bone forge spitting: bursts of fat blood-red sparks flung up and out in short arcs off the anvil, trailing
    (stretched along their flight) and dying dull. width (px), rise (px), spark (px), rate (/s), colour, colour2."""
    w = X.px("width", 24)
    life = float(X.e.get("life", 0.9))
    vy = X.px("rise", 50) / life
    sp = X.px("spark", 5)
    rate = float(X.e.get("rate", 6))
    return [X.group(nm, [SF.psys("spits", X.A["glint"], lifetime=[life * 0.6, life * 1.2], speed=[0],
                                 velX=[-vy * 0.6, vy * 0.6], velY=[vy * 0.6, vy * 1.3], velZ=[-vy * 0.2, vy * 0.2],
                                 size=[sp * 0.6, sp * 1.1], rate=rate, maxParticles=max(10, int(rate * life * 2)),
                                 shape="box", shapeScale=[w, X.m * 2, w * 0.3],
                                 color=X.col([1.0, 0.25, 0.15]) + [1.0], color2=_c2(X, [1.0, 0.55, 0.2]) + [1.0],
                                 alphaKeys=[0, 0, 0.08, 1, 0.5, 0.8, 1, 0], sizeKeys=[0, 1, 1, 0.3],
                                 drag=1.5, renderMode=1, lengthScale=1.0, velocityScale=0.06, customUV=False)])]


KINDS = {"forge_spits": k_forge_spits, "soul_spiral": k_soul_spiral, "soul_drain": k_soul_drain, "ghost_lights": k_ghost_lights,
         "grave_mist": k_grave_mist, "dead_leaves": k_dead_leaves, "grave_stir": k_grave_stir,
         "bone_dust": k_bone_dust, "crows": k_crows, "crow_perch": k_crow_perch, "crypt_seep": k_crypt_seep,
         "skull_eyes": k_skull_eyes, "rune_pulse": k_rune_pulse, "toll_pulse": k_toll_pulse,
         "candle_row": k_candle_row, "shadow_wisps": k_shadow_wisps, "witchfire": k_witchfire}
