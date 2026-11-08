"""Cove's own ambient kinds (loaded by town_full3d_ambient.py stage): a pirate harbour at sunset. Gulls gliding
across the bay, surf foam washing round the rocks, sea spray thrown up off the cliffs and reefs, ship's lanterns
swinging on their hooks, the lighthouse beacon sweeping its beam, smugglers' signal lamps blinking a code, sun glitter
dancing on the bay, light catching the ripples of a flag in the wind, the Ayssid orb's tide droplets circling it,
water caustics shimmering in the sea-mage windows and parrots flitting between the palms.

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), every velocity curve in one system and every orbital/radial curve in
one system in the same shape. Gradient keys stay at 8 or fewer per curve (Unity's limit). Sprites (gull, beam) are
generated next to the prefab like the shared bird silhouette. Phase tricks: systems with the same rate and lifetime
emit at the same instants, so two systems whose alpha windows differ run in lock-step (lantern swing, beacon sweep).
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


def _draw_gull(path):
    """A gliding gull seen from the front: a small body and long narrow wings bent at the wrist, the outer wing
    drooping (the gull 'M'), white on black, 128 x 48."""
    import cv2
    im = np.zeros((48, 128), np.uint8)
    pts = [(6, 30), (20, 20), (38, 15), (52, 20), (64, 26), (76, 20), (90, 15), (108, 20), (122, 30)]
    for a, b in zip(pts, pts[1:]):
        w = 5 if min(abs(a[0] - 64), abs(b[0] - 64)) < 30 else 3
        cv2.line(im, a, b, 255, w, cv2.LINE_AA)
    cv2.ellipse(im, (64, 27), (5, 4), 0, 0, 360, 255, -1)
    _png(path, cv2.GaussianBlur(im, (0, 0), 0.7))


def _draw_beam(path):
    """A light beam lying along +x: narrow and bright at the left (the lamp), widening and fading out to the right,
    soft on its long edges, 256 x 64."""
    x = np.linspace(0, 1, 256)[None, :]
    y = np.linspace(-1, 1, 64)[:, None]
    half = 0.3 + 0.65 * x                                  # beam half-height (share of the quad) along its length
    edge = np.clip(1 - np.abs(y) / half, 0, 1) ** 0.8
    fall = (1 - x) ** 1.1 * np.clip(x / 0.03, 0, 1)
    im = (255 * np.clip(edge * fall, 0, 1)).astype(np.uint8)
    _png(path, im)


SPRITES = {"gull": _draw_gull, "beam": _draw_beam}


def _sprite_mat(X: TA.K, name: str, colour, blend: float = 1.0, mn: float = 0.05, mx: float = 0.5):
    pth = S.STAGE / X.key / f"amb_cv_{name}.png"
    SPRITES[name](pth)
    asset = f"{S.ASSET_ROOT}/{X.key}/amb_cv_{name}.png"
    return X.M.material("Homm3ConfluxVfxUber", [X.M.tex("_Texture", asset, clamp=True),
                                               X.M.tex("_Mask", asset, clamp=True)],
                        {"_Min": mn, "_Max": mx, "_Lerp": 1.0, "_Multiply": 1.0, "_Blend": blend, "_xSpeed01": 0,
                         "_ySpeed01": 0, "_xSpeed02": 0, "_ySpeed02": 0, "_UseTwo": 0.0, "_CameraOffset": 0.0,
                         "_UseCamOffset": 0.0}, {"_Color": list(colour) + [1.0]})


def _quat_xz(ax_deg: float, az_deg: float) -> list[float]:
    """Unit quaternion (x, y, z, w) for a tilt about x then z (a system's local frame)."""
    ax, az = math.radians(ax_deg) / 2, math.radians(az_deg) / 2
    qx = np.array([math.sin(ax), 0, 0, math.cos(ax)])
    qz = np.array([0, 0, math.sin(az), math.cos(az)])
    x1, y1, z1, w1 = qz
    x2, y2, z2, w2 = qx
    return [float(w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2), float(w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2),
            float(w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2), float(w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)]


# ------------------------------------------------------------------------------------------------ birds
def k_gulls(X: TA.K, nm):
    """Gulls gliding across the bay on held wings, drifting in long straight lines and lifting on the air, now and
    then giving two quick flaps. w, h (px of the box they enter from), reach (px a gull travels over its life),
    dir (+1 = to the right, -1 = left), count (alive), span (px wingspan), life (s), colour (sunlit white), alpha,
    lift (px the entry box sits above the anchor: the anchor is on the sea or a roof, the gulls fly above it)."""
    w, h = X.px("w", 60), X.px("h", 40)
    life = float(X.e.get("life", 14))
    v = X.px("reach", 300) / life * float(X.e.get("dir", 1))
    n = int(X.e.get("count", 3))
    span = X.px("span", 12)
    mat = _sprite_mat(X, "gull", X.col([0.95, 0.9, 0.84]), blend=1.0)
    lo, hi = sorted((v * 0.75, v * 1.2))
    # glide (wings held), then two flaps (the wings fold to a quarter height and back), glide again
    flap = [0, 1, 0.42, 1, 0.45, 0.25, 0.48, 1, 0.51, 0.25, 0.54, 1, 1, 1]
    return [X.group(nm, [SF.psys("gulls", mat, lifetime=[life * 0.85, life * 1.15], speed=[0],
                                 velX=[lo, hi], velY=[-X.m * 0.6, X.m * 1.2], velZ=[-X.m * 0.5, X.m * 0.5],
                                 size=[span * 0.8, span * 1.1], sizeY=[span * 0.38, span * 0.42],
                                 sizeKeys=[0, 1, 1, 1], sizeYKeys=flap, rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w * 0.3], shapePos=[0, X.px("lift", 0), 0],
                                 color=[1, 1, 1, X.op(float(X.e.get("alpha", 0.95)))],
                                 alphaKeys=TA.sqk([0, 0, 0.1, 1, 0.88, 1, 1, 0]),
                                 noise=X.m * 6, noiseFreq=0.12, customUV=False)])]


def k_parrots(X: TA.K, nm):
    """Parrots flitting between the palms: small bright birds (scarlet to emerald, each its own colour) dashing in
    short hops with rapid wingbeats. w, h (px of the canopy box), count (alive), span (px), life (s), colour,
    colour2 (the other end of the plumage range), dart (noise strength, px/s)."""
    w, h = X.px("w", 60), X.px("h", 30)
    n = int(X.e.get("count", 2))
    life = float(X.e.get("life", 5))
    span = X.px("span", 6)
    mat = _sprite_mat(X, "gull", [1.0, 1.0, 1.0], blend=1.0)
    beat = [0, 1, 0.12, 0.3, 0.25, 1, 0.37, 0.3, 0.5, 1, 0.62, 0.3, 0.75, 1, 1, 0.3]
    c1 = X.col([0.85, 0.12, 0.08])
    c2 = [float(x) for x in X.e.get("colour2", [0.12, 0.7, 0.2])]
    return [X.group(nm, [SF.psys("parrots", mat, lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 size=[span * 0.85, span * 1.1], sizeY=[span * 0.45, span * 0.5],
                                 sizeKeys=[0, 1, 1, 1], sizeYKeys=beat, rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w * 0.3], color=c1 + [1.0], color2=c2 + [1.0],
                                 alphaKeys=[0, 0, 0.1, 1, 0.9, 1, 1, 0],
                                 noise=X.px("dart", 30), noiseFreq=0.5, noiseScroll=0.4, customUV=False)])]


# ------------------------------------------------------------------------------------------------ sea
def k_wave_foam(X: TA.K, nm):
    """Surf washing round a rock or a shore: flat lacy foam sheets swell along the waterline as a swell breaks,
    slide a little up the shore and sink away, at staggered places along it. w, h (px of the waterline box),
    sheet (px width of one wash), flat (sheet height / width), period (s per wash), count (washes alive),
    wash (px a sheet slides, +x = right), colour, alpha."""
    w, h = X.px("w", 60), X.px("h", 6)
    sh = X.px("sheet", 40)
    flat = float(X.e.get("flat", 0.3))
    per = float(X.e.get("period", 4.5))
    n = int(X.e.get("count", 3))
    vx = X.px("wash", 4) / per
    a = float(X.e.get("alpha", 0.55))
    # the swell: a quick bloom of foam, a short hold, a long fade as it drains off
    return [X.group(nm, [SF.psys("wave_foam", X.A["spray"], lifetime=[per * 0.9, per * 1.1], speed=[0],
                                 velX=[vx * 0.5, vx * 1.5], velY=[X.m * 0.1, X.m * 0.4], velZ=[0, 0],
                                 size=[sh * 0.7, sh * 1.2], sizeY=[sh * 0.7 * flat, sh * 1.2 * flat],
                                 rate=round(n / per, 3), maxParticles=n * 3, shape="box", shapeScale=[w, h, h],
                                 color=X.col([0.97, 0.94, 0.88]) + [1.0],
                                 alphaKeys=TA.sqk([0, 0, 0.12, a, 0.3, a * 0.85, 0.65, a * 0.35, 1, 0]),
                                 sizeKeys=[0, 0.45, 0.15, 0.95, 0.6, 1.1, 1, 1.25], rotation=[-12, 12],
                                 customUV=False)])]


def k_sea_spray(X: TA.K, nm):
    """Spray thrown up where a swell hits a cliff foot or a reef: misty plumes shoot up, hang and drift down, with
    bright droplets flung out on real arcs (gravity in the prefab frame). width (px of the strike), height (px the
    droplets climb), rate (strikes /s), life (s), lean (deg the throw leans, + = right), colour, alpha, drops
    (droplet intensity 0..1)."""
    w = X.px("width", 20)
    life = float(X.e.get("life", 2.2))
    hgt = X.px("height", 40)
    t_up = life * 0.42                          # droplets peak a little before mid-life
    g = 2 * hgt / t_up ** 2                     # painting m/s^2
    v0 = g * t_up
    gmod = g * X.sc.scale / 9.81                # gravityModifier: the prefab frame is scaled by sc.scale
    lean = float(X.e.get("lean", 0))
    rate = float(X.e.get("rate", 0.8))
    a = float(X.e.get("alpha", 0.45))
    sz = X.px("puff", max(float(X.e.get("width", 20)) * 1.8, 30))
    rot = [-90.0, 0.0, -lean]
    c = X.col([0.96, 0.95, 0.92])
    plume = SF.psys("sea_spray", X.A["spray"], lifetime=[life * 0.9, life * 1.3], speed=[v0 * 0.45, v0 * 0.7],
                    size=[sz * 0.5, sz * 0.9], rate=rate, maxParticles=max(6, int(rate * life * 3)), shape="cone",
                    angle=14, radius=w * 0.5, shapeRot=rot, gravity=gmod * 0.3, color=c + [1.0],
                    alphaKeys=TA.sqk([0, 0, 0.08, a, 0.45, a * 0.7, 1, 0]), sizeKeys=[0, 0.35, 0.4, 1.1, 1, 1.7],
                    rotation=[0, 360], rotSpeed=[-20, 20], customUV=False)
    drops = SF.psys("sea_spray_drops", X.A["glint"], lifetime=[life * 0.8, life * 1.0], speed=[v0 * 0.75, v0 * 1.1],
                    size=[X.m * 2.0, X.m * 3.4], rate=rate * 7, maxParticles=max(10, int(rate * 7 * life * 2)),
                    shape="cone", angle=24, radius=w * 0.5, shapeRot=rot, gravity=gmod,
                    color=c + [float(X.e.get("drops", 0.5))], alphaKeys=[0, 0, 0.08, 1, 0.7, 0.7, 1, 0],
                    customUV=False)
    return [X.group(nm, [plume, drops])]


def k_sun_glitter(X: TA.K, nm):
    """Sunset glitter on the water: short flat dashes of light winking on and off over the bay (each a ripple
    crest catching the low sun). w, h (px of the water box), dash (px), flat (height / width), rate (/s), life (s),
    colour, intensity (0..1)."""
    w, h = X.px("w", 200), X.px("h", 20)
    d = X.px("dash", 7)
    flat = float(X.e.get("flat", 0.22))
    life = float(X.e.get("life", 0.9))
    rate = float(X.e.get("rate", 10))
    return [X.group(nm, [SF.psys("sun_glitter", X.A["glint"], lifetime=[life * 0.6, life * 1.3], speed=[0],
                                 velX=[-X.m * 2, X.m * 2], velY=[0, 0], velZ=[0, 0],
                                 size=[d * 0.6, d * 1.2], sizeY=[d * 0.6 * flat, d * 1.2 * flat], rate=rate,
                                 maxParticles=max(8, int(rate * life * 3)), shape="box",
                                 shapeScale=[w, h * 0.2, h],
                                 color=X.col([1.0, 0.72, 0.4]) + [float(X.e.get("intensity", 0.7))],
                                 alphaKeys=[0, 0, 0.25, 1, 0.45, 0.4, 0.6, 0.9, 1, 0],
                                 sizeKeys=[0, 0.3, 0.3, 1, 1, 0.6], customUV=False)])]


def k_tide_orb(X: TA.K, nm):
    """The Ayssid orb's tide: water droplets circling the sphere on a tilted ring like a tiny moon's tide, and the
    orb's own sea-blue light swelling and ebbing. radius (px of the ring), tilt (deg), period (s per orbit),
    count (droplets alive), spark (px), colour, glow (px of the swell; 0 = none), intensity (0..1)."""
    r = X.px("radius", 40)
    per = float(X.e.get("period", 7))
    n = int(X.e.get("count", 10))
    life = per * 1.2
    sp = X.px("spark", 3.5)
    om = 2 * math.pi / per
    tilt = float(X.e.get("tilt", 22))
    c = X.col([0.6, 0.88, 1.0])
    ring = SF.psys("tide_orb", X.A["glint"], lifetime=[life * 0.85, life * 1.15], speed=[0],
                   size=[sp * 0.6, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2, shape="circle",
                   radius=r, radiusThickness=0.08, shapeRot=[90, 0, 0], orbitalX=[0, 0],
                   orbitalY=[om * 0.9, om * 1.1], orbitalZ=[0, 0], color=c + [float(X.e.get("intensity", 0.8))],
                   alphaKeys=[0, 0, 0.12, 1, 0.5, 0.55, 0.8, 1, 1, 0], rot=_quat_xz(tilt, 12), customUV=False)
    sys = [ring]
    g = float(X.e.get("glow", 60))
    if g > 0:
        gs = X.px("glow", 60)
        sys.append(SF.psys("tide_swell", X.A["glow"], lifetime=[5.6, 5.6], speed=[0], size=[gs, gs],
                           rate=round(1 / 5.6, 4), maxParticles=1, radius=gs * 0.01, color=c + [0.5],
                           alphaKeys=[0, 0.15, 0.45, 1, 1, 0.15], sizeKeys=[0, 0.85, 0.45, 1.05, 1, 0.85],
                           customUV=False))
    return [X.group(nm, sys)]


# ------------------------------------------------------------------------------------------------ lights
def k_lantern_swing(X: TA.K, nm):
    """A ship's lantern swinging on its hook in the sea wind: a warm light travelling to and fro along a short
    pendulum arc under the hook (px = the hook). drop (px, hook to lantern), amp (deg each side), period (s per
    full swing), size (px of the light), colour, intensity (0..1), spin (+1 / -1: the orbital sense)."""
    r = X.px("drop", 10)
    amp = float(X.e.get("amp", 22))
    per = float(X.e.get("period", 3.2))
    s = X.px("size", 12)
    a = float(X.e.get("intensity", 0.5))
    sg = float(X.e.get("spin", 1))
    om = math.radians(2 * amp) / (per / 2)      # one side to the other in half a period
    col = X.col([1.0, 0.7, 0.32]) + [a]

    def leg(name, start_deg, w, keys, mat="glow", k=1.0):
        return SF.psys(name, X.A[mat], lifetime=[per, per], speed=[0], size=[s * 0.95 * k, s * 1.05 * k],
                       rate=round(1 / per, 5), maxParticles=2, shape="circle", radius=r, radiusThickness=0.0,
                       arc=0.2, shapeRot=[0, 0, start_deg], orbitalX=[0, 0], orbitalY=[0, 0],
                       orbitalZ=[w * sg, w * sg], color=col if mat == "glow" else col[:3] + [min(1.0, a * 1.2)],
                       alphaKeys=keys, customUV=False)

    # leg A swings left end -> right end in the first half, leg B right -> left in the second; they cross-fade at
    # the ends (same rate and life: they spawn together, so they stay in phase)
    ka, kb = [0, 0, 0.05, 1, 0.45, 1, 0.5, 0, 1, 0], [0, 0, 0.5, 0, 0.55, 1, 0.95, 1, 1, 0]
    A = leg("lantern_swing_a", -90 - amp * sg, om, ka)
    B = leg("lantern_swing_b", -90 + 3 * amp * sg, -om, kb)
    Ac = leg("lantern_core_a", -90 - amp * sg, om, ka, "glint", 0.32)
    Bc = leg("lantern_core_b", -90 + 3 * amp * sg, -om, kb, "glint", 0.32)
    halo = SF.psys("lantern_halo", X.A["glow"], lifetime=[1.2, 1.6], speed=[0], size=[s * 2.4, s * 2.8],
                   rate=2.0, maxParticles=4, radius=s * 0.05, shapePos=[0, -r, 0],
                   color=X.col([1.0, 0.7, 0.32]) + [a * 0.25], alphaKeys=[0, 0, 0.3, 1, 0.7, 0.8, 1, 0],
                   customUV=False)
    return [X.group(nm, [A, B, Ac, Bc, halo])]


def k_beacon_sweep(X: TA.K, nm):
    """The lighthouse beacon turning: its beam swings out to the right, shortens as it points out to sea, swings
    out to the left, then flares as it faces the town. length (px of a full beam), width (px at its far end),
    period (s per turn), colour (HDR warm white), intensity (0..1), flare (px of the facing flash)."""
    L = X.px("length", 200)
    wd = X.px("width", 26)
    per = float(X.e.get("period", 9))
    a = float(X.e.get("intensity", 0.4))
    col = [float(x) for x in X.e.get("colour", [1.6, 1.35, 0.95])]
    mat = _sprite_mat(X, "beam", col, blend=0.12, mn=0.0, mx=float(X.e.get("soft", 0.3)))
    life = per * 0.999

    def beam(name, rotdeg, size_keys, alpha_keys):
        return SF.psys(name, mat, lifetime=[life, life], speed=[0], size=[L, L], sizeY=[wd, wd],
                       rotation=[rotdeg, rotdeg], rate=round(1 / per, 5), maxParticles=1, radius=X.m * 0.01,
                       pivot=[0.5, 0, 0], color=[1, 1, 1, math.sqrt(a)], alphaKeys=TA.sqk(alpha_keys),
                       sizeKeys=size_keys, sizeYKeys=[0, 1, 1, 1], customUV=False)

    flare = SF.psys("beacon_flare", X.A["glow"], lifetime=[life, life], speed=[0], size=[X.px("flare", 34)] * 2,
                    rate=round(1 / per, 5), maxParticles=1, radius=X.m * 0.01,
                    color=X.col([1.0, 0.9, 0.7]) + [min(1.0, a * 1.4)],
                    alphaKeys=[0, 1, 0.07, 0.15, 0.5, 0.05, 0.93, 0.15, 1, 1], customUV=False)
    # right beam over the first half (from facing the town round to facing out to sea), left over the second
    right = beam("beacon_right", 0.0, [0, 0.15, 0.25, 1, 0.5, 0.2, 1, 0.2], [0, 0.9, 0.25, 0.75, 0.47, 0.1, 0.5, 0, 1, 0])
    left = beam("beacon_left", 180.0, [0, 0.2, 0.5, 0.2, 0.75, 1, 1, 0.15], [0, 0, 0.5, 0, 0.53, 0.1, 0.75, 0.75, 1, 0.9])
    return [X.group(nm, [right, left, flare])]


SIGNALS = {   # alpha keys over one period: the code a lamp blinks (then dark till the period ends)
    "short_short_long": [0, 0, 0.04, 1, 0.1, 0, 0.16, 1, 0.22, 0, 0.3, 1, 0.48, 1, 0.54, 0],
    "long_short": [0, 0, 0.05, 1, 0.3, 1, 0.36, 0, 0.42, 1, 0.48, 0],
    "triple": [0, 0, 0.05, 1, 0.12, 0, 0.2, 1, 0.27, 0, 0.35, 1, 0.42, 0],
}


def k_signal_lamp(X: TA.K, nm):
    """A smugglers' signal lamp behind a shutter: it blinks its code, then stays dark for the rest of the period.
    size (px), code (short_short_long | long_short | triple), period (s), colour, intensity (0..1)."""
    s = X.px("size", 12)
    per = float(X.e.get("period", 7))
    keys = SIGNALS[X.e.get("code", "short_short_long")]
    a = float(X.e.get("intensity", 0.6))
    core = SF.psys("signal_lamp", X.A["glow"], lifetime=[per * 0.999, per * 0.999], speed=[0], size=[s, s],
                   rate=round(1 / per, 5), maxParticles=1, radius=s * 0.01,
                   color=X.col([1.0, 0.82, 0.45]) + [a], alphaKeys=keys, customUV=False)
    pt = SF.psys("signal_lamp_pt", X.A["glint"], lifetime=[per * 0.999, per * 0.999], speed=[0],
                 size=[s * 0.35, s * 0.35], rate=round(1 / per, 5), maxParticles=1, radius=s * 0.01,
                 color=X.col([1.0, 0.82, 0.45])[:3] + [min(1.0, a * 1.3)], alphaKeys=keys, customUV=False)
    return [X.group(nm, [core, pt])]


def k_caustics(X: TA.K, nm):
    """Water caustics playing on a lit window or a pool's rock: aqua-tinted light that wobbles irregularly in
    brightness and spread, as if seen through moving water. size (px), colour, intensity (0..1), count (layers)."""
    s = X.px("size", 16)
    n = int(X.e.get("count", 3))
    a = float(X.e.get("intensity", 0.35))
    return [X.group(nm, [SF.psys("caustics", X.A["glow"], lifetime=[1.1, 2.3], speed=[0], size=[s * 0.7, s * 1.2],
                                 sizeY=[s * 0.55, s * 1.0], rate=round(n / 1.7, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[s * 0.4, s * 0.4, s * 0.1],
                                 color=X.col([0.55, 0.95, 0.9]) + [a],
                                 alphaKeys=[0, 0, 0.2, 0.9, 0.35, 0.4, 0.55, 1, 0.75, 0.3, 1, 0],
                                 sizeKeys=[0, 0.8, 0.5, 1.15, 1, 0.9], sizeYKeys=[0, 1.1, 0.5, 0.8, 1, 1.05],
                                 customUV=False)])]


def k_flag_ripple(X: TA.K, nm):
    """A flag rippling in the wind: soft bands of light run from the hoist to the fly as the cloth waves, with a
    shadow band chasing each. w, h (px of the flag), dir (+1 = flies to the right), period (s per wave), colour,
    intensity (0..1)."""
    w, h = X.px("w", 26), X.px("h", 14)
    per = float(X.e.get("period", 0.8))
    d = float(X.e.get("dir", 1))
    v = w / per * d
    a = float(X.e.get("intensity", 0.4))
    off = [-w * 0.5 * d, 0, 0]
    band = SF.psys("flag_ripple", X.A["glow"], lifetime=[per, per], speed=[0], size=[w * 0.16, w * 0.16],
                   sizeY=[h * 1.1, h * 1.1], rate=round(1.6 / per, 4), maxParticles=4, shape="box",
                   shapeScale=[w * 0.05, h * 0.2, h * 0.05], shapePos=off, velX=[v * 0.9, v * 1.1], velY=[0, 0],
                   velZ=[0, 0], color=X.col([1.0, 0.85, 0.7]) + [a],
                   alphaKeys=[0, 0, 0.2, 1, 0.75, 0.7, 1, 0], sizeYKeys=[0, 0.8, 0.5, 1.1, 1, 0.7],
                   sizeKeys=[0, 1, 1, 1], customUV=False)
    return [X.group(nm, [band])]


KINDS = {"gulls": k_gulls, "parrots": k_parrots, "wave_foam": k_wave_foam, "sea_spray": k_sea_spray,
         "sun_glitter": k_sun_glitter, "tide_orb": k_tide_orb, "lantern_swing": k_lantern_swing,
         "beacon_sweep": k_beacon_sweep, "signal_lamp": k_signal_lamp, "caustics": k_caustics,
         "flag_ripple": k_flag_ripple}
