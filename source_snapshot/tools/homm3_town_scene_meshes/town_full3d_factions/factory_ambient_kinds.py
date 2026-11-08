"""Factory's own ambient kinds (loaded by town_full3d_ambient.py stage): a steam-and-iron town, so most of its life
keeps a machine rhythm instead of drifting at random.

Rhythm without bursts: a system emitting at a constant rate of 1 / period emits on an exact beat, and every system
of one group starts on the same frame. So a "burst" (steam chuff, spark shower, valve hiss) is several one-particle
systems sharing that rate, and a coherent light (sodium lamp stutter, weld arc, furnace bellows) is ONE particle
alive at a time whose life is the whole cycle, its alpha keys being the light's own timeline.

Written like the shared kinds: X is town_full3d_ambient.K (anchor, metres per px, materials on X.A), opacity through
X.op() / TA.sqk() (VfxUber squares vertex alpha), velocity curves in one system all [min, max] pairs.
Screen axes: local x = right, y = up, z = depth. Stretched particles (renderMode 1) get their streak from velocity:
velocityScale = streak_m / speed_m, so a streak of L px at speed v px/s is L / v.
"""
from __future__ import annotations

import math

import town_full3d_ambient as TA
import stronghold_full3d_fx as SF


def _mat(X, key, make):
    """One material per kind and town (cached on X.A, which stage() shares across effects)."""
    if key not in X.A:
        X.A[key] = make()
    return X.A[key]


def _soot(X):
    # dark heavy smoke: the puff sprite, alpha-blended, no brightening -- coal smoke must not glow
    return _mat(X, "fa_soot", lambda: X.M.uber("smoke_06_vfx", None, "glow_08_vfx", mn=0.0, mx=0.3, lerp=1.0,
                                                blend=1.0, color=0.8))


def _dirvel(dx, dy, v, lo, hi):
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, -dy / n            # spec dir is screen (y down)
    a, b = sorted((ux * v * lo, ux * v * hi))
    c, d = sorted((uy * v * lo, uy * v * hi))
    return [a, b], [c, d]


# ------------------------------------------------------------------------------------------------ steam
def k_steam_chuff(X: TA.K, nm):
    """Rhythmic steam from an engine stack or vent: on every beat a fat white cloud (puffs particles born together)
    bursts out fast, swells and slows as it climbs, with a trailing wisp on the same beat. period (s per chuff),
    width (px at the vent), rise (px), lean (px of sideways drift over a life, +x = right), colour, alpha, puffs."""
    per = float(X.e.get("period", 1.2))
    w, h = X.px("width", 8), X.px("rise", 60)
    life = float(X.e.get("life", 2.6))
    v = h / life
    lean = X.px("lean", 12) / life
    a = float(X.e.get("alpha", 0.75))
    col = X.col([0.96, 0.96, 0.95])
    n = int(X.e.get("puffs", 3))
    cnt = int(life / per) + 3
    sysl = []
    for i in range(n):
        f = 0.8 + 0.4 * i / max(1, n - 1)                  # the cloud's puffs climb at a spread of speeds
        sysl.append(SF.psys(f"chuff{i}", X.A["puff"], lifetime=[life * 0.85, life * 1.05], speed=[0],
                            velX=sorted([lean * 0.5 * f, lean * 1.3 * f]), velY=[v * 0.85 * f, v * 1.1 * f],
                            velZ=[-w * 0.3, w * 0.3], size=[w * 3.6, w * 4.6], rate=round(1.0 / per, 4),
                            maxParticles=cnt, radius=w * 0.35, color=col + [X.op(a)],
                            alphaKeys=TA.sqk([0, 0.3, 0.08, 1, 0.4, 0.75, 1, 0]),
                            sizeKeys=[0, 0.3, 0.12, 0.9, 0.5, 1.6, 1, 2.4], rotation=[0, 360], rotSpeed=[-40, 40],
                            noise=w * 0.4, noiseFreq=0.5, customUV=False))
    sysl.append(SF.psys("chuff_wisp", X.A["puff"], lifetime=[life * 1.1, life * 1.4], speed=[0],
                        velX=sorted([lean * 0.6, lean * 1.2]), velY=[v * 0.55, v * 0.7], velZ=[0, 0],
                        size=[w * 2.4, w * 3.0], rate=round(1.0 / per, 4), maxParticles=int(life * 1.4 / per) + 3,
                        radius=w * 0.1, color=col + [X.op(a * 0.55)], alphaKeys=TA.sqk([0, 0, 0.15, 1, 0.6, 0.5, 1, 0]),
                        sizeKeys=[0, 0.5, 1, 2.8], rotation=[0, 360], rotSpeed=[-20, 20], noise=w * 0.6,
                        noiseFreq=0.4, customUV=False))
    return [X.group(nm, sysl)]


def k_valve_hiss(X: TA.K, nm):
    """A safety valve blowing off: every period a short, hard jet of steam streaks out sideways and dissolves.
    dir [dx, dy] (screen, y down), reach (px), width (px), period (s), jets (particles per hiss), alpha."""
    per = float(X.e.get("period", 4.0))
    reach, w = X.px("reach", 30), X.px("width", 4)
    dx, dy = X.e.get("dir", [1, -0.3])
    n = int(X.e.get("jets", 5))
    life = float(X.e.get("life", 0.7))
    a = float(X.e.get("alpha", 0.6))
    sysl = []
    for i in range(n):
        f = 0.6 + 0.8 * i / max(1, n - 1)
        vx, vy = _dirvel(dx, dy, reach / life * f, 0.85, 1.15)
        sysl.append(SF.psys(f"hiss{i}", X.A["spray"], lifetime=[life * 0.7, life * 1.1], speed=[0], velX=vx, velY=vy,
                            velZ=[-reach * 0.1, reach * 0.1], size=[w * 1.5, w * 2.4], rate=round(1.0 / per, 4),
                            maxParticles=2, radius=w * 0.2, color=X.col([1, 1, 1]) + [X.op(a)],
                            alphaKeys=TA.sqk([0, 0, 0.05, 1, 0.4, 0.6, 1, 0]), sizeKeys=[0, 0.4, 1, 3.0],
                            rotation=[0, 360], rotSpeed=[-90, 90]))
    return [X.group(nm, sysl)]


# ------------------------------------------------------------------------------------------------ smoke
def k_oily_smoke(X: TA.K, nm):
    """Coal / oil smoke from a foundry stack: a thick brown-black column that billows slowly and is sheared off
    downwind, with sooty flecks. width (px), rise (px), wind (px/s, +x = right), colour, alpha, period (s life)."""
    w, h = X.px("width", 7), X.px("rise", 80)
    life = float(X.e.get("period", 6.0))
    v = h / life
    wind = X.px("wind", 6)
    a = float(X.e.get("alpha", 0.55))
    col = X.col([0.17, 0.14, 0.12])
    mat = _soot(X)
    body = SF.psys("oily", mat, lifetime=[life * 0.85, life * 1.15], speed=[0],
                   velX=sorted([wind * 0.5, wind * 1.3]), velY=[v * 0.7, v * 1.0], size=[w * 4.0, w * 5.4],
                   rate=round(9.0 / life + 2.0, 2), maxParticles=80, radius=w * 0.25,
                   color=col + [X.op(a)], alphaKeys=TA.sqk([0, 0, 0.1, 1, 0.55, 0.65, 1, 0]),
                   sizeKeys=[0, 0.5, 0.3, 1.3, 1, 3.2], rotation=[0, 360], rotSpeed=[-12, 12],
                   noise=w * 0.9, noiseFreq=0.25, customUV=False)
    fleck = SF.psys("soot", mat, lifetime=[life * 0.6, life * 0.9], speed=[0], velX=sorted([wind * 0.8, wind * 1.8]),
                    velY=[v * 0.5, v * 1.1], size=[X.m * 1.6, X.m * 2.6], rate=1.5, maxParticles=12, radius=w * 0.4,
                    color=[0.08, 0.07, 0.06, X.op(min(1.0, a * 1.4))], alphaKeys=TA.sqk([0, 0, 0.1, 1, 0.7, 0.8, 1, 0]),
                    noise=w * 1.2, noiseFreq=0.9, customUV=False)
    return [X.group(nm, [body, fleck])]


# ------------------------------------------------------------------------------------------------ sparks and arcs
def k_spark_shower(X: TA.K, nm):
    """A hammer or piston striking hot metal on a beat: every period a white flash and a fan of short orange
    streaks thrown up and out that fall away. period (s), sparks (count per strike), reach (px), streak (px),
    colour, spread (0..1, how wide the fan opens), flash (px, 0 = none)."""
    per = float(X.e.get("period", 1.6))
    n = int(X.e.get("sparks", 6))
    reach = X.px("reach", 20)
    life = float(X.e.get("life", 0.45))
    spread = float(X.e.get("spread", 0.8))
    streak = float(X.e.get("streak", 4))
    col = X.col([1.0, 0.68, 0.28])
    sk = X.px("spark", 2.2)
    sysl = []
    for i in range(n):
        ang = math.pi / 2 + spread * (math.pi * 0.8) * ((i + 0.5) / n - 0.5)
        dx, dy = math.cos(ang), -math.sin(ang)
        v = reach / life
        vx, vy = _dirvel(dx, dy, v, 0.7, 1.25)
        vy = [vy[0] - v * 0.35, vy[1] - v * 0.35]           # they fall as they fly
        sysl.append(SF.psys(f"spark{i}", X.A["glint"], lifetime=[life * 0.6, life * 1.2], speed=[0], velX=vx,
                            velY=vy, velZ=[-v * 0.2, v * 0.2], size=[sk * 0.8, sk * 1.2], rate=round(1.0 / per, 4),
                            maxParticles=2, radius=X.m * 0.5, color=col + [1.0],
                            alphaKeys=[0, 1, 0.6, 0.8, 1, 0], renderMode=1, lengthScale=1.0,
                            velocityScale=round(streak / (reach / life / X.m), 4), customUV=False))
    fl = X.px("flash", 9)
    if fl > 0:
        sysl.append(SF.psys("strike", X.A["glow"], lifetime=[0.16, 0.2], speed=[0], size=[fl * 0.9, fl * 1.1],
                            rate=round(1.0 / per, 4), maxParticles=2, radius=X.m * 0.2,
                            color=[1.0, 0.9, 0.7, float(X.e.get("intensity", 0.6))], alphaKeys=[0, 1, 0.3, 0.6, 1, 0],
                            customUV=False))
    return [X.group(nm, sysl)]


def k_arc_crackle(X: TA.K, nm):
    """Electric arcs about a conductor: a cold corona that swells on a beat and short blue-white zaps that jitter
    off it. radius (px of the zap shell), corona (px), period (s per discharge), rate (zaps /s), colour."""
    r = X.px("radius", 14)
    cor = X.px("corona", 26)
    per = float(X.e.get("period", 2.4))
    col = X.col([0.55, 0.78, 1.0])
    zap = SF.psys("zaps", X.A["glint"], lifetime=[0.12, 0.28], speed=[0], velX=[-r * 6, r * 6],
                  velY=[-r * 6, r * 6], velZ=[-r * 2, r * 2], size=[X.px("spark", 2.2) * 0.8, X.px("spark", 2.2) * 1.2],
                  rate=float(X.e.get("rate", 14)), maxParticles=12, shape="sphere", radius=r, radiusThickness=0.2,
                  color=col + [1.0], alphaKeys=[0, 1, 0.5, 0.4, 0.7, 1, 1, 0], renderMode=1, lengthScale=1.0,
                  velocityScale=0.09, noise=r * 1.5, noiseFreq=4.0, noiseScroll=3.0, customUV=False)
    # the discharge: one particle per cycle -- dim hum, a fast build, a bright crack, a stutter, back to the hum
    coro = SF.psys("corona", X.A["glow"], lifetime=[per, per], speed=[0], size=[cor, cor], rate=round(1.0 / per, 4),
                   maxParticles=2, radius=X.m * 0.1, color=col + [float(X.e.get("intensity", 0.4))],
                   alphaKeys=[0, 0.25, 0.55, 0.3, 0.62, 1.0, 0.66, 0.35, 0.7, 0.85, 0.78, 0.25, 1, 0.25],
                   sizeKeys=[0, 0.8, 0.6, 0.85, 0.63, 1.2, 0.8, 0.9, 1, 0.8], customUV=False)
    return [X.group(nm, [coro, zap])]


def k_weld_flash(X: TA.K, nm):
    """An arc welder at work inside a shop: on each cycle a cluster of hard blue-white stutters, then dark.
    size (px), period (s), duty (share of the cycle the welder is on), colour, intensity."""
    s = X.px("size", 10)
    per = float(X.e.get("period", 5.0))
    duty = float(X.e.get("duty", 0.35))
    t0, d = 0.15, duty
    # Unity gradients take 8 alpha keys: on, three stutters, off -- dark for the rest of the cycle
    keys = [0, 0, t0, 0, t0 + 0.04 * d, 1.0, t0 + 0.2 * d, 0.15, t0 + 0.35 * d, 0.9, t0 + 0.6 * d, 0.1,
            t0 + 0.8 * d, 1.0, t0 + d, 0]
    return [X.group(nm, [SF.psys("weld", X.A["glow"], lifetime=[per, per], speed=[0], size=[s, s],
                                 rate=round(1.0 / per, 4), maxParticles=2, radius=X.m * 0.1,
                                 color=X.col([0.7, 0.85, 1.0]) + [float(X.e.get("intensity", 0.55))],
                                 alphaKeys=keys, customUV=False),
                         SF.psys("weld_sparks", X.A["glint"], lifetime=[0.25, 0.45], speed=[0],
                                 velX=[-s * 3, s * 3], velY=[-s * 3.5, s * 1.5], velZ=[-s, s],
                                 size=[X.px("spark", 1.8) * 0.8, X.px("spark", 1.8) * 1.2], rate=float(X.e.get("rate", 6)) * duty,
                                 maxParticles=8, radius=s * 0.1, color=[1, 0.85, 0.55, 1.0],
                                 alphaKeys=[0, 1, 1, 0], renderMode=1, lengthScale=1.0, velocityScale=0.05,
                                 customUV=False)])]


# ------------------------------------------------------------------------------------------------ lights
def k_sodium_lamp(X: TA.K, nm):
    """A gas / sodium lamp: a steady amber core and halo that now and then stutters (two quick dropouts) as the
    mantle flickers. size (px of the halo), period (s between stutters), colour, intensity, phase (0..1 where in the
    cycle the stutter falls)."""
    s = X.px("size", 14)
    per = float(X.e.get("period", 6.0))
    a = float(X.e.get("intensity", 0.45))
    ph = min(0.85, max(0.05, float(X.e.get("phase", 0.6))))
    stutter = [0, 1, ph, 1, ph + 0.012, 0.25, ph + 0.03, 0.9, ph + 0.045, 0.1, ph + 0.07, 1, 1, 1]
    col = X.col([1.0, 0.66, 0.22])
    return [X.group(nm, [SF.psys("halo", X.A["glow"], lifetime=[per, per], speed=[0], size=[s, s],
                                 rate=round(1.0 / per, 4), maxParticles=2, radius=X.m * 0.05, color=col + [a],
                                 alphaKeys=stutter, customUV=False),
                         SF.psys("core", X.A["glint"], lifetime=[per, per], speed=[0], size=[s * 0.22, s * 0.22],
                                 rate=round(1.0 / per, 4), maxParticles=2, radius=X.m * 0.05,
                                 color=[1.0, 0.86, 0.55, 1.0], alphaKeys=stutter, customUV=False)])]


def k_furnace_breath(X: TA.K, nm):
    """The mouth of a furnace or firebox breathing with the bellows: one coherent glow that heaves bright-yellow
    and sinks back to deep red on a slow beat. size (px), period (s per breath), intensity, colour (the hot end)."""
    s = X.px("size", 24)
    per = float(X.e.get("period", 3.2))
    hot = X.col([1.0, 0.78, 0.35])
    return [X.group(nm, [SF.psys("breath", X.A["glow"], lifetime=[per, per], speed=[0], size=[s, s],
                                 rate=round(1.0 / per, 4), maxParticles=2, radius=X.m * 0.05,
                                 color=[1, 1, 1, float(X.e.get("intensity", 0.45))],
                                 colorKeys=[0, 0.85, 0.28, 0.12, 0.35] + hot + [0.75, 1.0, 0.42, 0.15, 1, 0.85, 0.28, 0.12],
                                 alphaKeys=[0, 0.55, 0.35, 1.0, 0.6, 0.85, 1, 0.55],
                                 sizeKeys=[0, 0.85, 0.35, 1.08, 1, 0.85], customUV=False)])]


# ------------------------------------------------------------------------------------------------ moving metal / water
def k_pipe_glints(X: TA.K, nm):
    """Highlights travelling along a pipe, rail or belt (sun on moving copper): small gleams born at one end that
    slide to the other. to [dx, dy] (px from the anchor to the far end, screen y down), speed (px/s), spark (px),
    colour, rate (/s)."""
    dx, dy = X.e.get("to", [40, 0])
    L = math.hypot(dx, dy) or 1.0
    sp = float(X.e.get("speed", 20))
    life = L / sp
    vx, vy = _dirvel(dx, dy, X.px("speed", 20), 0.95, 1.05)
    k = X.px("spark", 2.4)
    return [X.group(nm, [SF.psys("gleam", X.A["glint"], lifetime=[life * 0.95, life * 1.0], speed=[0], velX=vx,
                                 velY=vy, velZ=[0, 0], size=[k * 0.8, k * 1.2], rate=float(X.e.get("rate", 0.8)),
                                 maxParticles=max(4, int(life * float(X.e.get("rate", 0.8)) * 2) + 2),
                                 radius=X.m * 0.3, color=X.col([1.0, 0.86, 0.6]) + [1.0],
                                 alphaKeys=[0, 0, 0.15, 1, 0.35, 0.3, 0.55, 1, 0.8, 0.4, 1, 0],
                                 sizeKeys=[0, 0.4, 0.15, 1, 0.5, 0.6, 0.6, 1.1, 1, 0.3], customUV=False)])]


def k_tank_drip(X: TA.K, nm):
    """A leaking tank or pipe joint: bright droplets that swell, let go and streak down. fall (px), w (px of the
    leaking seam), rate (drops /s), colour."""
    fall = X.px("fall", 30)
    w = X.px("w", 8)
    life = float(X.e.get("life", 0.7))
    v = fall / life
    hang = SF.psys("bead", X.A["glint"], lifetime=[0.9, 1.3], speed=[0], size=[X.px("drop", 2.0) * 0.6, X.px("drop", 2.0) * 1.1],
                   rate=float(X.e.get("rate", 1.2)), maxParticles=4, shape="box", shapeScale=[w, X.m * 0.2, X.m * 0.2],
                   color=X.col([0.75, 0.9, 1.0]) + [1.0], alphaKeys=[0, 0, 0.5, 0.8, 1, 0.9],
                   sizeKeys=[0, 0.3, 1, 1.0], customUV=False)
    drop = SF.psys("drop", X.A["glint"], lifetime=[life * 0.9, life * 1.1], speed=[0], velX=[0, 0], velY=[-v * 1.1, -v * 0.9],
                   velZ=[0, 0], size=[X.px("drop", 2.0) * 0.8, X.px("drop", 2.0) * 1.0], rate=float(X.e.get("rate", 1.2)), maxParticles=6,
                   shape="box", shapeScale=[w, X.m * 0.2, X.m * 0.2], color=X.col([0.75, 0.9, 1.0]) + [1.0],
                   alphaKeys=[0, 1, 0.8, 0.8, 1, 0], renderMode=1, lengthScale=1.0,
                   velocityScale=round(5.0 * X.m / (v or 1), 4), customUV=False)
    return [X.group(nm, [hang, drop])]


KINDS = {"steam_chuff": k_steam_chuff, "valve_hiss": k_valve_hiss, "oily_smoke": k_oily_smoke,
         "spark_shower": k_spark_shower, "arc_crackle": k_arc_crackle, "weld_flash": k_weld_flash,
         "sodium_lamp": k_sodium_lamp, "furnace_breath": k_furnace_breath, "pipe_glints": k_pipe_glints,
         "tank_drip": k_tank_drip}
