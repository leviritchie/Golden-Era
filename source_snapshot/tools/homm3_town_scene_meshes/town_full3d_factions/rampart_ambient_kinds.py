"""Rampart's own ambient kinds (loaded by town_full3d_ambient.py stage): an elven glade town under a misty
mountainside. Leaves tumbling off the dendroid arches and the forest edge, pollen drifting over the meadow on the
breeze, butterflies over the market, wildflowers and the stables' hay, songbirds flitting in bounding flight round the
castle hill, the Enchanted Spring's spray billowing off the waterfall's foot with a prismatic tinge, white feathers
shed by the pegasus statue, the unicorn glade's prismatic shimmer rising out of the grass, the glade's stone lanterns
breathing with moths circling them, dryad wisps winding through the dendroid boughs, green-gold dragons gliding
round the Dragon Cliffs on slow wing beats, the Spirit Guardian's golden aura, the Fountain of Fortune's gold flecks
leaping from the pool, sun glitter and koi in the Mystic Pond, lit shoji paper screens, hoof dust in the centaur
paddock and the smithy's anvil sparks.

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), every velocity curve in one system and every orbital/radial curve
in one system as [min, max] pairs. Gradient / size keys stay at 8 or fewer per curve (Unity's limit). Sprites (leaf,
feather, butterfly, songbird, dragon, koi) are generated next to the prefab like the shared bird silhouette.
"""
from __future__ import annotations

import math

import numpy as np

import town_full3d_ambient as TA
import stronghold_full3d_fx as SF
import stronghold_full3d_scene as S


# ------------------------------------------------------------------------------------------------ sprites
def _png(path, im):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    TA.unlink(path)
    Image.fromarray(np.dstack([im] * 3)).save(path)


def _draw_leaf(path):
    """A broad elven leaf with a stalk and a darker midrib, white on black, 64 x 64 (fills most of the quad)."""
    import cv2
    im = np.zeros((64, 64), np.uint8)
    pts = np.array([[32, 4], [44, 14], [52, 28], [48, 44], [36, 56], [32, 58], [28, 56], [16, 44], [12, 28],
                    [20, 14]], np.int32)
    cv2.fillPoly(im, [pts], 235)
    cv2.line(im, (32, 8), (32, 62), 150, 2)
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.9))


def _draw_feather(path):
    """A long white pegasus feather: a curved vane round a shaft, 64 x 64 drawn on the diagonal."""
    import cv2
    im = np.zeros((64, 64), np.uint8)
    cv2.ellipse(im, (32, 32), (27, 8), -40, 0, 360, 240, -1)
    cv2.line(im, (10, 54), (54, 10), 255, 2)
    _png(path, cv2.GaussianBlur(im, (0, 0), 1.0))


def _draw_butterfly(path):
    """A butterfly seen from above, wings open: four lobes and a thin body, 64 x 64."""
    import cv2
    im = np.zeros((64, 64), np.uint8)
    cv2.ellipse(im, (20, 22), (15, 13), -25, 0, 360, 240, -1)
    cv2.ellipse(im, (44, 22), (15, 13), 25, 0, 360, 240, -1)
    cv2.ellipse(im, (23, 44), (10, 9), 20, 0, 360, 220, -1)
    cv2.ellipse(im, (41, 44), (10, 9), -20, 0, 360, 220, -1)
    cv2.line(im, (32, 12), (32, 54), 255, 3)
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.8))


def _draw_songbird(path):
    """A small bird in flapping flight seen face-on: two raised wings in a V over a round body, 64 x 32."""
    import cv2
    im = np.zeros((32, 64), np.uint8)
    pts = np.array([[2, 6], [16, 12], [28, 20], [32, 22], [36, 20], [48, 12], [62, 6], [50, 16], [38, 26],
                    [32, 28], [26, 26], [14, 16]], np.int32)
    cv2.fillPoly(im, [pts], 255)
    cv2.circle(im, (32, 23), 5, 255, -1)
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.7))


def _draw_dragon(path):
    """A dragon seen from below, wings spread: bat-wing membranes with scalloped trailing edges, a long neck and a
    longer tail, 128 x 64 (symmetric, so a billboard reads right flying either way)."""
    import cv2
    im = np.zeros((64, 128), np.uint8)
    wing = [[64, 26], [50, 16], [30, 6], [4, 14], [14, 22], [10, 30], [22, 30], [22, 38], [34, 34], [40, 40],
            [52, 32], [60, 34]]
    pts = np.array(wing, np.int32)
    cv2.fillPoly(im, [pts], 255)
    cv2.fillPoly(im, [np.array([[128 - x, y] for x, y in wing], np.int32)], 255)
    cv2.ellipse(im, (64, 32), (6, 12), 0, 0, 360, 255, -1)            # body
    cv2.line(im, (64, 22), (64, 6), 255, 4)                              # neck
    cv2.ellipse(im, (64, 5), (4, 4), 0, 0, 360, 255, -1)                 # head
    cv2.polylines(im, [np.array([[64, 42], [66, 50], [62, 56], [65, 62]], np.int32)], False, 255, 3)   # tail
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.8))


def _draw_koi(path):
    """A soft oval body (a koi under the water; the stretched billboard draws it out along its swim)."""
    import cv2
    im = np.zeros((64, 64), np.uint8)
    cv2.ellipse(im, (32, 32), (22, 14), 0, 0, 360, 230, -1)
    _png(path, cv2.GaussianBlur(im, (0, 0), 3.0))


SPRITES = {"leaf": _draw_leaf, "feather": _draw_feather, "butterfly": _draw_butterfly, "songbird": _draw_songbird,
           "dragon": _draw_dragon, "koi": _draw_koi}


def _sprite_mat(X: TA.K, name: str, blend: float = 1.0, mx: float = 0.5, colour=(1.0, 1.0, 1.0)):
    pth = S.STAGE / X.key / f"amb_rm_{name}.png"
    SPRITES[name](pth)
    asset = f"{S.ASSET_ROOT}/{X.key}/amb_rm_{name}.png"
    return X.M.material("Homm3ConfluxVfxUber", [X.M.tex("_Texture", asset, clamp=True),
                                               X.M.tex("_Mask", asset, clamp=True)],
                        {"_Min": 0.05, "_Max": mx, "_Lerp": 1.0, "_Multiply": 1.0, "_Blend": blend, "_xSpeed01": 0,
                         "_ySpeed01": 0, "_xSpeed02": 0, "_ySpeed02": 0, "_UseTwo": 0.0, "_CameraOffset": 0.0,
                         "_UseCamOffset": 0.0}, {"_Color": list(colour) + [1.0]})


def _cols(X: TA.K, key, default):
    """Two colours a particle's start colour is picked between (a leaf is green or gold, not a blend of a set)."""
    c = X.e.get(key, default)
    return [float(x) for x in c[0]], [float(x) for x in c[1]]


# ------------------------------------------------------------------------------------------------ forest
def k_falling_leaves(X: TA.K, nm):
    """Leaves letting go of a canopy: each tumbles down in a lazy pendulum (strong slow noise), spinning and turning
    over (its height flips through the life), green or autumn gold. w, h (px, the canopy box they let go from), fall
    (px/s), drift (px/s, +x = right, the breeze), leaf (px), rate (/s), life (s), colours [[r,g,b],[r,g,b]], alpha."""
    w, h = X.px("w", 80), X.px("h", 30)
    vy, vx = X.px("fall", 9), X.px("drift", 3)
    life = float(X.e.get("life", 6))
    rate = float(X.e.get("rate", 0.8))
    lf = X.px("leaf", 6)
    c1, c2 = _cols(X, "colours", [[0.55, 0.62, 0.22], [0.86, 0.62, 0.2]])
    a = X.op(float(X.e.get("alpha", 0.9)))
    return [X.group(nm, [SF.psys("falling_leaves", _sprite_mat(X, "leaf", mx=0.45), lifetime=[life * 0.75, life * 1.2],
                                 speed=[0], velX=[vx * 0.3, vx * 1.6], velY=[-vy * 1.25, -vy * 0.75],
                                 velZ=[-vx * 0.3, vx * 0.3], size=[lf * 0.7, lf * 1.25], sizeY=[lf * 0.7, lf * 1.25],
                                 sizeKeys=[0, 1, 1, 1], sizeYKeys=[0, 1, 0.18, 0.2, 0.36, 1, 0.55, 0.15, 0.74, 1,
                                                                   0.9, 0.3, 1, 1],
                                 rate=rate, maxParticles=max(6, int(rate * life * 2)), shape="box",
                                 shapeScale=[w, h, w * 0.3], color=c1 + [a], color2=c2 + [a],
                                 alphaKeys=TA.sqk([0, 0, 0.08, 1, 0.85, 1, 1, 0]), rotation=[0, 360],
                                 rotSpeed=[-140, 140], noise=lf * 2.2, noiseFreq=0.45, noiseScroll=0.3,
                                 customUV=False)])]


def k_pollen_drift(X: TA.K, nm):
    """Pollen and seed fluff riding the breeze over a sunny patch: soft warm specks that drift sideways, bob up and
    down and catch the light now and then. w, h (px box), drift (px/s, +x = right), count (alive), spark (px),
    life (s), colour, intensity (0..1)."""
    w, h = X.px("w", 300), X.px("h", 60)
    vx = X.px("drift", 6)
    n = int(X.e.get("count", 14))
    life = float(X.e.get("life", 8))
    sp = X.px("spark", 3.4)
    return [X.group(nm, [SF.psys("pollen_drift", X.A["glint"], lifetime=[life * 0.75, life * 1.25], speed=[0],
                                 velX=[vx * 0.5, vx * 1.4], velY=[-X.m * 0.5, X.m * 1.2], velZ=[-X.m, X.m],
                                 size=[sp * 0.6, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, h], color=X.col([1.0, 0.93, 0.62]) +
                                 [float(X.e.get("intensity", 0.4))],
                                 alphaKeys=[0, 0, 0.15, 0.6, 0.35, 1, 0.5, 0.45, 0.7, 1, 0.85, 0.5, 1, 0],
                                 noise=X.m * 5, noiseFreq=0.3, noiseScroll=0.2, customUV=False)])]


def k_butterflies(X: TA.K, nm):
    """Butterflies fluttering over flowers: they wander (slow scrolling noise) and beat their wings (the width
    snaps shut and open through the life). w, h (px patrol box), count (alive), span (px), life (s), colours
    [[r,g,b],[r,g,b]] (each one picks between them), alpha."""
    w, h = X.px("w", 80), X.px("h", 40)
    n = int(X.e.get("count", 3))
    life = float(X.e.get("life", 3.5))
    sp = X.px("span", 7)
    c1, c2 = _cols(X, "colours", [[1.0, 0.86, 0.35], [0.95, 0.95, 1.0]])
    a = X.op(float(X.e.get("alpha", 0.95)))
    flap = [0, 1, 0.14, 0.25, 0.28, 1, 0.42, 0.2, 0.57, 1, 0.71, 0.25, 0.85, 1, 1, 0.3]
    return [X.group(nm, [SF.psys("butterflies", _sprite_mat(X, "butterfly", mx=0.45), lifetime=[life * 0.85, life * 1.15],
                                 speed=[0], velX=[-X.m * 3, X.m * 3], velY=[-X.m, X.m * 1.5], velZ=[-X.m, X.m],
                                 size=[sp * 0.85, sp * 1.15], sizeY=[sp * 0.8, sp * 1.05], sizeKeys=flap,
                                 sizeYKeys=[0, 1, 1, 1], rate=round(n / life, 3), maxParticles=n * 2, shape="box",
                                 shapeScale=[w, h, w * 0.3], color=c1 + [a], color2=c2 + [a],
                                 alphaKeys=TA.sqk([0, 0, 0.12, 1, 0.88, 1, 1, 0]), rotation=[-15, 15],
                                 noise=X.px("wander", 18), noiseFreq=0.9, noiseScroll=0.6, customUV=False)])]


def k_songbirds(X: TA.K, nm):
    """Songbirds flitting across a treetop in bounding flight: quick flaps (height pumping) and swooping dips (strong
    vertical noise), a small flock crossing one way. w, h (px box they cross), count (alive), span (px), dir (+1 =
    to the right, -1 = left), speed (px/s), life (s), colour (dark), alpha."""
    w, h = X.px("w", 160), X.px("h", 40)
    n = int(X.e.get("count", 4))
    life = float(X.e.get("life", 7))
    sp = X.px("span", 6)
    v = X.px("speed", 22) * float(X.e.get("dir", 1))
    a = X.op(float(X.e.get("alpha", 0.85)))
    flap = [0, 1, 0.12, 0.35, 0.25, 1, 0.37, 0.35, 0.5, 1, 0.62, 0.35, 0.75, 1, 1, 0.4]
    lo, hi = sorted([v * 0.8, v * 1.2])
    return [X.group(nm, [SF.psys("songbirds", _sprite_mat(X, "songbird", mx=0.5, colour=X.col([0.16, 0.14, 0.12])),
                                 lifetime=[life * 0.85, life * 1.15], speed=[0], velX=[lo, hi],
                                 velY=[-X.m * 1.5, X.m * 1.5], velZ=[-X.m, X.m], size=[sp * 0.85, sp * 1.15],
                                 sizeY=[sp * 0.45, sp * 0.6], sizeKeys=[0, 1, 1, 1], sizeYKeys=flap,
                                 rate=round(n / life, 3), maxParticles=n * 2, shape="box",
                                 shapeScale=[w, h, w * 0.2], color=[1, 1, 1, a],
                                 alphaKeys=TA.sqk([0, 0, 0.1, 1, 0.9, 1, 1, 0]),
                                 noise=X.px("bound", 14), noiseFreq=1.1, noiseScroll=0.5, customUV=False)])]


def k_dryad_wisps(X: TA.K, nm):
    """Dryad wisps winding through the dendroid boughs: pale green-gold lights on slow sinuous paths, trailing a
    short tail (stretched along their speed), now and then flaring. w, h (px box), count (alive), spark (px),
    life (s), wind (noise, px/s), intensity (0..1)."""
    w, h = X.px("w", 120), X.px("h", 60)
    n = int(X.e.get("count", 5))
    life = float(X.e.get("life", 6))
    sp = X.px("spark", 4)
    return [X.group(nm, [SF.psys("dryad_wisps", X.A["glint"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-X.m * 2, X.m * 2], velY=[X.m * 0.2, X.m * 1.5], velZ=[-X.m, X.m],
                                 size=[sp * 0.7, sp * 1.1], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w * 0.4], color=[1, 1, 1, float(X.e.get("intensity", 0.7))],
                                 colorKeys=[0, 0.6, 1.0, 0.45, 0.5, 0.85, 1.0, 0.55, 1, 1.0, 0.9, 0.5],
                                 alphaKeys=[0, 0, 0.15, 0.7, 0.4, 0.5, 0.55, 1, 0.7, 0.5, 1, 0],
                                 renderMode=1, lengthScale=1.6, velocityScale=0.12,
                                 noise=X.px("wind", 22), noiseFreq=0.7, noiseScroll=0.4, customUV=False)])]


# ------------------------------------------------------------------------------------------------ water
def k_falls_spray(X: TA.K, nm):
    """Spray billowing off a waterfall's foot: soft white clouds well up, swell and roll outward, a prismatic tinge
    through the middle of their life (the spring's rainbow), with fine droplets flung out and stalling. width (px at
    the foot), rise (px), puff (px), rate (/s), life (s), alpha, drops (/s; 0 = none), rainbow (0..1)."""
    wd = X.px("width", 30)
    life = float(X.e.get("life", 2.6))
    vy = X.px("rise", 30) / life
    sz = X.px("puff", 40)
    a = float(X.e.get("alpha", 0.4))
    rb = float(X.e.get("rainbow", 0.5))
    tint = [0.92 + 0.08 * (1 - rb), 0.8 + 0.2 * (1 - rb), 1.0]                 # a faint violet-pink edge to cyan
    rate = float(X.e.get("rate", 4))
    sys = [SF.psys("falls_spray", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                   velX=[-vy * 0.6, vy * 0.6], velY=[vy * 0.6, vy * 1.2], velZ=[-vy * 0.2, vy * 0.4],
                   size=[sz * 0.6, sz * 1.0], rate=rate, maxParticles=max(8, int(rate * life * 2)), shape="box",
                   shapeScale=[wd, wd * 0.15, wd * 0.3], color=[1, 1, 1, 1.0],
                   colorKeys=[0, 0.95, 0.98, 1.0, 0.35] + tint + [0.6, 0.85 + 0.15 * (1 - rb), 1.0, 0.95,
                                                                   1, 0.95, 0.97, 1.0],
                   alphaKeys=TA.sqk([0, 0, 0.15, a, 0.55, a * 0.6, 1, 0]), sizeKeys=[0, 0.45, 1, 1.8],
                   rotation=[0, 360], rotSpeed=[-30, 30], noise=wd * 0.15, noiseFreq=0.6, customUV=False)]
    dr = float(X.e.get("drops", 6))
    if dr > 0:
        dv = X.px("fling", 40)
        sys.append(SF.psys("falls_drops", X.A["glint"], lifetime=[0.5, 0.9], speed=[0],
                           velX=[-dv, dv], velY=[dv * 0.2, dv * 0.9], velZ=[-dv * 0.3, dv * 0.3],
                           size=[X.m * 4.0, X.m * 5.5], rate=dr, maxParticles=max(8, int(dr * 2)), shape="box",
                           shapeScale=[wd, wd * 0.1, wd * 0.2], color=X.col([0.85, 0.95, 1.0]) + [0.6],
                           alphaKeys=[0, 0, 0.1, 1, 1, 0], drag=3.0, customUV=False))
    return [X.group(nm, sys)]


def k_pond_glitter(X: TA.K, nm):
    """Light glittering on open water: flat horizontal flashes that bloom and vanish across the surface (flattened
    so they lie on the water, not twinkle like stars). w, h (px of the water box), rate (/s), flash (px), life (s),
    colour, intensity (0..1)."""
    w, h = X.px("w", 120), X.px("h", 20)
    rate = float(X.e.get("rate", 6))
    fl = X.px("flash", 7)
    life = float(X.e.get("life", 0.7))
    return [X.group(nm, [SF.psys("pond_glitter", X.A["glint"], lifetime=[life * 0.6, life * 1.3], speed=[0],
                                 size=[fl * 0.7, fl * 1.3], sizeY=[fl * 0.22, fl * 0.35], rate=rate,
                                 maxParticles=max(8, int(rate * life * 3)), shape="box",
                                 shapeScale=[w, h * 0.2, h], color=X.col([0.92, 0.98, 1.0]) +
                                 [float(X.e.get("intensity", 0.7))], alphaKeys=[0, 0, 0.35, 1, 1, 0],
                                 sizeKeys=[0, 0.3, 0.4, 1, 1, 0.6], sizeYKeys=[0, 0.3, 0.4, 1, 1, 0.6],
                                 customUV=False)])]


def k_koi(X: TA.K, nm):
    """Koi gliding under a pond's surface: dim orange and pale shapes cruising slowly, drawn out along their swim,
    fading in and out as they go deeper. w, h (px of the water box), count (alive), fish (px), speed (px/s),
    life (s), colours [[r,g,b],[r,g,b]], alpha."""
    w, h = X.px("w", 100), X.px("h", 14)
    n = int(X.e.get("count", 3))
    life = float(X.e.get("life", 7))
    f = X.px("fish", 6)
    v = X.px("speed", 6)
    c1, c2 = _cols(X, "colours", [[1.0, 0.5, 0.15], [1.0, 0.92, 0.85]])
    a = X.op(float(X.e.get("alpha", 0.55)))
    return [X.group(nm, [SF.psys("koi", _sprite_mat(X, "koi", mx=0.6), lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-v, v], velY=[0, 0], velZ=[-v * 0.4, v * 0.4], size=[f * 0.8, f * 1.2],
                                 rate=round(n / life, 3), maxParticles=n * 2, shape="box",
                                 shapeScale=[w, h * 0.1, h], color=c1 + [a], color2=c2 + [a],
                                 alphaKeys=TA.sqk([0, 0, 0.25, 1, 0.6, 0.5, 0.8, 1, 1, 0]),
                                 sizeY=[f * 0.4, f * 0.6], noise=v * 0.6, noiseFreq=0.25, noiseScroll=0.15, customUV=False)])]


def k_fortune_jets(X: TA.K, nm):
    """The Fountain of Fortune tossing up gold: bright flecks leap out of the pool, stall at the top (drag) and
    sink back fading, like coins thrown into the light. width (px of the jet's foot), leap (px/s at launch), rate
    (/s), spark (px), colour, intensity (0..1)."""
    wd = X.px("width", 12)
    v = X.px("leap", 70)
    rate = float(X.e.get("rate", 5))
    sp = X.px("spark", 3.8)
    return [X.group(nm, [SF.psys("fortune_jets", X.A["glint"], lifetime=[1.2, 1.8], speed=[0],
                                 velX=[-v * 0.25, v * 0.25], velY=[v * 0.7, v * 1.1], velZ=[-v * 0.1, v * 0.1],
                                 size=[sp * 0.7, sp * 1.2], rate=rate, maxParticles=max(8, int(rate * 4)),
                                 shape="box", shapeScale=[wd, wd * 0.1, wd * 0.2], drag=1.8,
                                 color=[1, 1, 1, float(X.e.get("intensity", 0.85))],
                                 colorKeys=[0, 1.0, 0.95, 0.7, 0.4] + X.col([1.0, 0.8, 0.3]) + [1, 1.0, 0.6, 0.2],
                                 alphaKeys=[0, 0, 0.08, 1, 0.5, 0.9, 1, 0], sizeKeys=[0, 0.6, 0.15, 1, 1, 0.5],
                                 customUV=False)])]


# ------------------------------------------------------------------------------------------------ creatures and magic
def k_pegasus_feathers(X: TA.K, nm):
    """White feathers shed by a pegasus: one at a time they slip off the wings and see-saw slowly down (a wide
    pendulum, a gentle spin), pale against the sky. w, h (px of the wings), fall (px/s), feather (px), rate (/s),
    life (s), alpha."""
    w, h = X.px("w", 50), X.px("h", 14)
    vy = X.px("fall", 7)
    fe = X.px("feather", 7)
    life = float(X.e.get("life", 7))
    rate = float(X.e.get("rate", 0.35))
    a = X.op(float(X.e.get("alpha", 0.85)))
    return [X.group(nm, [SF.psys("pegasus_feathers", _sprite_mat(X, "feather", mx=0.45), lifetime=[life * 0.8, life * 1.2],
                                 speed=[0], velX=[-vy * 0.3, vy * 0.5], velY=[-vy * 1.2, -vy * 0.8],
                                 velZ=[-vy * 0.2, vy * 0.2], size=[fe * 0.8, fe * 1.2], rate=rate,
                                 maxParticles=max(4, int(rate * life * 2)), shape="box", shapeScale=[w, h, w * 0.3],
                                 color=X.col([0.97, 0.97, 1.0]) + [a],
                                 alphaKeys=TA.sqk([0, 0, 0.1, 1, 0.8, 1, 1, 0]), rotation=[0, 360],
                                 rotSpeed=[-45, 45], noise=fe * 2.6, noiseFreq=0.3, customUV=False)])]


def k_unicorn_shimmer(X: TA.K, nm):
    """The unicorn glade's shimmer: pearly sparkles rise slowly out of the grass, each running pink, lilac, sky blue
    and gold over its life and pulsing twice, under a faint pearly glow that breathes. w, h (px box), count (alive),
    rise (px over a life), spark (px), life (s), intensity (0..1), glow (px; 0 = none)."""
    w, h = X.px("w", 200), X.px("h", 30)
    n = int(X.e.get("count", 14))
    life = float(X.e.get("life", 4))
    vy = X.px("rise", 30) / life
    sp = X.px("spark", 3.6)
    sys = [SF.psys("unicorn_shimmer", X.A["glint"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                   velX=[-vy * 0.2, vy * 0.2], velY=[vy * 0.6, vy * 1.3], velZ=[-vy * 0.2, vy * 0.2],
                   size=[sp * 0.6, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2, shape="box",
                   shapeScale=[w, h, h], color=[1, 1, 1, float(X.e.get("intensity", 0.75))],
                   colorKeys=[0, 1.0, 0.7, 0.9, 0.33, 0.8, 0.7, 1.0, 0.66, 0.6, 0.9, 1.0, 1, 1.0, 0.92, 0.6],
                   alphaKeys=[0, 0, 0.15, 1, 0.35, 0.3, 0.55, 1, 0.75, 0.35, 1, 0],
                   sizeKeys=[0, 0.5, 0.3, 1, 1, 0.6], customUV=False)]
    g = float(X.e.get("glow", 0))
    if g > 0:
        gs = X.px("glow", 60) * 2.0
        per = float(X.e.get("period", 5))
        sys.append(SF.psys("unicorn_glow", X.A["glow"], lifetime=[per, per * 1.2], speed=[0],
                           size=[gs * 0.9, gs * 1.1], sizeY=[gs * 0.35, gs * 0.45], rate=round(2.0 / per, 3),
                           maxParticles=4, radius=gs * 0.05, color=[0.92, 0.88, 1.0, float(X.e.get("glowIntensity", 0.3))],
                           alphaKeys=[0, 0, 0.5, 1, 1, 0], customUV=False))
    return [X.group(nm, sys)]


def k_lantern_moths(X: TA.K, nm):
    """A stone lantern breathing pale elven light, with moths circling it: one soft green-white light swelling and
    sinking slowly (no flicker: no flame), and a few pale specks orbiting close and fluttering. size (px of the
    light), period (s per breath), moths (count; 0 = none), radius (px of their orbit), colour, intensity (0..1)."""
    s = X.px("size", 16) * 2.2         # the glow sprite fills about the middle half of its quad
    per = float(X.e.get("period", 4.5))
    sys = [SF.psys("lantern_light", X.A["glow"], lifetime=[per * 0.95, per * 1.05], speed=[0], size=[s * 0.9, s * 1.1],
                   rate=round(2.0 / per, 3), maxParticles=4, radius=s * 0.01,
                   color=X.col([0.85, 1.0, 0.82]) + [float(X.e.get("intensity", 0.4))],
                   alphaKeys=[0, 0, 0.3, 0.8, 0.5, 1, 0.75, 0.75, 1, 0], customUV=False)]
    n = int(X.e.get("moths", 3))
    if n > 0:
        r = X.px("radius", 9)
        om = 2 * math.pi / 2.2
        sys.append(SF.psys("lantern_moths", X.A["glint"], lifetime=[3.0, 4.0], speed=[0],
                           orbitalX=[0, 0], orbitalY=[om * 0.7, om * 1.3], orbitalZ=[0, 0], radial=[0, 0],
                           velX=[0, 0], velY=[-X.m * 0.5, X.m * 0.5], velZ=[0, 0],
                           size=[X.m * 4.5, X.m * 5.5], rate=round(n / 3.5, 3), maxParticles=n * 2,
                           shape="circle", radius=r, radiusThickness=0.3, shapeRot=[90, 0, 0],
                           color=[1.0, 0.98, 0.9, 0.55],
                           alphaKeys=[0, 0, 0.1, 1, 0.3, 0.4, 0.5, 1, 0.7, 0.45, 0.9, 1, 1, 0],
                           noise=r * 0.35, noiseFreq=2.0, customUV=False))
    return [X.group(nm, sys)]


def k_dragon_glide(X: TA.K, nm):
    """Dragons gliding round their cliffs: big bat-winged silhouettes circling slowly on a thermal, a few deep wing
    beats then a long glide (the height dips on a beat), tinted green-bronze by the haze. radius (px of the circle),
    count, period (s per circle), span (px wingspan), colour, alpha."""
    r = X.px("radius", 120)
    per = float(X.e.get("period", 26))
    n = int(X.e.get("count", 2))
    span = X.px("span", 24)
    life = per * 1.3
    beat = [0, 1, 0.06, 0.45, 0.12, 1, 0.18, 0.45, 0.24, 1, 0.6, 1, 0.66, 0.5, 0.72, 1]
    a = X.op(float(X.e.get("alpha", 0.85)))
    mat = _sprite_mat(X, "dragon", mx=0.5, colour=X.col([0.24, 0.3, 0.2]))
    return [X.group(nm, [SF.psys("dragon_glide", mat, lifetime=[life * 0.9, life * 1.1], speed=[0],
                                 size=[span * 0.85, span], sizeY=[span * 0.5, span * 0.55], sizeKeys=[0, 1, 1, 1],
                                 sizeYKeys=beat, rate=round(n / life, 4), maxParticles=n * 2, shape="circle",
                                 radius=r, radiusThickness=0.25, shapeRot=[90, 0, 0],
                                 orbitalX=[0, 0], orbitalY=[2 * math.pi / per * 0.85, 2 * math.pi / per * 1.15],
                                 orbitalZ=[0, 0], radial=[0, 0], velX=[0, 0], velY=[-X.m * 0.8, X.m * 0.8],
                                 velZ=[0, 0], color=[1, 1, 1, a], alphaKeys=TA.sqk([0, 0, 0.07, 1, 0.93, 1, 1, 0]),
                                 customUV=False)])]


def k_guardian_aura(X: TA.K, nm):
    """The Spirit Guardian's aura: a tall golden halo that swells and sinks slowly round the statue, and gold flecks
    spiralling up its length. size (px halo width), tall (halo height / width), period (s per breath), radius (px of
    the spiral), rise (px over a life), count (flecks alive), colour, intensity (0..1)."""
    s = X.px("size", 50)
    tall = float(X.e.get("tall", 2.6))
    per = float(X.e.get("period", 5))
    c = X.col([1.0, 0.82, 0.38])
    sys = [SF.psys("guardian_halo", X.A["glow"], lifetime=[per * 0.95, per * 1.05], speed=[0],
                   size=[s * 0.95, s * 1.05], sizeY=[s * tall * 0.95, s * tall * 1.05], rate=round(2.0 / per, 3),
                   maxParticles=4, radius=s * 0.02, color=c + [float(X.e.get("intensity", 0.35))],
                   alphaKeys=[0, 0, 0.5, 1, 1, 0], customUV=False)]
    r = X.px("radius", 14)
    life = 5.0
    vy = X.px("rise", 120) / life
    n = int(X.e.get("count", 10))
    om = 2 * math.pi / 3.0
    sys.append(SF.psys("guardian_flecks", X.A["glint"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                       velX=[0, 0], velY=[vy * 0.8, vy * 1.2], velZ=[0, 0], orbitalX=[0, 0],
                       orbitalY=[om * 0.8, om * 1.2], orbitalZ=[0, 0], radial=[0, 0], size=[X.m * 4.5, X.m * 6],
                       rate=round(n / life, 3), maxParticles=n * 2, shape="circle", radius=r, radiusThickness=0.2,
                       shapeRot=[90, 0, 0], color=c + [0.85], alphaKeys=[0, 0, 0.15, 1, 0.7, 0.7, 1, 0],
                       customUV=False))
    return [X.group(nm, sys)]


# ------------------------------------------------------------------------------------------------ dwellings and crafts
def k_shoji_glow(X: TA.K, nm):
    """A lit shoji paper screen: a soft warm-cream panel of light, built from several overlapping soft lights spread
    over the panel's box (one glow sprite reads as a round blob; the glow fills only the middle of its quad, so each
    light is drawn about twice the panel's short side), shivering slowly as the lamp behind moves. w, h (px of the
    panel), period (s), colour, intensity (0..1, per light)."""
    w, h = X.px("w", 20), X.px("h", 14)
    per = float(X.e.get("period", 3.5))
    short = min(w, h)
    n = max(2, int(round(max(w, h) / short * 1.5)))
    return [X.group(nm, [SF.psys("shoji_glow", X.A["glow"], lifetime=[per * 0.8, per * 1.2], speed=[0],
                                 size=[short * 1.9, short * 2.4], rate=round(n / per, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[max(w - short, short * 0.1), max(h - short, short * 0.1),
                                                          short * 0.1],
                                 color=X.col([1.0, 0.86, 0.6]) + [float(X.e.get("intensity", 0.35))],
                                 alphaKeys=[0, 0, 0.25, 0.9, 0.4, 0.75, 0.6, 1, 0.8, 0.85, 1, 0], customUV=False)])]


def k_hoof_dust(X: TA.K, nm):
    """Dust kicked up in a paddock: low tan puffs that roll sideways along the ground, swell and settle.
    w, h (px box on the ground), puff (px), drift (px/s, +x = right), rate (/s), life (s), colour, alpha."""
    w, h = X.px("w", 80), X.px("h", 8)
    sz = X.px("puff", 30)
    vx = X.px("drift", 6)
    life = float(X.e.get("life", 3.5))
    rate = float(X.e.get("rate", 0.8))
    a = float(X.e.get("alpha", 0.3))
    return [X.group(nm, [SF.psys("hoof_dust", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[vx * 0.3, vx * 1.3], velY=[X.m * 0.3, X.m * 1.5], velZ=[-vx * 0.2, vx * 0.2],
                                 size=[sz * 0.6, sz * 1.0], sizeY=[sz * 0.35, sz * 0.55], sizeKeys=[0, 0.4, 1, 1.6],
                                 sizeYKeys=[0, 0.4, 1, 1.3], rate=rate, maxParticles=max(4, int(rate * life * 2)),
                                 shape="box", shapeScale=[w, h * 0.2, h], color=X.col([0.68, 0.58, 0.42]) + [1.0],
                                 alphaKeys=TA.sqk([0, 0, 0.12, a, 0.5, a * 0.6, 1, 0]), rotation=[0, 360],
                                 rotSpeed=[-10, 10], customUV=False)])]


def k_anvil_sparks(X: TA.K, nm):
    """Sparks off an elven smith's anvil: short bright streaks spraying up and out in a fan (stretched along their
    speed), slowed fast by the air, orange going cherry. width (px), fling (px/s), rate (/s), colour,
    intensity (0..1)."""
    wd = X.px("width", 6)
    v = X.px("fling", 60)
    rate = float(X.e.get("rate", 7))
    return [X.group(nm, [SF.psys("anvil_sparks", X.A["glint"], lifetime=[0.35, 0.7], speed=[0],
                                 velX=[-v * 0.7, v * 0.7], velY=[v * 0.3, v * 1.0], velZ=[-v * 0.2, v * 0.2],
                                 size=[X.m * 4.0, X.m * 5.0], rate=rate, maxParticles=max(8, int(rate * 1.5)),
                                 shape="box", shapeScale=[wd, wd * 0.2, wd * 0.3], drag=2.5,
                                 color=[1, 1, 1, float(X.e.get("intensity", 0.9))],
                                 colorKeys=[0, 1.0, 0.92, 0.6, 0.4] + X.col([1.0, 0.55, 0.15]) + [1, 0.8, 0.2, 0.08],
                                 alphaKeys=[0, 1, 0.6, 0.8, 1, 0], renderMode=1, lengthScale=1.0,
                                 velocityScale=0.08, customUV=False)])]


KINDS = {"falling_leaves": k_falling_leaves, "pollen_drift": k_pollen_drift, "butterflies": k_butterflies,
         "songbirds": k_songbirds, "dryad_wisps": k_dryad_wisps, "falls_spray": k_falls_spray,
         "pond_glitter": k_pond_glitter, "koi": k_koi, "fortune_jets": k_fortune_jets,
         "pegasus_feathers": k_pegasus_feathers, "unicorn_shimmer": k_unicorn_shimmer,
         "lantern_moths": k_lantern_moths, "dragon_glide": k_dragon_glide, "guardian_aura": k_guardian_aura,
         "shoji_glow": k_shoji_glow, "hoof_dust": k_hoof_dust, "anvil_sparks": k_anvil_sparks}
