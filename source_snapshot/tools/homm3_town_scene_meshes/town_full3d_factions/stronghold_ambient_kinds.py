"""Stronghold's own ambient kinds (loaded by town_full3d_ambient.py stage): desert dust devils, hoof/paw dust kicked up
in the pens and yards, flies over the meat stall, vultures and wind-blown plain dust (shared birds / mist with
a fast fill).

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), velocity curves in one system all [min, max] pairs, orbital/radial
curves all [min, max] pairs.
"""
from __future__ import annotations

import math

import town_full3d_ambient as TA
import stronghold_full3d_fx as SF


def k_dust_devil(X: TA.K, nm):
    """A small whirlwind of sand wandering over the plain: radius (px at the base), rise (px, column height), period
    (s per turn), drift (px/s, +x = right), colour (sandy), alpha, count (alive), puff (px)."""
    r = X.px("radius", 10)
    h = X.px("rise", 90)
    life = float(X.e.get("life", 4.5))
    per = float(X.e.get("period", 1.6))
    vy = h / life
    vx = X.px("drift", 3)
    n = int(X.e.get("count", 18))
    sz = X.px("puff", 14)
    w = 2 * math.pi / per
    return [X.group(nm, [SF.psys("dust_devil", X.A["puff"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[vx * 0.8, vx * 1.2], velY=[vy * 0.7, vy * 1.2], velZ=[0, 0],
                                 orbitalY=[w * 0.85, w * 1.15], radial=[r * 0.05, r * 0.25],
                                 size=[sz * 0.6, sz * 1.0], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="circle", radius=r, radiusThickness=0.6, shapeRot=[90, 0, 0],
                                 color=X.col([0.72, 0.52, 0.36]) + [X.op(0.3)],
                                 alphaKeys=TA.sqk([0, 0, 0.15, 1, 0.65, 0.7, 1, 0]), sizeKeys=[0, 0.5, 1, 2.0],
                                 rotation=[0, 360], rotSpeed=[-60, 60], noise=r * 0.3, noiseFreq=0.6,
                                 customUV=False)])]


def k_dust(X: TA.K, nm):
    """Dust kicked up in a yard or pen: low puffs born over a box that billow and settle. w, h (px), rise (px over a
    life), drift (px/s), colour (sandy), alpha, rate (/s), puff (px), life (s)."""
    w, h = X.px("w", 60), X.px("h", 10)
    life = float(X.e.get("life", 2.6))
    vy = X.px("rise", 10) / life
    vx = X.px("drift", 2)
    rate = float(X.e.get("rate", 2))
    sz = X.px("puff", 12)
    return [X.group(nm, [SF.psys("dust", X.A["puff"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 velX=[-vx * 0.2, vx * 1.4], velY=[vy * 0.4, vy * 1.1], velZ=[-vx * 0.3, vx * 0.3],
                                 size=[sz * 0.6, sz * 1.2], rate=rate, maxParticles=max(6, int(rate * life * 2)),
                                 shape="box", shapeScale=[w, h * 0.3, h], color=X.col([0.7, 0.5, 0.34]) + [X.op(0.28)],
                                 alphaKeys=TA.sqk([0, 0, 0.12, 1, 0.5, 0.6, 1, 0]), sizeKeys=[0, 0.4, 1, 1.9],
                                 rotation=[0, 360], rotSpeed=[-20, 20], noise=sz * 0.3, noiseFreq=0.5,
                                 customUV=False)])]


def k_flies(X: TA.K, nm):
    """Flies buzzing over meat: dark specks darting about a point. w, h (px of the swarm box), count (alive), speck
    (px), colour, alpha."""
    w, h = X.px("w", 14), X.px("h", 10)
    n = int(X.e.get("count", 6))
    life = float(X.e.get("life", 2.5))
    sp = X.px("speck", 1.4)
    return [X.group(nm, [SF.psys("flies", X.A["puff"], lifetime=[life * 0.7, life * 1.3], speed=[0],
                                 size=[sp * 0.8, sp * 1.2], rate=round(n / life, 3), maxParticles=n * 2,
                                 shape="box", shapeScale=[w, h, w * 0.5],
                                 color=X.col([0.06, 0.05, 0.04]) + [X.op(0.85)],
                                 alphaKeys=TA.sqk([0, 0, 0.1, 1, 0.9, 1, 1, 0]),
                                 noise=w * 0.9, noiseFreq=2.5, noiseScroll=1.5, customUV=False)])]


def _fill_fast(groups, n: int, fill_s: float):
    """Long-lived systems (a 29 s soar, a 14 s wisp) are nearly empty after the ~5-6 s prewarm the game and the editor
    renders give them; emit the whole flock within fill_s and cap it at n so the town opens populated."""
    s = groups[0]["systems"][0]
    s["rate"] = round(n / fill_s, 3)
    s["maxParticles"] = n
    return groups


def k_vultures(X: TA.K, nm):
    """Vultures circling: the shared birds kind (same knobs), the flock present from the first second."""
    return _fill_fast(TA.k_birds(X, nm), int(X.e.get("count", 3)), 3.0)


def k_dust_drift(X: TA.K, nm):
    """Wind-blown dust low over the plain: the shared mist kind (same knobs), filled within a few seconds."""
    return _fill_fast(TA.k_mist(X, nm), int(X.e.get("count", 6)), float(X.e.get("life", 14)) * 0.35)


KINDS = {"dust_devil": k_dust_devil, "dust": k_dust, "flies": k_flies, "vultures": k_vultures,
         "dust_drift": k_dust_drift}
