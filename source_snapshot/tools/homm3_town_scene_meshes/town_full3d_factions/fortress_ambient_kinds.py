"""Fortress's own ambient kinds (loaded by town_full3d_ambient.py stage): a lizardfolk town on a bog. Swamp bubbles
that swell and pop, ripple rings on still water, dragonflies darting round the hive, fireflies blinking in the reeds,
flat fog banks lying on the water, green miasma coiling out of the gorgon and lizard dens, spores puffed off the
bog mushrooms, the grail orchid's golden pollen spiralling up, marsh gas burping off the open water, midge columns
dancing over the shore and the mage hut's runes beating slowly.

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), every velocity curve in one system and every orbital/radial curve
in one system as [min, max] pairs. Gradient keys stay at 8 or fewer per curve (Unity's limit).
Sprites (ring, bubble) are generated next to the prefab like the shared bird silhouette.
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


def _draw_ring(path):
    """A thin soft ring (a ripple seen face-on; the particle's sizeY flattens it onto the water)."""
    import cv2
    im = np.zeros((128, 128), np.uint8)
    cv2.circle(im, (64, 64), 52, 255, 13)
    _png(path, cv2.GaussianBlur(im, (0, 0), 2.5))


def _draw_bubble(path):
    """A bog bubble: a pale rim, a dimmer skin and a bright highlight up-left."""
    import cv2
    im = np.zeros((64, 64), np.uint8)
    cv2.circle(im, (32, 32), 27, 150, -1)
    cv2.circle(im, (32, 32), 26, 235, 7)
    cv2.ellipse(im, (23, 22), (8, 6), -35, 0, 360, 255, -1)
    _png(path, cv2.GaussianBlur(im, (0, 0), 1.2))


SPRITES = {"ring": _draw_ring, "bubble": _draw_bubble}


def _sprite_mat(X: TA.K, name: str, blend: float = 1.0, mx: float = 0.5):
    pth = S.STAGE / X.key / f"amb_fr_{name}.png"
    SPRITES[name](pth)
    asset = f"{S.ASSET_ROOT}/{X.key}/amb_fr_{name}.png"
    return X.M.material("Homm3ConfluxVfxUber", [X.M.tex("_Texture", asset, clamp=True),
                                               X.M.tex("_Mask", asset, clamp=True)],
                        {"_Min": 0.05, "_Max": mx, "_Lerp": 1.0, "_Multiply": 1.0, "_Blend": blend, "_xSpeed01": 0,
                         "_ySpeed01": 0, "_xSpeed02": 0, "_ySpeed02": 0, "_UseTwo": 0.0, "_CameraOffset": 0.0,
                         "_UseCamOffset": 0.0}, {"_Color": [1.0, 1.0, 1.0, 1.0]})


def _ring_sys(X: TA.K, nm, w, h, ring, life, rate, flat, colour, alpha):
    return SF.psys(nm, _sprite_mat(X, "ring", mx=0.45), lifetime=[life * 0.8, life * 1.2], speed=[0],
                   size=[ring * 0.7, ring * 1.2], sizeY=[ring * 0.7 * flat, ring * 1.2 * flat], rate=rate,
                   maxParticles=max(4, int(rate * life * 2.5)), shape="box", shapeScale=[w, h * 0.2, h],
                   color=colour + [math.sqrt(alpha)], alphaKeys=TA.sqk([0, 0, 0.08, 1, 0.45, 0.55, 1, 0]),
                   sizeKeys=[0, 0.08, 0.35, 0.6, 1, 1], customUV=False)


# ------------------------------------------------------------------------------------------------ water
def k_ripples(X: TA.K, nm):
    """Ripple rings spreading on still water (round a lily pad, a piling, a stilt): w, h (px of the box the rings
    are born in), ring (px, final width), flat (height / width of a ring on the water), life (s), rate (/s),
    colour, alpha."""
    w, h = X.px("w", 20), X.px("h", 6)
    return [X.group(nm, [_ring_sys(X, "ripples", w, h, X.px("ring", 22), float(X.e.get("life", 2.8)),
                                   float(X.e.get("rate", 0.6)), float(X.e.get("flat", 0.26)),
                                   X.col([0.8, 0.86, 0.78]), float(X.e.get("alpha", 0.5)))])]


def k_bubbles(X: TA.K, nm):
    """Bog bubbles: a blister swells on the water, wobbles and pops, leaving a small ring. w, h (px box), bubble (px),
    rate (/s), life (s), colour (murky pale), alpha, ring (px of the pop ring; 0 = none)."""
    w, h = X.px("w", 40), X.px("h", 8)
    b = X.px("bubble", 7.0)
    life = float(X.e.get("life", 1.6))
    rate = float(X.e.get("rate", 1.5))
    col = X.col([0.74, 0.8, 0.62])
    sys = [SF.psys("bubbles", _sprite_mat(X, "bubble", mx=0.55), lifetime=[life * 0.7, life * 1.3], speed=[0],
                   velX=[-X.m * 0.1, X.m * 0.1], velY=[X.m * 0.1, X.m * 0.5], velZ=[0, 0],
                   size=[b * 0.6, b * 1.4], rate=rate, maxParticles=max(6, int(rate * life * 3)), shape="box",
                   shapeScale=[w, h * 0.2, h], color=col + [X.op(float(X.e.get("alpha", 0.8)))],
                   alphaKeys=TA.sqk([0, 0, 0.15, 0.8, 0.8, 1, 0.88, 0.6, 0.9, 0]),
                   sizeKeys=[0, 0.1, 0.55, 0.8, 0.7, 0.92, 0.82, 1.15, 0.9, 1.3], customUV=False)]
    ring = float(X.e.get("ring", 16))
    if ring > 0:
        sys.append(_ring_sys(X, "pops", w, h, X.px("ring", 16), 1.5, rate * 0.6, 0.3, col,
                             float(X.e.get("alpha", 0.8)) * 0.55))
    return [X.group(nm, sys)]


def k_swamp_gas(X: TA.K, nm):
    """Marsh gas burping off the bog: now and then a sickly yellow-green puff wells up off the water, rises a little
    and thins out. w, h (px box), puff (px), rise (px over a life), rate (/s), life (s), colour, alpha."""
    w, h = X.px("w", 60), X.px("h", 10)
    life = float(X.e.get("life", 5.0))
    vy = X.px("rise", 24) / life
    rate = float(X.e.get("rate", 0.35))
    sz = X.px("puff", 50)
    return [X.group(nm, [SF.psys("swamp_gas", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-vy * 0.15, vy * 0.25], velY=[vy * 0.6, vy * 1.2], velZ=[0, 0],
                                 size=[sz * 0.6, sz * 1.1], rate=rate, maxParticles=max(4, int(rate * life * 3)),
                                 shape="box", shapeScale=[w, h * 0.2, h], color=X.col([0.66, 0.72, 0.42]) + [1.0],
                                 colorKeys=[0, 0.8, 0.85, 0.45, 0.5, 0.66, 0.72, 0.45, 1, 0.55, 0.6, 0.52],
                                 alphaKeys=TA.sqk([0, 0, 0.12, float(X.e.get("alpha", 0.32)), 0.55,
                                                   float(X.e.get("alpha", 0.32)) * 0.6, 1, 0]),
                                 sizeKeys=[0, 0.25, 0.15, 0.7, 1, 2.0], rotation=[0, 360], rotSpeed=[-12, 12],
                                 noise=sz * 0.2, noiseFreq=0.4, customUV=False)])]


def k_fog_bank(X: TA.K, nm):
    """A fog bank lying flat on the bog: wide, low, very thin sheets that drift and slowly breathe. w, h (px box),
    puff (px width of a sheet), flat (sheet height / width), drift (px/s, +x = right), life (s), count (alive),
    colour (swamp grey-green), alpha."""
    w, h = X.px("w", 400), X.px("h", 24)
    sz = X.px("puff", 160)
    flat = float(X.e.get("flat", 0.28))
    vx = X.px("drift", 3)
    life = float(X.e.get("life", 22))
    n = int(X.e.get("count", 6))
    a = float(X.e.get("alpha", 0.16))
    return [X.group(nm, [SF.psys("fog_bank", X.A["puff"], lifetime=[life * 0.85, life * 1.15], speed=[0],
                                 velX=[vx * 0.6, vx * 1.3], velY=[-X.m * 0.05, X.m * 0.05], velZ=[0, 0],
                                 size=[sz * 0.75, sz * 1.25], sizeY=[sz * 0.75 * flat, sz * 1.25 * flat],
                                 rate=round(n / life, 3), maxParticles=n * 2, shape="box",
                                 shapeScale=[w, h, h * 0.6], color=X.col([0.6, 0.66, 0.56]) + [1.0],
                                 alphaKeys=TA.sqk([0, 0, 0.25, a, 0.5, a * 0.75, 0.75, a, 1, 0]),
                                 sizeKeys=[0, 0.8, 0.5, 1.05, 1, 1.25], customUV=False)])]


# ------------------------------------------------------------------------------------------------ creatures
def k_dragonflies(X: TA.K, nm):
    """Dragonflies hunting round a point: they hover, then dart (strong scrolling noise; stretched along their speed
    so a dart reads as a streak), wings flashing iridescent teal to green to bronze. w, h (px of the patrol box),
    count (alive), span (px), life (s), dart (noise strength, px/s), intensity (0..1)."""
    w, h = X.px("w", 60), X.px("h", 30)
    n = int(X.e.get("count", 3))
    life = float(X.e.get("life", 6))
    sp = X.px("span", 4)
    dart = X.px("dart", 40)
    return [X.group(nm, [SF.psys("dragonflies", X.A["glint"], lifetime=[life * 0.8, life * 1.2],
                                 speed=[0], size=[sp * 0.85, sp * 1.15], rate=round(n / life, 3),
                                 maxParticles=n * 2, shape="box", shapeScale=[w, h, w * 0.4],
                                 color=[1, 1, 1, float(X.e.get("intensity", 0.85))],
                                 colorKeys=[0, 0.2, 0.85, 0.9, 0.35, 0.3, 0.95, 0.5, 0.7, 0.85, 0.7, 0.3,
                                            1, 0.25, 0.75, 0.95],
                                 alphaKeys=[0, 0, 0.08, 1, 0.3, 0.6, 0.5, 1, 0.75, 0.55, 0.92, 1, 1, 0],
                                 renderMode=1, lengthScale=1.0, velocityScale=0.06,
                                 noise=dart, noiseFreq=1.6, noiseScroll=1.2, customUV=False)])]


def k_fireflies(X: TA.K, nm):
    """Fireflies in the reeds: yellow-green lights that blink twice and go dark while drifting lazily. w, h (px box),
    count (alive), spark (px), life (s), colour, intensity (0..1)."""
    w, h = X.px("w", 80), X.px("h", 40)
    n = int(X.e.get("count", 6))
    life = float(X.e.get("life", 4.5))
    sp = X.px("spark", 4.5)
    a = float(X.e.get("intensity", 0.9))
    return [X.group(nm, [SF.psys("fireflies", X.A["glint"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 velX=[-X.m * 1.5, X.m * 1.5], velY=[-X.m * 0.8, X.m * 1.6], velZ=[-X.m, X.m],
                                 size=[sp * 0.7, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w * 0.4], color=X.col([0.72, 1.0, 0.28]) + [a],
                                 alphaKeys=[0, 0, 0.1, 1, 0.2, 0.05, 0.32, 0.9, 0.45, 0, 0.75, 0, 0.85, 0.7, 1, 0],
                                 noise=X.m * 4, noiseFreq=0.35, customUV=False)])]


def k_midges(X: TA.K, nm):
    """A midge column dancing over the shore: tiny light-catching specks bobbing in a tall narrow cloud. w, h (px of
    the column), count (alive), speck (px), colour, alpha."""
    w, h = X.px("w", 10), X.px("h", 26)
    n = int(X.e.get("count", 14))
    life = float(X.e.get("life", 3.0))
    sp = X.px("speck", 1.9)
    return [X.group(nm, [SF.psys("midges", X.A["glint"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 size=[sp * 0.7, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w], color=X.col([0.95, 0.92, 0.75]) +
                                 [float(X.e.get("alpha", 0.45))], alphaKeys=[0, 0, 0.15, 1, 0.85, 1, 1, 0],
                                 noise=h * 0.7, noiseFreq=2.2, noiseScroll=0.8, customUV=False)])]


# ------------------------------------------------------------------------------------------------ dens and flora
def k_miasma(X: TA.K, nm):
    """Green miasma coiling out of a den: heavy vapour that turns slowly about its source, creeps outward and
    climbs only a little, green going grey as it thins. radius (px at the source), rise (px), period (s per turn),
    puff (px), count (alive), life (s), colour (fresh vapour), alpha."""
    r = X.px("radius", 14)
    life = float(X.e.get("life", 7))
    vy = X.px("rise", 18) / life
    per = float(X.e.get("period", 9))
    n = int(X.e.get("count", 8))
    sz = X.px("puff", 60)
    om = 2 * math.pi / per
    c = X.col([0.55, 0.78, 0.35])
    return [X.group(nm, [SF.psys("miasma", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-vy * 0.2, vy * 0.2], velY=[vy * 0.5, vy * 1.1], velZ=[-vy * 0.2, vy * 0.2],
                                 orbitalX=[0, 0], orbitalY=[om * 0.8, om * 1.2], orbitalZ=[0, 0],
                                 radial=[r * 0.05, r * 0.15], size=[sz * 0.6, sz * 1.0], rate=round(n / life, 3),
                                 maxParticles=n * 2, shape="circle", radius=r, radiusThickness=0.7,
                                 shapeRot=[90, 0, 0], color=[1, 1, 1, 1.0],
                                 colorKeys=[0] + c + [0.6] + [0.5 * c[0] + 0.25, 0.5 * c[1] + 0.25, 0.5 * c[2] + 0.25]
                                 + [1, 0.5, 0.52, 0.48],
                                 alphaKeys=TA.sqk([0, 0, 0.2, float(X.e.get("alpha", 0.32)), 0.65,
                                                   float(X.e.get("alpha", 0.32)) * 0.7, 1, 0]),
                                 sizeKeys=[0, 0.4, 1, 1.9], rotation=[0, 360], rotSpeed=[-15, 15],
                                 noise=r * 0.25, noiseFreq=0.5, customUV=False)])]


def k_spore_puff(X: TA.K, nm):
    """A bog mushroom shedding spores: pale motes leak off the cap, drift out and sink slowly, glinting faintly.
    w (px of the cap), fall (px/s), drift (px/s, +x = right), count (alive), life (s), spark (px), colour, alpha."""
    w = X.px("w", 14)
    vy = X.px("fall", 3)
    vx = X.px("drift", 2)
    n = int(X.e.get("count", 8))
    life = float(X.e.get("life", 4))
    sp = X.px("spark", 3.4)
    return [X.group(nm, [SF.psys("spore_puff", X.A["glint"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 velX=[-vx, vx * 1.6], velY=[-vy * 1.2, vy * 0.4], velZ=[-vx * 0.5, vx * 0.5],
                                 size=[sp * 0.6, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, w * 0.15, w * 0.4],
                                 color=X.col([1.0, 0.75, 0.85]) + [float(X.e.get("alpha", 0.5))],
                                 alphaKeys=[0, 0, 0.15, 1, 0.6, 0.7, 1, 0], sizeKeys=[0, 0.6, 0.2, 1, 1, 0.6],
                                 noise=w * 0.15, noiseFreq=0.8, customUV=False)])]


def k_grail_pollen(X: TA.K, nm):
    """The grail orchid breathing out its pollen: golden grains spiral up out of the bloom, widen and drift off,
    turning rose as they fade. radius (px at the bloom), rise (px over a life), period (s per turn), count (alive),
    life (s), spark (px), intensity (0..1)."""
    r = X.px("radius", 14)
    life = float(X.e.get("life", 5))
    vy = X.px("rise", 70) / life
    per = float(X.e.get("period", 3.5))
    n = int(X.e.get("count", 14))
    sp = X.px("spark", 3.6)
    om = 2 * math.pi / per
    return [X.group(nm, [SF.psys("grail_pollen", X.A["glint"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[0, 0], velY=[vy * 0.7, vy * 1.2], velZ=[0, 0],
                                 orbitalX=[0, 0], orbitalY=[om * 0.85, om * 1.15], orbitalZ=[0, 0],
                                 radial=[r * 0.1, r * 0.35], size=[sp * 0.6, sp * 1.2], rate=round(n / life, 3),
                                 maxParticles=n * 2, shape="circle", radius=r, radiusThickness=0.4,
                                 shapeRot=[90, 0, 0], color=[1, 1, 1, float(X.e.get("intensity", 0.75))],
                                 colorKeys=[0, 1.0, 0.86, 0.4, 0.5, 1.0, 0.7, 0.35, 1, 1.0, 0.45, 0.5],
                                 alphaKeys=[0, 0, 0.12, 1, 0.6, 0.8, 1, 0], sizeKeys=[0, 0.5, 0.3, 1, 1, 0.5],
                                 noise=r * 0.1, noiseFreq=0.7, customUV=False)])]


def k_rune_pulse(X: TA.K, nm):
    """A rune that beats: one light at a time, a double heartbeat then a long rest (no overlapping flicker).
    size (px), period (s per beat), colour, intensity (0..1)."""
    s = X.px("size", 14)
    per = float(X.e.get("period", 3.2))
    return [X.group(nm, [SF.psys("rune_pulse", X.A["glow"], lifetime=[per * 0.98, per * 0.98], speed=[0], size=[s, s],
                                 rate=round(1.0 / per, 4), maxParticles=1, radius=s * 0.01,
                                 color=X.col([0.7, 0.35, 1.0]) + [float(X.e.get("intensity", 0.45))],
                                 alphaKeys=[0, 0.15, 0.1, 1, 0.2, 0.35, 0.3, 0.85, 0.5, 0.2, 1, 0.15],
                                 customUV=False)])]


KINDS = {"ripples": k_ripples, "bubbles": k_bubbles, "swamp_gas": k_swamp_gas, "fog_bank": k_fog_bank,
         "dragonflies": k_dragonflies, "fireflies": k_fireflies, "midges": k_midges, "miasma": k_miasma,
         "spore_puff": k_spore_puff, "grail_pollen": k_grail_pollen, "rune_pulse": k_rune_pulse}
