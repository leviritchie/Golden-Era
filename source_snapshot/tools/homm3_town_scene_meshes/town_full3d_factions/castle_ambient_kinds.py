"""Castle's own ambient kinds (loaded by town_full3d_ambient.py stage): a knightly human kingdom on a bright day.
White doves fluttering round the keep, griffins wheeling high over their tower, pennants snapping on the tower tops,
the lighthouse beam sweeping round, holy light rays fanning down from the Portal of Glory and haloing the Colossus,
a gleam running up a sword blade or across a gilded dome, angel feathers drifting from the portal cloud, monastery
candles and incense threads, the blacksmith's anvil striking in rhythm, practice arrows loosed from the archers'
tower, sword clashes in the barracks yard, dust kicked up by jousting charges, market pigeons that take off and come
back, the waterfall's spray, sun glitter on the lake, an armillary ring of stars round the mage guild, butterflies
over the meadow and swallows skimming it.

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), every velocity curve in one system and every orbital/radial curve
in one system as [min, max] pairs. Gradient keys stay at 8 or fewer per curve (Unity's limit).
Screen axes: local x = right, y = up, z = depth.

Rhythm: a system whose particles all live exactly `period` and whose maxParticles caps the flock / shower emits its
whole cap within a frame or two (rate far above the cap), then nothing until they all die together -- a burst every
period. Every system of one group starts on the same frame, so two systems with the same period stay in step
(the pigeons' take-off and return, the two jousting charges, the beam's two halves).
Half sprites: a beam, a ray, a flag or a dust lane is drawn only in one half of its texture, from the centre out, so
the particle's position is the root (the lamp, the light's source, the flagpole) and scaling / rotating the quad
keeps the root in place.
"""
from __future__ import annotations

import math
import os

import numpy as np

import town_full3d_ambient as TA
import stronghold_full3d_fx as SF
import stronghold_full3d_scene as S


# ------------------------------------------------------------------------------------------------ sprites
def _png(path, im):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    TA.unlink(path)
    im = np.clip(im, 0, 255).astype(np.uint8)
    Image.fromarray(np.dstack([im] * 3)).save(path)


def _draw_dove(path):
    """A dove with its wings raised in a V (the size curve flattens it on the down-stroke), 128 x 64."""
    import cv2
    im = np.zeros((64, 128), np.uint8)
    wing_l = np.array([[60, 38], [44, 26], [24, 12], [8, 6], [16, 16], [30, 30], [46, 40], [58, 44]], np.int32)
    wing_r = wing_l.copy()
    wing_r[:, 0] = 128 - wing_r[:, 0]
    cv2.fillPoly(im, [wing_l, wing_r], 255)
    cv2.ellipse(im, (64, 42), (8, 6), 0, 0, 360, 255, -1)          # body
    cv2.circle(im, (73, 38), 4, 255, -1)                          # head
    cv2.fillPoly(im, [np.array([[56, 42], [44, 50], [50, 52], [58, 46]], np.int32)], 255)   # fan tail
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.8))


def _draw_griffin(path):
    """A griffin from below: broad eagle wings in a shallow M, a lion body, a tufted tail and a beaked head, 128 x 64."""
    import cv2
    im = np.zeros((64, 128), np.uint8)
    wings = np.array([[2, 26], [18, 16], [40, 14], [56, 24], [64, 28], [72, 24], [88, 14], [110, 16], [126, 26],
                      [118, 28], [112, 34], [104, 30], [98, 36], [90, 32], [74, 36], [64, 38], [54, 36], [38, 32],
                      [30, 36], [24, 30], [16, 34], [10, 28]], np.int32)
    cv2.fillPoly(im, [wings], 255)
    cv2.ellipse(im, (64, 36), (7, 13), 0, 0, 360, 255, -1)         # lion body, seen from below
    cv2.circle(im, (64, 22), 5, 255, -1)                           # head
    cv2.fillPoly(im, [np.array([[61, 18], [64, 11], [67, 18]], np.int32)], 255)       # beak
    cv2.polylines(im, [np.array([[64, 48], [68, 54], [74, 58], [80, 58]], np.int32)], False, 255, 2)  # tail
    cv2.circle(im, (82, 57), 3, 255, -1)                           # tuft
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.8))


def _draw_beam(path):
    """A lighthouse beam in the right half of a 256 x 64 texture: narrow and bright at the lamp, widening and fading."""
    H, W = 64, 256
    y, x = np.mgrid[0:H, 0:W].astype(np.float64)
    t = np.clip((x - 128) / 127.0, 0, 1)
    hw = 2.0 + 24.0 * t
    across = np.exp(-((y - 31.5) / hw) ** 2 * 2.2)
    along = (1 - t) ** 0.5 * np.clip((x - 126) / 4.0, 0, 1)
    _png(path, 255 * np.sqrt(across * along))


def _draw_ray(path):
    """A light shaft in the top half of a 64 x 256 texture: thin at the source, widening and fading outward."""
    H, W = 256, 64
    y, x = np.mgrid[0:H, 0:W].astype(np.float64)
    t = np.clip((128 - y) / 127.0, 0, 1)
    hw = 4.0 + 16.0 * t
    across = np.exp(-((x - 31.5) / hw) ** 2)
    along = np.sin(np.pi * np.clip(t, 0, 1) ** 0.7) * np.clip((130 - y) / 6.0, 0, 1)
    _png(path, 255 * np.sqrt(across * along))


def _draw_star(path):
    """A four-pointed gleam: a hot centre and two thin crossed flares, 64 x 64."""
    y, x = np.mgrid[0:64, 0:64].astype(np.float64)
    dx, dy = (x - 31.5) / 32, (y - 31.5) / 32
    r = np.hypot(dx, dy)
    core = np.exp(-(r / 0.12) ** 2)
    flare = (np.exp(-(dy / 0.035) ** 2) + np.exp(-(dx / 0.035) ** 2)) * np.clip(1 - r, 0, 1) ** 1.5
    _png(path, 255 * np.clip(core + 0.8 * flare, 0, 1))


def _draw_feather(path):
    """A small white feather with a curved shaft, 32 x 64."""
    import cv2
    im = np.zeros((64, 32), np.uint8)
    cv2.ellipse(im, (16, 30), (7, 24), 8, 0, 360, 255, -1)
    cv2.line(im, (14, 58), (18, 4), 140, 1)
    _png(path, cv2.GaussianBlur(im, (0, 0), 1.0))


def _draw_flag(path):
    """A swallow-tailed pennant in the right half of a 256 x 64 texture, its hoist on the centre line."""
    import cv2
    im = np.zeros((64, 256), np.uint8)
    cv2.fillPoly(im, [np.array([[128, 6], [200, 16], [252, 22], [214, 32], [252, 42], [200, 48], [128, 58]],
                               np.int32)], 255)
    _png(path, cv2.GaussianBlur(im, (0, 0), 1.0))


def _draw_pole(path):
    """A flagpole in the top half of a 16 x 128 texture, its foot at the centre, a ball finial on top."""
    import cv2
    im = np.zeros((128, 16), np.uint8)
    cv2.line(im, (8, 64), (8, 8), 255, 3)
    cv2.circle(im, (8, 7), 3, 255, -1)
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.6))


def _draw_butterfly(path):
    """Butterfly wings seen from above: two big fore lobes and two small hind lobes, 64 x 64."""
    import cv2
    im = np.zeros((64, 64), np.uint8)
    for sx in (-1, 1):
        cv2.ellipse(im, (32 + sx * 13, 24), (13, 11), sx * 25, 0, 360, 255, -1)
        cv2.ellipse(im, (32 + sx * 10, 42), (8, 9), sx * -20, 0, 360, 230, -1)
    cv2.line(im, (32, 16), (32, 50), 120, 2)
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.9))


def _draw_dot(path):
    """A round soft dot (a streak once stretched along its velocity), 32 x 32."""
    y, x = np.mgrid[0:32, 0:32].astype(np.float64)
    r = np.hypot(x - 15.5, y - 15.5) / 16
    _png(path, 255 * np.clip(1 - r, 0, 1) ** 0.8)


SPRITES = {"dove": _draw_dove, "griffin": _draw_griffin, "beam": _draw_beam, "ray": _draw_ray, "star": _draw_star,
           "feather": _draw_feather, "flag": _draw_flag, "pole": _draw_pole, "butterfly": _draw_butterfly,
           "dot": _draw_dot}


def _mat(X: TA.K, name: str, colour, light: bool = False, mx: float = 0.5, tag: str = ""):
    """A sprite material: `light` = additive (beams, rays, gleams; colour is its brightness), else alpha-blended
    with `colour` as the paint (doves, griffins, flags). Cached per prefab, sprite and colour."""
    ck = f"cs_{X.key}_{name}_{tag}_{'L' if light else 'A'}_" + "_".join(f"{c:.3f}" for c in colour)
    if ck in X.A:
        return X.A[ck]
    pth = S.STAGE / X.key / f"amb_cs_{name}.png"
    SPRITES[name](pth)
    asset = f"{S.ASSET_ROOT}/{X.key}/amb_cs_{name}.png"
    X.A[ck] = X.M.material("Homm3ConfluxVfxUber", [X.M.tex("_Texture", asset, clamp=True),
                                                   X.M.tex("_Mask", asset, clamp=True)],
                           {"_Min": 0.0 if light else 0.05, "_Max": 1.0 if light else mx, "_Lerp": 1.0,
                            "_Multiply": 1.0, "_Blend": 0.0 if light else 1.0, "_xSpeed01": 0, "_ySpeed01": 0,
                            "_xSpeed02": 0, "_ySpeed02": 0, "_UseTwo": 0.0, "_CameraOffset": 0.0,
                            "_UseCamOffset": 0.0}, {"_Color": list(colour)[:3] + [1.0]})
    return X.A[ck]


def _burst(n: int, period: float, overlap: float = 1.0) -> dict:
    """A beat: one particle emitted every `period` (a constant rate of 1 / period emits on an exact beat, and every
    system of a group starts on the same frame), living the whole period (x overlap). n > 1 is expanded by _beats()
    into n such systems with their own seeds -- a cap-limited fast emitter is no burst in the editor renders, which
    simulate the whole prewarm in one step."""
    return {"lifetime": [period * overlap, period * overlap], "maxParticles": 2, "rate": round(1.0 / period, 5),
            "_n": int(n)}


def _beats(fn):
    """Kind wrapper: every system carrying `_n` becomes _n one-particle-per-beat copies (distinct names and seeds)."""
    import hashlib

    def run(X, nm):
        groups = fn(X, nm)
        for g in groups:
            out = []
            for d in g["systems"]:
                n = int(d.pop("_n", 1))
                for i in range(n):
                    c = dict(d)
                    if n > 1:
                        c["name"] = f"{d['name']}{i}"
                        c["seed"] = int(hashlib.sha1(c["name"].encode()).hexdigest()[:6], 16)
                    out.append(c)
            g["systems"] = out
        return groups
    run.__doc__ = fn.__doc__
    return run


def _qz(deg: float, tilt_x: float = 0.0):
    """Quaternion [x, y, z, w]: a roll of `deg` about the view axis (local z) after a tilt of `tilt_x` about x."""
    a, b = math.radians(deg) / 2, math.radians(tilt_x) / 2
    qz = np.array([0, 0, math.sin(a), math.cos(a)])
    qx = np.array([math.sin(b), 0, 0, math.cos(b)])
    x1, y1, z1, w1 = qz
    x2, y2, z2, w2 = qx
    return [w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2]


def _dirvel(dx, dy, v, lo, hi):
    """Spec dir (screen, y down) and speed -> sorted [min, max] velX / velY pairs."""
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, -dy / n
    a, b = sorted((ux * v * lo, ux * v * hi))
    c, d = sorted((uy * v * lo, uy * v * hi))
    return [a, b], [c, d]


# ------------------------------------------------------------------------------------------------ birds
FLUTTER = [0, 1, 0.08, 0.3, 0.16, 1, 0.24, 0.3, 0.32, 1, 0.62, 1, 0.7, 0.3, 1, 1]   # beat, beat, beat, glide, beat


def k_doves(X: TA.K, nm):
    """White doves fluttering round a keep's towers: tight loops with quick wing-beat bursts between glides, rising
    and dipping, the flock loose. radius (px), count, period (s per loop), span (px wingspan), colour (white),
    out (as for birds), life (s)."""
    r = X.px("radius", 50)
    per = float(X.e.get("period", 7.0))
    n = int(X.e.get("count", 5))
    span = X.px("span", 7)
    life = float(X.e.get("life", per * 1.3))
    w = 2 * math.pi / per
    mat = _mat(X, "dove", X.col([0.97, 0.97, 0.94]))
    return [X.group(nm, [SF.psys("doves", mat, lifetime=[life * 0.85, life * 1.15], speed=[0],
                                 size=[span * 0.8, span], sizeY=[span * 0.5, span * 0.55], sizeKeys=[0, 1, 1, 1],
                                 sizeYKeys=FLUTTER, rate=round(n / life, 3), maxParticles=n * 2, shape="circle",
                                 radius=r, radiusThickness=0.45, shapeRot=[90, 0, 0], orbitalX=[0, 0],
                                 orbitalY=[w * 0.75, w * 1.25], orbitalZ=[0, 0], radial=[-r * 0.04, r * 0.04],
                                 velX=[-X.m * 1.5, X.m * 1.5], velY=[-X.m * 2.0, X.m * 2.5], velZ=[-X.m, X.m],
                                 color=[1, 1, 1, 1], alphaKeys=[0, 0, 0.1, 1, 0.9, 1, 1, 0],
                                 noise=r * 0.18, noiseFreq=0.9, noiseScroll=0.4, customUV=False)])]


def k_griffins(X: TA.K, nm):
    """Griffins wheeling high over their tower: big tawny silhouettes on wide slow circles, long glides broken by a
    couple of heavy wing beats, banking now and then. radius (px), count, period (s per circle), span (px),
    colour (dark tawny), out, lift (px the circle rides above the anchor)."""
    r = X.px("radius", 110)
    per = float(X.e.get("period", 20))
    n = int(X.e.get("count", 2))
    span = X.px("span", 22)
    life = per * 1.5
    w = 2 * math.pi / per
    mat = _mat(X, "griffin", X.col([0.3, 0.22, 0.13]))
    beats = [0, 1, 0.18, 1, 0.22, 0.4, 0.26, 1, 0.58, 1, 0.62, 0.4, 0.66, 1, 1, 1]
    bank = [0, 1, 0.3, 1, 0.4, 0.7, 0.5, 1, 0.8, 1, 0.9, 0.75, 1, 1]
    return [X.group(nm, [SF.psys("griffins", mat, lifetime=[life * 0.9, life * 1.1], speed=[0],
                                 size=[span * 0.85, span], sizeY=[span * 0.5, span * 0.55], sizeKeys=bank,
                                 sizeYKeys=beats, rate=round(n / life, 3), maxParticles=n * 2, shape="circle",
                                 radius=r, radiusThickness=0.25, shapeRot=[90, 0, 0], shapePos=[0.0, X.px("lift", 0), 0.0],
                                 orbitalX=[0, 0], orbitalY=[w * 0.85, w * 1.15], orbitalZ=[0, 0],
                                 velX=[-X.m * 0.5, X.m * 0.5], velY=[-X.m * 1.2, X.m * 1.2], velZ=[0, 0],
                                 color=[1, 1, 1, 1], alphaKeys=[0, 0, 0.08, 1, 0.92, 1, 1, 0],
                                 noise=r * 0.05, noiseFreq=0.3, customUV=False)])]


def k_pigeons(X: TA.K, nm):
    """Market pigeons: every period the flock bursts up off the square, wheels away flapping hard and is lost over
    the roofs; half a period later it glides back in and drops onto the stalls. count, span (px), reach (px they fly
    out), dir [dx, dy] (screen, the way they leave), period (s), colour (slate grey)."""
    per = float(X.e.get("period", 9.0))
    n = int(X.e.get("count", 5))
    span = X.px("span", 5)
    reach = X.px("reach", 90)
    dx, dy = X.e.get("dir", [1, -0.6])
    mat = _mat(X, "dove", X.col([0.5, 0.5, 0.55]))
    out_t = 0.32 * per                                   # the take-off leg lasts a third of the cycle
    vx, vy = _dirvel(dx, dy, reach / out_t, 0.7, 1.2)
    nrm = math.hypot(dx, dy) or 1
    back = [dx / nrm * reach * 1.15 * 0.95 + 0.0, -dy / nrm * reach * 1.15 * 0.95]   # where the return leg starts
    rvx, rvy = _dirvel(-dx, -dy, reach / out_t, 0.85, 1.1)
    flap = [0, 1, 0.12, 0.25, 0.24, 1, 0.36, 0.25, 0.48, 1, 0.6, 0.25, 0.72, 1, 1, 0.4]
    common = dict(speed=[0], size=[span * 0.8, span], sizeY=[span * 0.5, span * 0.55], sizeKeys=[0, 1, 1, 1],
                  sizeYKeys=flap, shape="box", color=[1, 1, 1, 1], noise=X.m * 6, noiseFreq=1.1, customUV=False)
    up = SF.psys("pigeons_up", mat, **_burst(n, per), shapeScale=[X.m * 22, X.m * 3, X.m * 6],
                 velX=vx, velY=vy, velZ=[-X.m * 2, X.m * 2], alphaKeys=[0, 0, 0.02, 1, 0.26, 1, 0.33, 0, 1, 0],
                 **common)
    down = SF.psys("pigeons_back", mat, **_burst(n, per), shapeScale=[X.m * 30, X.m * 10, X.m * 6],
                   shapePos=[back[0], back[1], 0.0], velX=rvx, velY=rvy, velZ=[-X.m * 2, X.m * 2],
                   alphaKeys=[0, 0, 0.5, 0, 0.56, 1, 0.8, 1, 0.84, 0, 1, 0], **common)
    return [X.group(nm, [up, down])]


def k_swallows(X: TA.K, nm):
    """Swallows skimming a meadow: small dark birds darting low and fast in long jinking streaks. w, h (px box),
    count (alive), span (px), dart (noise strength, px/s), life (s), colour."""
    w, h = X.px("w", 300), X.px("h", 40)
    n = int(X.e.get("count", 4))
    span = X.px("span", 6)
    life = float(X.e.get("life", 5))
    v = X.px("speed", 70)
    mat = _mat(X, "dove", X.col([0.12, 0.12, 0.16]))
    return [X.group(nm, [SF.psys("swallows", mat, lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[span * 0.8, span], sizeY=[span * 0.4, span * 0.5], sizeKeys=[0, 1, 1, 1],
                                 sizeYKeys=[0, 1, 0.1, 0.35, 0.2, 1, 0.5, 1, 0.6, 0.35, 0.7, 1, 1, 1],
                                 rate=round(n / life, 3), maxParticles=n * 2, shape="box", shapeScale=[w, h, w * 0.3],
                                 velX=[-v, v], velY=[-v * 0.1, v * 0.15], velZ=[-v * 0.3, v * 0.3],
                                 color=[1, 1, 1, 1], alphaKeys=[0, 0, 0.1, 1, 0.9, 1, 1, 0],
                                 noise=X.px("dart", 40), noiseFreq=0.9, noiseScroll=0.6, customUV=False)])]


def k_butterflies(X: TA.K, nm):
    """Butterflies over the meadow: white and sulphur-yellow wings opening and closing, tumbling about lazily.
    w, h (px box), count (alive), span (px), life (s), colour, colour2."""
    w, h = X.px("w", 300), X.px("h", 60)
    n = int(X.e.get("count", 6))
    span = X.px("span", 7)
    life = float(X.e.get("life", 7))
    mat = _mat(X, "butterfly", [1.0, 1.0, 1.0])
    c1 = X.col([0.98, 0.97, 0.9])
    c2 = [float(x) for x in X.e.get("colour2", [1.0, 0.88, 0.35])]
    flap = [0, 1, 0.07, 0.25, 0.14, 1, 0.21, 0.25, 0.28, 1, 0.35, 0.25, 0.42, 1, 1, 1]
    return [X.group(nm, [SF.psys("butterflies", mat, lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[span * 0.8, span * 1.1], sizeY=[span * 0.8, span * 1.1], sizeKeys=flap,
                                 sizeYKeys=[0, 1, 1, 1], rate=round(n / life, 3), maxParticles=n * 2, shape="box",
                                 shapeScale=[w, h, w * 0.3], velX=[-X.m * 4, X.m * 4], velY=[-X.m * 1.5, X.m * 2.5],
                                 velZ=[-X.m * 2, X.m * 2], color=c1 + [1.0], color2=c2 + [1.0],
                                 alphaKeys=[0, 0, 0.1, 1, 0.9, 1, 1, 0], noise=X.m * 10, noiseFreq=0.7,
                                 noiseScroll=0.5, customUV=False)])]


# ------------------------------------------------------------------------------------------------ light
def k_lighthouse_beam(X: TA.K, nm):
    """The lighthouse beam sweeping round: it swings out to the right, lengthening as it turns side-on, shortens as it
    passes behind the tower, swings out to the left and flashes when it faces the town. length (px of a side-on
    beam), width (px at its tip), period (s per turn), colour, intensity (0..1)."""
    L, wd = X.px("length", 140), X.px("width", 22)
    per = float(X.e.get("period", 8.0))
    a = math.sqrt(float(X.e.get("intensity", 0.4)))   # VfxUber squares vertex alpha
    col = X.col([1.0, 0.92, 0.7])
    mat = _mat(X, "beam", [4.0, 4.0, 4.0], light=True)
    one = _burst(1, per)
    right = SF.psys("beam_r", mat, **one, speed=[0], size=[L * 2, L * 2], sizeY=[wd * 2.4, wd * 2.4],
                    sizeKeys=[0, 0.08, 0.22, 1, 0.42, 0.25, 0.5, 0.05, 1, 0.05],
                    sizeYKeys=[0, 0.5, 0.22, 1, 0.5, 0.6, 1, 0.5], color=col + [a],
                    alphaKeys=[0, 0.9, 0.06, 0.8, 0.22, 0.75, 0.42, 0.15, 0.48, 0, 1, 0], radius=X.m * 0.01,
                    customUV=False)
    left = SF.psys("beam_l", mat, **one, speed=[0], size=[L * 2, L * 2], sizeY=[wd * 2.4, wd * 2.4],
                   rotation=[180, 180], sizeKeys=[0, 0.05, 0.5, 0.05, 0.58, 0.25, 0.78, 1, 1, 0.08],
                   sizeYKeys=[0, 0.5, 0.5, 0.6, 0.78, 1, 1, 0.5], color=col + [a],
                   alphaKeys=[0, 0, 0.52, 0, 0.58, 0.15, 0.78, 0.75, 0.94, 0.8, 1, 0.9], radius=X.m * 0.01,
                   customUV=False)
    flash = SF.psys("beam_flash", X.A["glow"], **one, speed=[0], size=[wd * 3.2, wd * 3.2], color=col + [a * 0.9],
                    alphaKeys=[0, 1, 0.07, 0.15, 0.9, 0.1, 1, 1], radius=X.m * 0.01, customUV=False)
    return [X.group(nm, [right, left, flash])]


def k_holy_rays(X: TA.K, nm):
    """Holy light: shafts radiating from a source, each slowly swelling and fading, the fan turning a little.
    length (px), width (px of a shaft's broad end), aim (deg, 0 = up, 180 = down), spread (deg either side; 180 = a
    full halo), count (alive), life (s), turn (deg/s either way), colour, intensity (0..1)."""
    L, wd = X.px("length", 120), X.px("width", 14)
    aim = float(X.e.get("aim", 180))
    spread = float(X.e.get("spread", 35))
    n = int(X.e.get("count", 5))
    life = float(X.e.get("life", 7))
    turn = float(X.e.get("turn", 1.5))
    a = math.sqrt(float(X.e.get("intensity", 0.25)))
    mat = _mat(X, "ray", [1.8, 1.8, 1.8], light=True)
    return [X.group(nm, [SF.psys("holy_rays", mat, lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[wd * 0.9, wd * 1.3], sizeY=[L * 1.6, L * 2.2],
                                 sizeKeys=[0, 0.8, 1, 1.1], sizeYKeys=[0, 0.85, 0.5, 1, 1, 0.9],
                                 rotation=[aim - spread, aim + spread], rotSpeed=[-turn, turn],
                                 rate=round(n / life, 3), maxParticles=n * 2, radius=X.m * 0.5,
                                 color=X.col([1.0, 0.95, 0.75]) + [a],
                                 alphaKeys=[0, 0, 0.3, 1, 0.55, 0.7, 0.75, 1, 1, 0], customUV=False)])]


def k_gleam(X: TA.K, nm):
    """A gleam running along polished metal (up a sword blade, across a gilded dome): a four-pointed star slides
    along `dir` for `reach` px, flaring in the middle, then the metal rests until the next period. dir [dx, dy]
    (screen, y down), reach (px), star (px), period (s), run (share of the period the gleam travels), colour,
    intensity (0..1)."""
    per = float(X.e.get("period", 5.0))
    run = float(X.e.get("run", 0.22))
    reach = X.px("reach", 40)
    st = X.px("star", 12)
    dx, dy = X.e.get("dir", [0, -1])
    vx, vy = _dirvel(dx, dy, reach / (run * per), 1.0, 1.0)
    mat = _mat(X, "star", [5.0, 5.0, 5.0], light=True)
    return [X.group(nm, [SF.psys("gleam", mat, **_burst(1, per), speed=[0], size=[st, st], velX=vx, velY=vy,
                                 velZ=[0, 0], color=X.col([1.0, 0.97, 0.85]) + [math.sqrt(float(X.e.get("intensity", 0.9)))],
                                 alphaKeys=[0, 0, run * 0.3, 0.7, run * 0.55, 1, run * 0.85, 0.5, run, 0, 1, 0],
                                 sizeKeys=[0, 0.4, run * 0.55, 1.2, run, 0.3, 1, 0.3], rotation=[0, 20],
                                 radius=X.m * 0.01, customUV=False)])]


def k_candles(X: TA.K, nm):
    """Candles in a monastery's windows: several tiny warm flames each guttering on its own, slowly coming and going
    along the window band. w, h (px band), count (alive), flame (px), life (s), colour, intensity (0..1)."""
    w, h = X.px("w", 40), X.px("h", 6)
    n = int(X.e.get("count", 5))
    fl = X.px("flame", 7)
    life = float(X.e.get("life", 5))
    a = math.sqrt(float(X.e.get("intensity", 0.4)))
    gutter = [0, 0, 0.1, 1, 0.24, 0.55, 0.36, 0.95, 0.5, 0.65, 0.66, 1, 0.82, 0.6, 1, 0]
    return [X.group(nm, [SF.psys("candles", X.A["glow"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[fl * 0.8, fl * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w * 0.05], color=X.col([1.0, 0.72, 0.36]) + [a],
                                 color2=[1.0, 0.85, 0.5, a], alphaKeys=gutter, customUV=False)])]


def k_astral_ring(X: TA.K, nm):
    """An armillary of stars round the mage guild: two tilted rings of pale-blue sparks orbiting the tower's crown in
    opposite directions, each spark trailing a short comet tail. radius (px), count (per ring), period (s per orbit),
    tilt (deg the rings lean), spark (px), intensity (0..1), colour."""
    r = X.px("radius", 40)
    n = int(X.e.get("count", 6))
    per = float(X.e.get("period", 7))
    tilt = float(X.e.get("tilt", 22))
    sp = X.px("spark", 3.6)
    w = 2 * math.pi / per
    a = float(X.e.get("intensity", 0.85))
    sysl = []
    for i, sgn in enumerate((1, -1)):
        sysl.append(SF.psys(f"ring{i}", X.A["glint"], lifetime=[per * 1.4, per * 1.6], speed=[0],
                            size=[sp * 0.8, sp * 1.2], rate=round(n / (per * 1.5), 3), maxParticles=n * 2,
                            shape="circle", radius=r, radiusThickness=0.02, shapeRot=[90, 0, 0],
                            rot=_qz(sgn * tilt, 14), orbitalX=[0, 0], orbitalY=[sgn * w * 0.98, sgn * w * 1.02],
                            orbitalZ=[0, 0], color=X.col([0.62, 0.8, 1.0]) + [a],
                            alphaKeys=[0, 0, 0.12, 1, 0.5, 0.7, 0.88, 1, 1, 0], renderMode=1, lengthScale=1.0,
                            velocityScale=0.12, customUV=False))
    return [X.group(nm, sysl)]


def k_lake_shimmer(X: TA.K, nm):
    """Sun glitter on a lake: flat horizontal flecks of light winking on and off across the water and drifting with
    the ripples. w, h (px box), rate (/s), fleck (px long), drift (px/s), colour."""
    w, h = X.px("w", 150), X.px("h", 24)
    fk = X.px("fleck", 9)
    life = float(X.e.get("life", 0.9))
    rate = float(X.e.get("rate", 6))
    vx = X.px("drift", 3)
    return [X.group(nm, [SF.psys("shimmer", X.A["glint"], lifetime=[life * 0.6, life * 1.3], speed=[0],
                                 size=[fk * 0.6, fk * 1.2], sizeY=[fk * 0.3, fk * 0.4], rate=rate,
                                 maxParticles=max(8, int(rate * life * 3)), shape="box",
                                 shapeScale=[w, h * 0.2, h], velX=[vx * 0.5, vx * 1.2], velY=[0, 0], velZ=[0, 0],
                                 color=X.col([0.95, 0.97, 1.0]) + [1.0], alphaKeys=[0, 0, 0.35, 1, 1, 0],
                                 sizeKeys=[0, 0.3, 0.4, 1, 1, 0.6], customUV=False)])]


# ------------------------------------------------------------------------------------------------ work and war
def k_anvil(X: TA.K, nm):
    """The blacksmith's anvil: on every stroke a white-hot flash and a fan of sparks spraying off the work, then the
    forge rests till the next blow. period (s per stroke), sparks (per blow), reach (px), spark (px), flash (px),
    colour, intensity (0..1)."""
    per = float(X.e.get("period", 1.3))
    n = int(X.e.get("sparks", 7))
    v = X.px("reach", 22) / (0.22 * per)
    sp = X.px("spark", 3.4)
    fs = X.px("flash", 16)
    col = X.col([1.0, 0.7, 0.3])
    sparks = SF.psys("anvil_sparks", X.A["glint"], **_burst(n, per), speed=[0], velX=[-v, v], velY=[-v * 0.2, v],
                     velZ=[-v * 0.4, v * 0.4], size=[sp * 0.6, sp * 1.2], radius=X.m * 0.6, color=col + [1.0],
                     alphaKeys=[0, 1, 0.1, 0.9, 0.24, 0, 1, 0], sizeKeys=[0, 1, 0.24, 0.3, 1, 0.3], customUV=False)
    flash = SF.psys("anvil_flash", X.A["glow"], **_burst(1, per), speed=[0], size=[fs, fs], radius=X.m * 0.01,
                    color=[1.0, 0.85, 0.6, math.sqrt(float(X.e.get("intensity", 0.7)))],
                    alphaKeys=[0, 1, 0.08, 0.25, 0.2, 0, 1, 0], customUV=False)
    return [X.group(nm, [sparks, flash])]


def k_sword_clash(X: TA.K, nm):
    """Sword drill in a barracks yard: two clashes in quick succession (a few cold white sparks and a blink of light),
    then a pause. period (s per bout), sparks, spark (px), spread (px), colour."""
    per = float(X.e.get("period", 2.6))
    n = int(X.e.get("sparks", 4))
    sp = X.px("spark", 3.6)
    v = X.px("spread", 8) / (0.1 * per)
    col = X.col([0.9, 0.95, 1.0])
    out = []
    for i, t0 in enumerate((0.0, 0.16)):
        k = [0, 0, t0, 0, t0 + 0.01, 1, t0 + 0.09, 0, 1, 0] if t0 > 0 else [0, 1, 0.09, 0, 1, 0]
        out.append(SF.psys(f"clash{i}", X.A["glint"], **_burst(n, per), speed=[0], velX=[-v, v], velY=[-v * 0.5, v],
                           velZ=[-v * 0.3, v * 0.3], size=[sp * 0.6, sp * 1.1], radius=X.m * 0.8,
                           shapePos=[X.m * 3 * i, 0.0, 0.0], color=col + [1.0], alphaKeys=k, customUV=False))
    return [X.group(nm, out)]


def k_arrows(X: TA.K, nm):
    """Practice arrows loosed from an archers' tower: every period a small volley streaks out along `dir`, dark
    shafts in flight, and is gone. dir [dx, dy] (screen, y down), reach (px), count (per volley), streak (px long),
    period (s), colour."""
    per = float(X.e.get("period", 4.0))
    n = int(X.e.get("count", 3))
    reach = X.px("reach", 120)
    fly = 0.25 * per
    v = reach / fly
    dx, dy = X.e.get("dir", [1, 0.1])
    vx, vy = _dirvel(dx, dy, v, 0.85, 1.1)
    mat = _mat(X, "dot", X.col([0.16, 0.13, 0.1]))
    th = X.px("thick", 2.6)
    return [X.group(nm, [SF.psys("arrows", mat, **_burst(n, per), speed=[0], velX=vx, velY=vy,
                                 velZ=[-v * 0.05, v * 0.05], size=[th, th * 1.2], radius=X.m * 2,
                                 color=[1, 1, 1, 1], alphaKeys=[0, 0, 0.02, 1, 0.22, 1, 0.26, 0, 1, 0],
                                 renderMode=1, lengthScale=1.0, velocityScale=X.px("streak", 9) / v,
                                 customUV=False)])]


def k_joust_dust(X: TA.K, nm):
    """Jousting charges down the lists: a rider's dust races along the lane, billowing and settling behind him; half
    a period later the next rider charges back the other way. dir [dx, dy] (screen, y down, the first charge),
    reach (px of the lane), puffs (per charge), puff (px), colour (dry earth), alpha, period (s)."""
    per = float(X.e.get("period", 8.0))
    reach = X.px("reach", 220)
    n = int(X.e.get("puffs", 9))
    sz = X.px("puff", 26)
    a = float(X.e.get("alpha", 0.4))
    col = X.col([0.74, 0.66, 0.52])
    dx, dy = X.e.get("dir", [1, -0.2])
    nrm = math.hypot(dx, dy) or 1
    run = 0.3 * per
    vx, vy = _dirvel(dx, dy, reach / run, 0.4, 1.0)
    rvx, rvy = _dirvel(-dx, -dy, reach / run, 0.4, 1.0)
    rise = X.m * 3
    end = [dx / nrm * reach, -dy / nrm * reach, 0.0]
    out = []
    for nm_, pos, (ax, ay), keys in (
            ("charge_a", [-end[0] / 2, -end[1] / 2, 0.0], (vx, vy), [0, 0, 0.04, 1, 0.3, 0.8, 0.48, 0, 1, 0]),
            ("charge_b", [end[0] / 2, end[1] / 2, 0.0], (rvx, rvy),
             [0, 0, 0.5, 0, 0.54, 1, 0.8, 0.8, 0.98, 0, 1, 0])):
        out.append(SF.psys(nm_, X.A["puff"], **_burst(n, per), speed=[0], velX=ax, velY=[ay[0] + rise * 0.3,
                                                                                         ay[1] + rise],
                           velZ=[-X.m * 2, X.m * 2], size=[sz * 0.6, sz * 1.0], shapePos=pos, radius=X.m * 3,
                           color=col + [X.op(a)], alphaKeys=TA.sqk(keys),
                           sizeKeys=[0, 0.3, 0.3, 1.0, 0.5, 1.6, 1, 2.0], rotation=[0, 360], rotSpeed=[-20, 20],
                           noise=sz * 0.15, noiseFreq=0.6, customUV=False))
    return [X.group(nm, out)]


# ------------------------------------------------------------------------------------------------ cloth, water, faith
def k_pennant(X: TA.K, nm):
    """A swallow-tailed pennant snapping on a tower-top pole: the cloth ripples, stretching and gathering as the wind
    gusts. pole (px tall), flag (px long), colour (cloth), side (+1 flies right, -1 left), period (s per gust)."""
    ph, fl = X.px("pole", 12), X.px("flag", 15)
    per = float(X.e.get("period", 1.4))
    side = float(X.e.get("side", 1))
    pole = SF.psys("pole", _mat(X, "pole", [0.35, 0.3, 0.26]), **_burst(1, 60.0, 1.02), speed=[0],
                   size=[ph * 0.25, ph * 0.25], sizeY=[ph * 2, ph * 2], color=[1, 1, 1, 1],
                   alphaKeys=[0, 1, 1, 1], radius=X.m * 0.01, customUV=False)
    flap = SF.psys("flag", _mat(X, "flag", X.col([0.14, 0.2, 0.62])), **_burst(1, per * 2, 1.02), speed=[0],
                   size=[fl * 2, fl * 2], sizeY=[fl * 0.5, fl * 0.5], rotation=[0, 0] if side > 0 else [180, 180],
                   sizeKeys=[0, 1, 0.2, 0.84, 0.42, 1, 0.6, 0.9, 0.8, 0.98, 1, 1],
                   sizeYKeys=[0, 0.92, 0.2, 1.08, 0.42, 0.9, 0.6, 1.04, 0.8, 0.94, 1, 0.92],
                   shapePos=[0.0, ph * 0.8, 0.0], color=[1, 1, 1, 1], alphaKeys=[0, 1, 1, 1], radius=X.m * 0.01,
                   customUV=False)
    return [X.group(nm, [pole, flap])]


def k_falls_spray(X: TA.K, nm):
    """A waterfall's foot: white spray billowing up and out of the plunge pool, with bright droplets thrown off and
    falling back. w (px of the pool), rise (px), puff (px), drops (/s), colour, alpha."""
    w = X.px("w", 30)
    life = float(X.e.get("life", 3.0))
    vy = X.px("rise", 30) / life
    sz = X.px("puff", 30)
    a = float(X.e.get("alpha", 0.45))
    dr = float(X.e.get("drops", 6))
    col = X.col([0.95, 0.97, 1.0])
    mist = SF.psys("falls_mist", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                   velX=[-vy * 0.5, vy * 0.5], velY=[vy * 0.6, vy * 1.2], velZ=[-vy * 0.3, vy * 0.3],
                   size=[sz * 0.6, sz * 1.0], rate=round(6 / life, 3), maxParticles=16, shape="box",
                   shapeScale=[w, X.m * 2, w * 0.3], color=col + [X.op(a)],
                   alphaKeys=TA.sqk([0, 0, 0.15, 1, 0.6, 0.6, 1, 0]), sizeKeys=[0, 0.4, 0.4, 1.0, 1, 1.8],
                   rotation=[0, 360], rotSpeed=[-25, 25], noise=sz * 0.2, noiseFreq=0.5, customUV=False)
    v = X.px("rise", 30) / 0.7
    drops = SF.psys("falls_drops", X.A["glint"], lifetime=[0.5, 0.9], speed=[0], velX=[-v * 0.6, v * 0.6],
                    velY=[-v * 0.7, v], velZ=[-v * 0.2, v * 0.2], size=[X.m * 2.4, X.m * 3.4], rate=dr,
                    maxParticles=20, shape="box", shapeScale=[w, X.m * 2, w * 0.3], color=col + [1.0],
                    alphaKeys=[0, 0, 0.15, 1, 0.7, 0.6, 1, 0], gravity=float(X.e.get("gravity", 0.0)),
                    customUV=False)
    return [X.group(nm, [mist, drops])]


def k_incense(X: TA.K, nm):
    """Incense threads rising from a censer: thin pale-blue strands that climb slowly, curling and swaying as they
    thin out (no chimney puffs). width (px of a strand), rise (px), count (alive), life (s), colour, alpha."""
    wd = X.px("width", 4)
    life = float(X.e.get("life", 6))
    vy = X.px("rise", 50) / life
    n = int(X.e.get("count", 6))
    a = float(X.e.get("alpha", 0.35))
    return [X.group(nm, [SF.psys("incense", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-vy * 0.15, vy * 0.15], velY=[vy * 0.8, vy * 1.2], velZ=[0, 0],
                                 size=[wd * 2.2, wd * 3.0], sizeY=[wd * 7, wd * 10], rate=round(n / life, 3),
                                 maxParticles=n * 2, radius=wd * 0.3, color=X.col([0.82, 0.86, 0.95]) + [X.op(a)],
                                 alphaKeys=TA.sqk([0, 0, 0.2, 1, 0.65, 0.6, 1, 0]),
                                 sizeKeys=[0, 0.5, 1, 1.4], sizeYKeys=[0, 0.6, 1, 1.5],
                                 rotation=[-12, 12], rotSpeed=[-14, 14], noise=wd * 1.4, noiseFreq=0.35,
                                 customUV=False)])]


def k_feathers(X: TA.K, nm):
    """White feathers drifting down from the Portal of Glory's cloud, see-sawing and turning as they fall.
    w, h (px box), count (alive), feather (px), fall (px/s), life (s), colour, alpha."""
    w, h = X.px("w", 120), X.px("h", 20)
    n = int(X.e.get("count", 5))
    fz = X.px("feather", 7)
    life = float(X.e.get("life", 9))
    vf = X.px("fall", 6)
    mat = _mat(X, "feather", X.col([1.0, 1.0, 0.97]))
    return [X.group(nm, [SF.psys("feathers", mat, lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[fz * 0.5, fz * 0.6], sizeY=[fz * 0.9, fz * 1.1],
                                 sizeKeys=[0, 1, 0.25, 0.4, 0.5, 1, 0.75, 0.4, 1, 1], sizeYKeys=[0, 1, 1, 1],
                                 rotation=[-60, 60], rotSpeed=[-40, 40], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w * 0.2], velX=[-vf * 0.4, vf * 0.4],
                                 velY=[-vf * 1.2, -vf * 0.8], velZ=[0, 0], color=[1, 1, 1, X.op(float(
                                     X.e.get("alpha", 0.9)))], alphaKeys=TA.sqk([0, 0, 0.12, 1, 0.8, 1, 1, 0]),
                                 noise=X.m * 6, noiseFreq=0.5, customUV=False)])]


KINDS = {n: _beats(globals()["k_" + n]) for n in (
    "doves", "griffins", "pigeons", "swallows", "butterflies", "lighthouse_beam", "holy_rays", "gleam", "candles",
    "astral_ring", "lake_shimmer", "anvil", "sword_clash", "arrows", "joust_dust", "pennant", "falls_spray", "incense",
    "feathers")}
