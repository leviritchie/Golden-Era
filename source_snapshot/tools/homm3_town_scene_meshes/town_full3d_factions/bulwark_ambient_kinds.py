"""Bulwark's own ambient kinds (loaded by town_full3d_ambient.py stage): a northern town in deep snow under a green
aurora. Snow falling in depth layers, aurora rays rippling over the peaks, warm breath steaming out of the cave
dwellings and the mammoth tent in slow beats, peat smoke from the hearths leaning on the east wind, forge and pyre
light pooled on the snow, ice-star glints on the shards and the ice spires, arctic sea smoke rising off the open
river, powder sifting off the eaves, meltwater dripping off the warm forge and the hall, ravens flapping round the
towers, cinders and ash off the great pyre, diamond dust hanging in the moonlight, snow snaking over the open field
and rime crystals spiralling up the mage spire.

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), every velocity curve in one system and every orbital/radial curve in
one system as [min, max] pairs. Gradient keys stay at 8 or fewer per curve (Unity's limit). Local axes: x = screen
right, y = up, z = depth. The wind blows from the east (the mountains, screen right) to the west everywhere: snow,
smoke, sea smoke and drifting powder all lean left.
Sprites (flake, star, raven, drop) are generated next to the prefab like the shared bird silhouette.
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


def _draw_flake(path):
    """A snowflake at game distance: a soft round dot with a brighter core."""
    import cv2
    im = np.zeros((64, 64), np.uint8)
    cv2.circle(im, (32, 32), 22, 150, -1)
    cv2.circle(im, (32, 32), 13, 255, -1)
    _png(path, cv2.GaussianBlur(im, (0, 0), 4.0))


def _draw_star(path):
    """A four-point ice star: spikes on a hot core (reads as a glint, not a round blob). Drawn 10-25 px wide at
    game distance, so spikes and core are a few sprite-px wide or they vanish."""
    import cv2
    im = np.zeros((128, 128), np.float32)
    yy, xx = np.mgrid[0:128, 0:128].astype(np.float32) - 63.5
    r = np.hypot(xx, yy) + 1e-3
    spikes = np.exp(-np.abs(yy) / 5.0) * np.clip(1 - np.abs(xx) / 62, 0, 1) ** 1.2 + \
        np.exp(-np.abs(xx) / 5.0) * np.clip(1 - np.abs(yy) / 62, 0, 1) ** 1.2
    diag = (np.exp(-np.abs(xx - yy) / 4.0) + np.exp(-np.abs(xx + yy) / 4.0)) * np.clip(1 - r / 34, 0, 1) ** 2 * 0.4
    core = np.exp(-(r / 16.0) ** 2)
    im = np.clip(spikes + diag + core, 0, 1)
    _png(path, (cv2.GaussianBlur(im, (0, 0), 0.8) * 255).astype(np.uint8))


def _draw_raven(path):
    """A raven seen side-on in flapping flight: wings raised in a deep V with fingered tips, wedge tail, heavy beak,
    white on black, 128 x 64."""
    import cv2
    im = np.zeros((64, 128), np.uint8)
    body = np.array([[40, 40], [52, 36], [70, 35], [84, 36], [92, 33], [98, 34], [94, 38], [86, 41], [70, 44],
                     [52, 44], [38, 46], [30, 50], [28, 44]], np.int32)
    cv2.fillPoly(im, [body], 255)
    wing_l = np.array([[56, 37], [44, 24], [34, 12], [28, 6], [33, 8], [30, 3], [37, 7], [36, 1], [42, 8], [44, 4],
                       [48, 14], [62, 30], [68, 36]], np.int32)
    wing_r = np.array([[66, 36], [74, 22], [80, 10], [84, 4], [86, 9], [90, 5], [90, 12], [95, 9], [92, 18],
                       [82, 30], [76, 38]], np.int32)
    cv2.fillPoly(im, [wing_l, wing_r], 255)
    cv2.circle(im, (92, 35), 4, 255, -1)
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.7))


def _draw_drop(path):
    """A water drop: a small bright bead with a pale tail above it (read as a falling glint)."""
    import cv2
    im = np.zeros((64, 32), np.uint8)
    cv2.ellipse(im, (16, 46), (8, 9), 0, 0, 360, 255, -1)
    cv2.fillPoly(im, [np.array([[10, 44], [16, 10], [22, 44]], np.int32)], 150)
    _png(path, cv2.GaussianBlur(im, (0, 0), 1.5))


SPRITES = {"flake": _draw_flake, "star": _draw_star, "raven": _draw_raven,
           "drop": _draw_drop}


def _sprite_mat(X: TA.K, name: str, colour=(1.0, 1.0, 1.0), blend: float = 1.0, mx: float = 0.5, hdr: float = 1.0,
                mask: bool = True):
    """A material over a generated sprite: blend 1 = alpha-blended (snow, ravens), 0 = additive (aurora, glints).
    mask False leaves _Mask white, so the sprite is not squared (texture x mask) -- thin glints keep their spikes."""
    pth = S.STAGE / X.key / f"amb_bw_{name}.png"
    SPRITES[name](pth)
    asset = f"{S.ASSET_ROOT}/{X.key}/amb_bw_{name}.png"
    tx = [X.M.tex("_Texture", asset, clamp=True)] + ([X.M.tex("_Mask", asset, clamp=True)] if mask else [])
    return X.M.material("Homm3ConfluxVfxUber", tx,
                        {"_Min": 0.02, "_Max": mx, "_Lerp": 1.0, "_Multiply": 1.0, "_Blend": blend, "_xSpeed01": 0,
                         "_ySpeed01": 0, "_xSpeed02": 0, "_ySpeed02": 0, "_UseTwo": 0.0, "_CameraOffset": 0.0,
                         "_UseCamOffset": 0.0}, {"_Color": [c * hdr for c in colour] + [1.0]})


def _wind(X: TA.K, default=-6.0):
    """The east wind, px/s along screen x (negative = to the left)."""
    return X.px("wind", default)


# ------------------------------------------------------------------------------------------------ weather
def k_snowfall(X: TA.K, nm):
    """Snow falling through a slab of air: w, h (px of the slab; it stands on its anchor and reaches h px up), deep
    (px of depth), flake (px), fall (px/s), wind (px/s, - = left), count (alive), alpha, flutter (noise, px)."""
    w, h, deep = X.px("w", 600), X.px("h", 300), X.px("deep", 120)
    fl = X.px("flake", 5)
    fall = X.px("fall", 22)
    wind = _wind(X, -7)
    life = h / max(fall, 1e-6) * 1.15
    n = int(X.e.get("count", 120))
    return [X.group(nm, [SF.psys("snowfall", _sprite_mat(X, "flake", mx=0.55), lifetime=[life * 0.85, life * 1.1],
                                 speed=[0], velX=[wind * 1.3, wind * 0.6], velY=[-fall * 1.2, -fall * 0.8],
                                 velZ=[-fall * 0.1, fall * 0.1], size=[fl * 0.6, fl * 1.25],
                                 rate=round(n / life, 3), maxParticles=int(n * 1.6), shape="box",
                                 shapeScale=[w, h * 0.15, deep], shapePos=[-wind * life * 0.4, h * 0.95, 0],
                                 color=X.col([0.94, 0.96, 1.0]) + [X.op(float(X.e.get("alpha", 0.8)))],
                                 alphaKeys=TA.sqk([0, 0, 0.06, 1, 0.85, 1, 1, 0]),
                                 noise=X.px("flutter", 6), noiseFreq=0.7, noiseScroll=0.3, customUV=False)])]


def k_aurora(X: TA.K, nm):
    """Aurora rays over the peaks: a row of faint vertical pillars (soft dots stretched along a slow upward drift),
    each brightening and dying on its own, green low and teal to violet as it fades, the row drifting sideways so
    the curtain seems to ripple. w (px span of the row), up (px above the anchor the rays stand), ray (px width),
    tall (ray height in widths), drift (px/s along the row), climb (px/s the rays rise), count (alive), life (s), intensity (0..1, on-screen)."""
    w = X.px("w", 500)
    ray = X.px("ray", 14)
    tall = float(X.e.get("tall", 9))
    up = X.px("up", 120)
    life = float(X.e.get("life", 7))
    n = int(X.e.get("count", 24))
    a = float(X.e.get("intensity", 0.18))
    vx = X.px("drift", 1)
    vy = X.px("climb", 8)
    mat = _sprite_mat(X, "flake", colour=(1, 1, 1), blend=0.0, mx=0.6, hdr=2.0)
    return [X.group(nm, [SF.psys("aurora", mat, lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 velX=[vx * 0.8, vx * 1.2], velY=[vy * 0.9, vy * 1.1], velZ=[0, 0],
                                 size=[ray * 0.7, ray * 1.3], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, ray * 2, w * 0.04], shapePos=[0, up, 0],
                                 color=[1, 1, 1, math.sqrt(a)],
                                 colorKeys=[0, 0.3, 1.0, 0.55, 0.5, 0.25, 0.95, 0.8, 1, 0.6, 0.45, 1.0],
                                 alphaKeys=TA.sqk([0, 0, 0.3, 0.9, 0.5, 0.55, 0.7, 1, 1, 0]),
                                 sizeKeys=[0, 0.8, 0.5, 1.1, 1, 0.9], renderMode=1, lengthScale=tall,
                                 velocityScale=0.0, customUV=False)])]


def k_ground_snake(X: TA.K, nm):
    """Snow snaking over open ground on the wind: thin low streamers stretched along their speed, racing left.
    w, h (px of the field box; h is how high they lift), speed (px/s), width (px of a streamer), count (alive),
    life (s), alpha."""
    w, h = X.px("w", 300), X.px("h", 6)
    v = X.px("speed", 70)
    life = float(X.e.get("life", 1.6))
    n = int(X.e.get("count", 10))
    wd = X.px("width", 6)
    return [X.group(nm, [SF.psys("ground_snake", X.A["spray"], lifetime=[life * 0.6, life * 1.2], speed=[0],
                                 velX=[-v * 1.25, -v * 0.75], velY=[-X.m * 0.4, X.m * 1.2], velZ=[-v * 0.08, v * 0.08],
                                 size=[wd * 0.7, wd * 1.3], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w * 0.4], shapePos=[0, h * 0.5, 0],
                                 color=X.col([0.93, 0.96, 1.0]) + [X.op(float(X.e.get("alpha", 0.45)))],
                                 alphaKeys=TA.sqk([0, 0, 0.2, 1, 0.65, 0.7, 1, 0]), sizeKeys=[0, 0.6, 0.5, 1, 1, 1.4],
                                 renderMode=1, lengthScale=2.5, velocityScale=0.12,
                                 noise=h * 0.8, noiseFreq=1.1, noiseScroll=0.6)])]


def k_diamond_dust(X: TA.K, nm):
    """Diamond dust: ice crystals hanging in the frozen air, sinking very slowly and flashing as they turn to the
    moon. w, h (px box), spark (px), count (alive), life (s), colour, intensity (0..1)."""
    w, h = X.px("w", 200), X.px("h", 80)
    sp = X.px("spark", 5)
    n = int(X.e.get("count", 14))
    life = float(X.e.get("life", 5))
    mat = _sprite_mat(X, "star", colour=X.col([0.8, 0.92, 1.0]), blend=0.0, mx=0.6, hdr=2.5, mask=False)
    return [X.group(nm, [SF.psys("diamond_dust", mat, lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 velX=[-X.m * 1.5, -X.m * 0.3], velY=[-X.m * 1.0, -X.m * 0.2], velZ=[-X.m * 0.3, X.m * 0.3],
                                 size=[sp * 0.6, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w * 0.3], shapePos=[0, h * 0.5, 0],
                                 rotation=[0, 90], rotSpeed=[-20, 20],
                                 color=[1, 1, 1, math.sqrt(float(X.e.get("intensity", 0.8)))],
                                 alphaKeys=TA.sqk([0, 0, 0.2, 0.05, 0.3, 1, 0.4, 0.05, 0.62, 0.0, 0.72, 0.9, 0.82, 0.05, 1, 0]),
                                 customUV=False)])]


# ------------------------------------------------------------------------------------------------ ice
def k_ice_star(X: TA.K, nm):
    """Ice catching the moon: four-point stars flaring and dying on a surface (shards, spires, icicles), each a slow
    swell, a sharp peak and a quarter turn. w, h (px box), star (px), rate (/s), life (s), colour, intensity."""
    w, h = X.px("w", 40), X.px("h", 40)
    st = X.px("star", 10)
    life = float(X.e.get("life", 1.1))
    rate = float(X.e.get("rate", 1.2))
    mat = _sprite_mat(X, "star", colour=X.col([0.75, 0.9, 1.0]), blend=0.0, mx=0.55, hdr=3.0, mask=False)
    return [X.group(nm, [SF.psys("ice_star", mat, lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 size=[st * 0.6, st * 1.2], rate=rate, maxParticles=max(4, int(rate * life * 3)),
                                 shape="box", shapeScale=[w, h, min(w, h) * 0.2], rotation=[-12, 12],
                                 rotSpeed=[25, 50], color=[1, 1, 1, math.sqrt(float(X.e.get("intensity", 0.9)))],
                                 alphaKeys=[0, 0, 0.35, 0.5, 0.5, 1, 0.65, 0.4, 1, 0],
                                 sizeKeys=[0, 0.1, 0.4, 0.55, 0.5, 1, 0.7, 0.45, 1, 0], customUV=False)])]


def k_rime_swirl(X: TA.K, nm):
    """Rime crystals spiralling up a spire: pale specks wind round it, climb and whiten into frost, then vanish at
    the top. radius (px of the spire), rise (px over a life), period (s per turn), count (alive), life (s), spark
    (px), colour, intensity."""
    r = X.px("radius", 18)
    life = float(X.e.get("life", 6))
    vy = X.px("rise", 120) / life
    om = 2 * math.pi / float(X.e.get("period", 4))
    n = int(X.e.get("count", 12))
    sp = X.px("spark", 5)
    mat = _sprite_mat(X, "star", colour=X.col([0.65, 0.85, 1.0]), blend=0.0, mx=0.6, hdr=2.2, mask=False)
    return [X.group(nm, [SF.psys("rime_swirl", mat, lifetime=[life * 0.85, life * 1.15], speed=[0],
                                 velX=[0, 0], velY=[vy * 0.8, vy * 1.2], velZ=[0, 0],
                                 orbitalX=[0, 0], orbitalY=[-om * 1.15, -om * 0.85], orbitalZ=[0, 0], radial=[0, 0],
                                 size=[sp * 0.6, sp * 1.1], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="circle", radius=r, radiusThickness=0.1, shapeRot=[90, 0, 0],
                                 rotation=[0, 90], rotSpeed=[40, 80],
                                 color=[1, 1, 1, math.sqrt(float(X.e.get("intensity", 0.7)))],
                                 colorKeys=[0, 0.55, 0.8, 1.0, 0.6, 0.8, 0.92, 1.0, 1, 1.0, 1.0, 1.0],
                                 alphaKeys=TA.sqk([0, 0, 0.15, 0.8, 0.5, 0.45, 0.6, 1, 0.75, 0.3, 1, 0]),
                                 sizeKeys=[0, 0.5, 0.6, 1, 1, 0.3], customUV=False)])]


def k_icicle_drip(X: TA.K, nm):
    """Meltwater off icicles under a warm eave: a bead swells at the tip, lets go and falls as a streak catching the
    light. w (px of the eave), fall (px the drop falls before it is lost), rate (/s), drop (px), colour."""
    w = X.px("w", 40)
    fall = X.px("fall", 26)
    life = float(X.e.get("life", 0.7))
    rate = float(X.e.get("rate", 0.8))
    dp = X.px("drop", 4)
    mat = _sprite_mat(X, "drop", colour=X.col([0.8, 0.92, 1.0]), blend=0.0, mx=0.5, hdr=2.0, mask=False)
    v = fall / life
    bead = [SF.psys("icicle_bead", mat, lifetime=[1.6, 2.4], speed=[0], size=[dp * 0.5, dp * 0.8],
                    rate=rate, maxParticles=max(3, int(rate * 6)), shape="box", shapeScale=[w, X.m * 0.5, X.m * 0.5],
                    color=[1, 1, 1, 0.75], alphaKeys=[0, 0, 0.4, 0.5, 0.9, 1, 1, 0], sizeKeys=[0, 0.2, 0.9, 1, 1, 1],
                    customUV=False)]
    drop = [SF.psys("icicle_drop", mat, lifetime=[life * 0.8, life * 1.2], speed=[0], velX=[0, 0],
                    velY=[-v * 1.15, -v * 0.85], velZ=[0, 0], size=[dp * 0.6, dp * 0.9], rate=rate,
                    maxParticles=max(3, int(rate * life * 3)), shape="box", shapeScale=[w, X.m * 0.5, X.m * 0.5],
                    color=[1, 1, 1, 0.9], alphaKeys=[0, 1, 0.7, 0.8, 1, 0], renderMode=1, lengthScale=1.0,
                    velocityScale=0.08, customUV=False)]
    return [X.group(nm, bead + drop)]


# ------------------------------------------------------------------------------------------------ hearths
def k_hearth_smoke(X: TA.K, nm):
    """Peat smoke from a smoke hole or chimney, leaning on the east wind: a narrow column that leans more as it
    climbs and thins to blue-grey. width (px at the flue), rise (px), lean (px/s across, - = left), period (s, a
    puff's climb), colour (fresh smoke), density, alpha."""
    w, h = X.px("width", 8), X.px("rise", 80)
    per = float(X.e.get("period", 4.0))
    v = h / per
    lean = X.px("lean", -9)
    dens = float(X.e.get("density", 1.0))
    a = float(X.e.get("alpha", 0.5))
    c = X.col([0.42, 0.42, 0.44])
    return [X.group(nm, [SF.psys("hearth_smoke", X.A["puff"], lifetime=[per * 0.85, per * 1.2], speed=[0],
                                 velX=[lean * 1.3, lean * 0.6], velY=[v * 0.8, v * 1.1], velZ=[-v * 0.05, v * 0.05],
                                 size=[w * 4.0, w * 5.5], rate=round((7.0 / per + 2.0) * dens, 2), maxParticles=70,
                                 shape="sphere", radius=w * 0.15, color=[1, 1, 1, 1.0],
                                 colorKeys=[0] + c + [0.5, 0.5 * c[0] + 0.28, 0.5 * c[1] + 0.3, 0.5 * c[2] + 0.34]
                                 + [1, 0.66, 0.7, 0.78],
                                 alphaKeys=TA.sqk([0, 0, 0.1, a, 0.5, a * 0.65, 1, 0]), sizeKeys=[0, 0.35, 0.5, 1.2, 1, 2.6],
                                 rotation=[0, 360], rotSpeed=[-20, 20], noise=w * 0.5, noiseFreq=0.45,
                                 customUV=False)])]


def k_breath_steam(X: TA.K, nm):
    """Warm breath steaming out of a dwelling into the cold, in slow beats: one puff per period swells out of the
    opening, rises and is gone well before the next. dir [dx, dy] (screen, y down; the way the puff leaves), reach
    (px it travels), puff (px), period (s per breath), alpha, colour."""
    per = float(X.e.get("period", 4.5))
    dx, dy = X.e.get("dir", [0.3, -1])
    nd = math.hypot(dx, dy) or 1
    reach = X.px("reach", 22)
    sz = X.px("puff", 26)
    v = reach / (per * 0.45)
    a = float(X.e.get("alpha", 0.45))
    return [X.group(nm, [SF.psys("breath_steam", X.A["puff"], lifetime=[per * 0.97, per * 0.97], speed=[0],
                                 velX=[v * dx / nd * 0.9, v * dx / nd * 1.1], velY=[-v * dy / nd * 0.9, -v * dy / nd * 1.1],
                                 velZ=[0, 0], size=[sz * 0.9, sz * 1.1], rate=round(1.0 / per, 4), maxParticles=1,
                                 shape="sphere", radius=X.m * 0.5, color=X.col([0.92, 0.95, 1.0]) + [1.0],
                                 alphaKeys=TA.sqk([0, 0, 0.08, a, 0.3, a * 0.7, 0.6, 0, 1, 0]),
                                 sizeKeys=[0, 0.3, 0.15, 0.85, 0.6, 1.7, 1, 1.7], rotation=[0, 360], rotSpeed=[-30, 30],
                                 customUV=False)])]


def k_hearth_pool(X: TA.K, nm):
    """Firelight pooled on the snow in front of a fire: a flat warm ellipse lying on the ground that breathes with
    the fire behind it. size (px width), flat (height / width), colour, intensity (0..1, on-screen), period (s)."""
    s = X.px("size", 80)
    flat = float(X.e.get("flat", 0.3))
    per = float(X.e.get("period", 1.8))
    a = math.sqrt(float(X.e.get("intensity", 0.3)))
    return [X.group(nm, [SF.psys("hearth_pool", X.A["glow"], lifetime=[per * 0.8, per * 1.2], speed=[0],
                                 size=[s * 0.92, s * 1.05], sizeY=[s * flat * 0.92, s * flat * 1.05],
                                 rate=round(3.0 / per, 3), maxParticles=6, shape="sphere", radius=s * 0.02,
                                 color=X.col([1.0, 0.55, 0.22]) + [a],
                                 alphaKeys=[0, 0, 0.3, 0.85, 0.55, 1, 0.75, 0.8, 1, 0], customUV=False)])]


def k_pyre_cinders(X: TA.K, nm):
    """Cinders whirled up off a great fire, and the grey ash that comes back down: sparks spiral up hot and go out,
    flakes of ash drift down and away on the wind. width (px of the fire), rise (px), rate (/s sparks), ash (/s),
    colour (spark)."""
    w, h = X.px("width", 40), X.px("rise", 140)
    life = float(X.e.get("life", 2.2))
    v = h / life
    om = 2 * math.pi / 2.5
    sp = X.px("spark", 3.5)
    ash_life = float(X.e.get("ashLife", 6))
    wind = _wind(X, -6)
    sparks = SF.psys("cinders", X.A["glint"], lifetime=[life * 0.5, life * 1.1], speed=[0],
                     velX=[-v * 0.1, v * 0.1], velY=[v * 0.6, v * 1.2], velZ=[-v * 0.1, v * 0.1],
                     orbitalX=[0, 0], orbitalY=[om * 0.6, om * 1.4], orbitalZ=[0, 0], radial=[w * 0.05, w * 0.2],
                     size=[sp * 0.6, sp * 1.2], rate=float(X.e.get("rate", 9)), maxParticles=60, shape="circle",
                     radius=w * 0.4, radiusThickness=1.0, shapeRot=[90, 0, 0], color=[1, 1, 1, 1.0],
                     colorKeys=[0, 1.0, 0.85, 0.45, 0.4, 1.0, 0.5, 0.15, 1, 0.7, 0.18, 0.05],
                     alphaKeys=[0, 0, 0.08, 1, 0.55, 0.85, 1, 0], sizeKeys=[0, 1, 1, 0.3],
                     noise=w * 0.3, noiseFreq=1.0, customUV=False)
    ash = SF.psys("ash", _sprite_mat(X, "flake", colour=(0.3, 0.29, 0.28), mx=0.55), lifetime=[ash_life * 0.8, ash_life * 1.2],
                  speed=[0], velX=[wind * 1.4, wind * 0.6], velY=[-X.m * 6, -X.m * 2], velZ=[-X.m, X.m],
                  size=[sp * 0.9, sp * 1.5], rate=float(X.e.get("ash", 1.5)), maxParticles=40, shape="box",
                  shapeScale=[w * 1.6, w * 0.3, w * 0.5], shapePos=[0, h * 0.9, 0], color=[1, 1, 1, X.op(0.7)],
                  alphaKeys=TA.sqk([0, 0, 0.15, 1, 0.8, 0.8, 1, 0]), rotation=[0, 360], rotSpeed=[-90, 90],
                  noise=X.m * 6, noiseFreq=0.6, customUV=False)
    return [X.group(nm, [sparks, ash])]


def k_frost_smoke(X: TA.K, nm):
    """Arctic sea smoke off open water: thin pale wisps that stand up off the river, climb a little, lean on the
    wind and dissolve. w, h (px of the water box), wisp (px wide; a wisp lies about half as tall as wide), rise (px over a
    life), life (s), count (alive), alpha, colour."""
    w, h = X.px("w", 200), X.px("h", 20)
    wp = X.px("wisp", 30)
    life = float(X.e.get("life", 7))
    vy = X.px("rise", 30) / life
    wind = _wind(X, -4)
    n = int(X.e.get("count", 8))
    a = float(X.e.get("alpha", 0.2))
    return [X.group(nm, [SF.psys("frost_smoke", X.A["spray"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[wind * 1.3, wind * 0.6], velY=[vy * 0.7, vy * 1.2], velZ=[0, 0],
                                 size=[wp * 0.8, wp * 1.3], sizeY=[wp * 0.4, wp * 0.65],
                                 sizeKeys=[0, 0.6, 1, 1.6], sizeYKeys=[0, 0.5, 0.5, 1.0, 1, 1.8],
                                 rate=round(n / life, 3), maxParticles=n * 2, shape="box",
                                 shapeScale=[w, h * 0.2, h], color=X.col([0.82, 0.9, 0.96]) + [1.0],
                                 alphaKeys=TA.sqk([0, 0, 0.3, a, 0.6, a * 0.8, 1, 0]), rotation=[-8, 8],
                                 noise=wp * 0.15, noiseFreq=0.35)])]


def k_roof_slough(X: TA.K, nm):
    """Powder sifting off a snowy roof edge on the wind: now and then a little fall of snow slips off the eave,
    trails down and blows away. w (px of the eave), fall (px), rate (/s), puff (px), alpha."""
    w = X.px("w", 60)
    fall = X.px("fall", 30)
    life = float(X.e.get("life", 2.4))
    v = fall / life
    wind = _wind(X, -8)
    sz = X.px("puff", 12)
    a = float(X.e.get("alpha", 0.5))
    rate = float(X.e.get("rate", 1.5))
    return [X.group(nm, [SF.psys("roof_slough", X.A["spray"], lifetime=[life * 0.7, life * 1.2], speed=[0],
                                 velX=[wind * 1.3, wind * 0.5], velY=[-v * 1.3, -v * 0.6], velZ=[-v * 0.1, v * 0.1],
                                 size=[sz * 0.7, sz * 1.3], rate=rate, maxParticles=max(8, int(rate * life * 3)),
                                 shape="box", shapeScale=[w, X.m * 2, X.m * 3],
                                 color=X.col([0.95, 0.97, 1.0]) + [X.op(a)],
                                 alphaKeys=TA.sqk([0, 0, 0.1, 1, 0.5, 0.6, 1, 0]), sizeKeys=[0, 0.4, 0.4, 1, 1, 1.9],
                                 rotation=[0, 360], rotSpeed=[-40, 40], noise=sz * 0.3, noiseFreq=0.8)])]


# ------------------------------------------------------------------------------------------------ creatures
def k_ravens(X: TA.K, nm):
    """Ravens wheeling round a tower: black birds that flap (the wing curve beats) and wheel on a loop, a few at a
    time, fading in and out at the edge of sight. radius (px of the loop), count (alive), period (s per loop),
    span (px wingspan), life (s), colour (near black, blue sheen)."""
    r = X.px("radius", 60)
    per = float(X.e.get("period", 9))
    n = int(X.e.get("count", 3))
    span = X.px("span", 9)
    life = float(X.e.get("life", 8))
    om = 2 * math.pi / per
    mat = _sprite_mat(X, "raven", colour=X.col([0.05, 0.05, 0.07]), blend=1.0, mx=0.5)
    flap = [0, 1, 0.12, 0.45, 0.24, 1, 0.36, 0.45, 0.5, 1, 0.72, 1, 0.86, 0.5, 1, 1]   # beats, a glide, a beat
    return [X.group(nm, [SF.psys("ravens", mat, lifetime=[life * 0.85, life * 1.15], speed=[0],
                                 velX=[0, 0], velY=[-X.m * 0.6, X.m * 0.6], velZ=[0, 0],
                                 orbitalX=[0, 0], orbitalY=[om * 0.8, om * 1.2], orbitalZ=[0, 0], radial=[0, 0],
                                 size=[span * 0.85, span * 1.1], sizeY=[span * 0.5, span * 0.6],
                                 sizeKeys=[0, 1, 1, 1], sizeYKeys=flap, rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="circle", radius=r, radiusThickness=0.35, shapeRot=[90, 0, 0],
                                 color=[1, 1, 1, 1], alphaKeys=[0, 0, 0.1, 1, 0.9, 1, 1, 0],
                                 noise=X.m * 3, noiseFreq=0.3, customUV=False)])]



def k_aurora_curtain(X: TA.K, nm):
    """An auroral curtain: one ribbon mesh drawn by Homm3Town/Aurora (thin rippling green hem, sheaves of fine rays
    fading to violet, surges running along it, folds swaying in 3D) -- not particles. hem ([[x, y], ...] rest px the
    hem passes through, left to right; a Catmull-Rom spline), height (px, or one per hem point), sway (px the folds
    swing), folds (along the curtain), intensity, hemw (hem width, fraction of height), hemsoft (how softly the curtain fades in below its hem), fade (ray fade upward),
    colours hem / low / high (HDR), phase. Depth: the anchor's (px on the far peaks, out < 0 pushes it behind them),
    so the peaks occlude the hem where it hangs low."""
    import stronghold_full3d_terrain as T
    pts = np.asarray(X.e["hem"], np.float64)
    hgt = X.e.get("height", 160)
    hgt = np.full(len(pts), float(hgt)) if np.isscalar(hgt) else np.asarray(hgt, np.float64)
    # Catmull-Rom through the hem points, sampled about every 6 px of hem
    P = np.vstack([2 * pts[0] - pts[1], pts, 2 * pts[-1] - pts[-2]])
    Hh = np.concatenate([[hgt[0]], hgt, [hgt[-1]]])
    seg = []
    for i in range(1, len(P) - 2):
        n = max(4, int(np.hypot(*(P[i + 1] - P[i])) / 6))
        s = np.linspace(0, 1, n, endpoint=False)[:, None]
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        c = 0.5 * ((2 * p1) + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * s ** 3)
        hh = Hh[i] + (Hh[i + 1] - Hh[i]) * (3 * s[:, 0] ** 2 - 2 * s[:, 0] ** 3)
        seg.append(np.column_stack([c, hh]))
    seg.append(np.array([[*pts[-1], hgt[-1]]]))
    C = np.vstack(seg)
    nu = len(C)
    rows_v = 16                                        # vertical rows: the vertex sway bends the drape smoothly
    vs = np.linspace(-0.25, 1, rows_v)                 # v < 0: room below the hem for its soft fade (hemsoft)
    cam = X.sc.cam
    z = X.z
    ph = float(X.e.get("phase", 0.0))
    V, UV = [], []
    for j, v in enumerate(vs):
        xs = C[:, 0]
        ys = C[:, 1] - C[:, 2] * v
        d = T.rays(cam, xs, ys)
        d = d / (d @ cam["fwd"])[:, None]
        # a gentle depth zigzag along the curtain so it turns and overlaps itself in sweeps
        zz = z * (1 + 0.02 * np.sin(np.linspace(0, 1, nu) * 9.0 + ph))
        V.append(cam["pos"] + d * zz[:, None])
        UV.append(np.column_stack([np.linspace(0, 1, nu), np.full(nu, v)]))
    V, UV = np.vstack(V), np.vstack(UV)
    i = np.arange(nu - 1)
    tris = []
    for j in range(rows_v - 1):
        a, b = j * nu + i, (j + 1) * nu + i
        tris += [np.stack([a, a + 1, b], 1), np.stack([a + 1, b + 1, b], 1)]
    tris = np.vstack(tris)
    hem_len = float(np.sum(np.hypot(*np.diff(C[:, :2], axis=0).T)))
    uv2 = np.tile([hem_len / 10.0, ph], (len(V), 1))
    mat = X.M.material("Homm3TownAurora",
                       [X.M.tex("_Noise", X.M.vtex("TileNoise_19_vfx"), srgb=False), X.M.tex("_Noise2", X.M.vtex("TileNoise_23_vfx"), srgb=False)],
                       {"_Intensity": float(X.e.get("intensity", 0.6)), "_HemWidth": float(X.e.get("hemw", 0.05)), "_HemSoft": float(X.e.get("hemsoft", 0.015)),
                        "_RayFade": float(X.e.get("fade", 2.2)), "_Drift": float(X.e.get("drift", 0.15)),
                        "_Surge": float(X.e.get("surge", 0.05)), "_Sway": X.px("sway", 10) * X.sc.scale,
                        "_SwayFreq": float(X.e.get("folds", 2.5)), "_SwaySpeed": float(X.e.get("swayspeed", 0.25)),
                        "_TimeOffset": 0.0, "_TimeScale": 1.0},
                       {"_ColorHem": list(X.e.get("hemcol", [0.55, 1.0, 0.6])) + [1.0],
                        "_ColorLow": list(X.e.get("lowcol", [0.2, 1.0, 0.55])) + [1.0],
                        "_ColorHigh": list(X.e.get("highcol", [0.55, 0.3, 1.0])) + [1.0]})
    return [{"fxmesh": nm, "v": V, "uv": UV, "uv2": uv2, "tris": tris, "material": mat}]


KINDS = {"snowfall": k_snowfall, "aurora": k_aurora, "ground_snake": k_ground_snake, "diamond_dust": k_diamond_dust,
         "ice_star": k_ice_star, "rime_swirl": k_rime_swirl, "icicle_drip": k_icicle_drip,
         "hearth_smoke": k_hearth_smoke, "breath_steam": k_breath_steam, "hearth_pool": k_hearth_pool,
         "pyre_cinders": k_pyre_cinders, "frost_smoke": k_frost_smoke, "roof_slough": k_roof_slough,
         "ravens": k_ravens, "aurora_curtain": k_aurora_curtain}
