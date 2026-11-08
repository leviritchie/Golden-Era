"""Inferno's own ambient kinds (loaded by town_full3d_ambient.py stage): falling ash, lava bubbles, heat haze.

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), velocity curves in one system all [min, max] pairs.
"""
from __future__ import annotations

import town_full3d_ambient as TA
import stronghold_full3d_fx as SF


def k_ash(X: TA.K, nm):
    """Ash flakes drifting down over a box: w, h (px; the box the flakes are born in), fall (px/s), drift (px/s,
    +x = right), colour, alpha, rate (/s), flake (px), material (puff = grey alpha flakes | glint = hot cinders)."""
    w, h = X.px("w", 400), X.px("h", 200)
    vy, vx = X.px("fall", 6), X.px("drift", 2)
    life = float(X.e.get("life", 9))
    rate = float(X.e.get("rate", 4))
    fl = X.px("flake", 2.5)
    mat = X.A[X.e.get("material", "puff")]
    return [X.group(nm, [SF.psys("ash", mat, lifetime=[life * 0.7, life * 1.2], speed=[0],
                                 velX=[vx * 0.4, vx * 1.6], velY=[-vy * 1.3, -vy * 0.7], size=[fl * 0.6, fl * 1.3],
                                 rate=rate, maxParticles=max(8, int(rate * life * 1.5)), shape="box",
                                 shapeScale=[w, h, min(w, h) * 0.3], color=X.col([0.32, 0.3, 0.29]) + [X.op(0.7)],
                                 alphaKeys=TA.sqk([0, 0, 0.15, 1, 0.8, 1, 1, 0]), rotation=[0, 360],
                                 rotSpeed=[-90, 90], noise=fl * 2.0, noiseFreq=0.7, customUV=False)])]


def k_lava_bubbles(X: TA.K, nm):
    """Lava blisters swelling and popping over a box: w, h (px), bubble (px), colour, rate (/s), life (s),
    intensity (0..1)."""
    w, h = X.px("w", 40), X.px("h", 12)
    b = X.px("bubble", 5)
    life = float(X.e.get("life", 0.9))
    rate = float(X.e.get("rate", 3))
    a = float(X.e.get("intensity", 0.6))
    return [X.group(nm, [SF.psys("lava_bubbles", X.A["glow"], lifetime=[life * 0.6, life * 1.3], speed=[0],
                                 velY=[X.m * 0.5, X.m * 2.0], size=[b * 0.6, b * 1.4], rate=rate,
                                 maxParticles=max(6, int(rate * life * 3)), shape="box",
                                 shapeScale=[w, h, min(w, h) * 0.3], color=X.col([1.0, 0.62, 0.2]) + [a],
                                 alphaKeys=[0, 0, 0.2, 0.8, 0.75, 1, 0.85, 0.3, 1, 0],
                                 sizeKeys=[0, 0.15, 0.7, 1, 0.85, 1.25, 1, 0], customUV=False)])]


def k_heat_haze(X: TA.K, nm):
    """Heat shimmer rising off lava: a few very faint warm wisps climbing slowly. w (px, source width), rise (px),
    puff (px), colour, alpha, count (alive)."""
    w, h = X.px("w", 80), X.px("rise", 60)
    life = float(X.e.get("life", 5))
    v = h / life
    n = int(X.e.get("count", 5))
    sz = X.px("puff", max(float(X.e.get("w", 80)) * 0.5, 20))
    return [X.group(nm, [SF.psys("heat_haze", X.A["spray"], lifetime=[life * 0.8, life * 1.2], speed=[0],
                                 velX=[-v * 0.15, v * 0.15], velY=[v * 0.7, v * 1.2], size=[sz * 0.7, sz * 1.2],
                                 rate=round(n / life, 3), maxParticles=n * 2, shape="box",
                                 shapeScale=[w, w * 0.08, w * 0.2], color=X.col([1.0, 0.55, 0.3]) + [X.op(0.08)],
                                 alphaKeys=TA.sqk([0, 0, 0.3, 1, 0.7, 0.7, 1, 0]), sizeKeys=[0, 0.6, 1, 1.5],
                                 rotation=[0, 360], rotSpeed=[-8, 8], noise=w * 0.08, noiseFreq=0.5)])]


KINDS = {"ash": k_ash, "lava_bubbles": k_lava_bubbles, "heat_haze": k_heat_haze}
