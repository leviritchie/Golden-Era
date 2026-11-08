"""Contact sheet for stride_match_glb.py: each grounded foot's position along the ground over two game-time Move
cycles, before and after, with the body carried forward at moveSpeed. A planted foot draws a flat line; a sliding
foot climbs. Thick segments are the samples the slip metric counts as contact.

    python tools/homm3_def_retarget_delivery/stride_sheet.py <out.png> <unit>=<before.glb>,<after.glb> [...]

The after GLB must carry the stride-match stamp (moveSpeed, worldScale, bodyHeight are read from it).
Proof tier: generated artifact (offline FK of the GLB keys; not a Unity or in-game render).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stride_gait as G  # noqa: E402
import stride_match_glb as S  # noqa: E402


def ground_tracks(g: S.Glb, ms: float, scale: float, height: float):
    times, end = S.cycle_times(g)
    mats = g.world(g.sample_local(S.MOVE, times))
    chains = S.chains_of(g)
    tr = {c["name"]: S.contact_traj(g, mats, c) for c in chains}
    floor = min(float(t[:, G.UP].min()) for t in tr.values())
    tr = {k: v for k, v in tr.items() if v[:, G.UP].min() <= floor + S.GROUND_BAND * height}
    game_t = times / S.PLAYBACK
    cyc = end / S.PLAYBACK
    t2 = np.r_[game_t, game_t + cyc]
    body = ms * t2 / scale                                 # body travel in body units
    out = {}
    for k, v in tr.items():
        v2 = np.r_[v, v]
        x = (v2 @ S.FORWARD + body) / height
        m = G.contact_mask(v[:, G.UP], height)
        out[k] = (t2, x, np.r_[m, m])
    return out


def main(argv: list[str]) -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out = Path(argv[0])
    rows = [a.split("=", 1) for a in argv[1:]]
    fig, axes = plt.subplots(len(rows), 2, figsize=(11, 2.6 * len(rows)), squeeze=False)
    for r, (unit, pair) in enumerate(rows):
        before, after = (Path(p) for p in pair.split(","))
        ga = S.Glb.load(after)
        st = ga.json["asset"]["extras"][S.STAMP]
        for c, (tag, g) in enumerate((("before", S.Glb.load(before)), ("after", ga))):
            m = S.measure(g, st["moveSpeed"], st["worldScale"], st["bodyHeight"], flier=False)   # stamped = walker
            ax = axes[r][c]
            for k, (t, x, cm) in ground_tracks(g, st["moveSpeed"], st["worldScale"], st["bodyHeight"]).items():
                ln, = ax.plot(t, x, lw=0.8, label=k)
                ax.plot(t, np.where(cm, x, np.nan), lw=3.0, color=ln.get_color())
            ax.set_title(f"{unit} {tag}: slip {m['slipRatio']:.2f}, required/actual stride "
                         f"{m['requiredOverActual']:.2f}", fontsize=9)
            ax.set_xlabel("game seconds", fontsize=8)
            ax.set_ylabel("foot along ground / body height", fontsize=8)
            ax.tick_params(labelsize=7)
            ax.legend(fontsize=6, loc="upper left")
    fig.suptitle("Unit_Move foot position along the ground (body moving at moveSpeed): flat = planted", fontsize=10)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
