"""fair.py <p1.npz> <p2.npz> <p3.npz> [--gap 0.01]

Stage 3: exact sparse fairing of the Blender fills (new vertices only; the original mesh is held).
- body panel: bi-Laplacian (minimum-curvature) solve, so the rebuilt torso front continues the surrounding robe
  tangentially; then clamped --gap behind the arm block's front surface wherever the folded arms cover it (clamped
  vertices are held and the rest re-solved, 4 rounds) so the panel never shows at rest
- arm caps: harmonic solve (they face the chest and are hidden at rest)"""
import sys, numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as sla
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from raylib import ray_z
from scipy.spatial import cKDTree

a = sys.argv[1:]
d1, d2 = np.load(a[0]), np.load(a[1])
GAP = float(a[a.index("--gap") + 1]) if "--gap" in a else 0.01
V1 = d1["V"]; armT = V1[d1["armF"]]
out = dict(d2)


def lap(P, F):
    n = len(P)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]); E = np.concatenate([E, E[:, ::-1]])
    E = np.unique(E, axis=0)
    A = sp.csr_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n))
    deg = np.asarray(A.sum(1)).ravel()
    return sp.diags(1 / np.maximum(deg, 1)) @ A - sp.identity(n)


def solve(P, F, free, order):
    L = lap(P, F)
    M = (L.T @ L).tocsr() if order == 2 else L.tocsr()
    fi = np.nonzero(free)[0]; ci = np.nonzero(~free)[0]
    eps = 1e-6
    Mff = (M[fi][:, fi] + eps * sp.identity(len(fi))).tocsc(); rhs = -M[fi][:, ci] @ P[ci] + eps * P[fi]
    lu = sla.splu(Mff)
    Q = P.copy(); Q[fi] = np.stack([lu.solve(rhs[:, k]) for k in range(3)], 1)
    return Q


# --clamp back: the panel is held GAP behind the arm block's BACK (its faired, inflated caps) instead of its front, so
# once the arms leave, the rebuilt chest sits flush with the robe rather than as a shelf out where the forearms were.
# The arm part is then solved first so its caps exist for the clamp.
# --order 1: harmonic panel instead of minimum curvature. Bi-Laplacian overshoots its boundary where the clamp holds the
# chest back next to a forward rim (the hood cowl): the free vertices between swing out past the cowl as blades.
# A harmonic solve obeys the maximum principle, so the panel stays inside its rim's depth range.
ORD = int(a[a.index("--order") + 1]) if "--order" in a else 2
BACK = "--clamp" in a and a[a.index("--clamp") + 1] == "back"
for tag, panel in ((("arm", False), ("body", True)) if BACK else (("body", True), ("arm", False))):
    P = d2[tag + "_pos"].copy(); F = d2[tag + "_faces"]
    # Blender's vertex identity does not survive the bmesh edits: re-identify originals by exact (f32) position
    dd, wi = cKDTree(d2["U"]).query(P)
    wid = np.where(dd < 2e-6, wi, -1); out[tag + "_wid"] = wid; new = wid < 0
    used = np.zeros(len(P), bool); used[F.ravel()] = True
    free = new & used
    if panel:
        P = solve(P, F, free, 1)              # start from harmonic, then minimum curvature
        P = solve(P, F, free, ORD)
        held = np.zeros(len(P), bool)
        for r in range(4):
            if BACK:   # backmost arm surface at (x, y): a +Z ray from behind against the solved arm part (caps included)
                fz = ray_z(np.c_[P[:, :2], np.full(len(P), -2.0)], out["arm_pos"][d2["arm_faces"]], sign=1)
            else:      # arm front surface at (x, y)
                fz = ray_z(np.c_[P[:, :2], np.full(len(P), 2.0)], armT, sign=-1)
            lim = fz - GAP
            over = free & ~np.isnan(fz) & (P[:, 2] > lim)
            print(tag, "round", r, "over", int(over.sum()), "max", float(np.nanmax(np.where(over, P[:, 2] - lim, np.nan))) if over.any() else 0)
            if not over.any(): break
            P[over, 2] = lim[over]; held |= over
            P = solve(P, F, free & ~held, ORD)
    else:
        P = solve(P, F, free, 1)
        # sliver spikes of the old fused surface ring the cut: relax the original arm vertices within 2 rings of the
        # caps (hidden against the chest at rest), then re-solve the caps on the relaxed rim
        L = lap(P, F)
        A_ = (abs(L) > 0).astype(float)
        zone = (A_ @ (A_ @ free.astype(float))) > 0
        zone &= ~free & used
        for _ in range(int(a[a.index("--relax") + 1]) if "--relax" in a else 6):
            P[zone] += 0.5 * (L @ P)[zone]
        P = solve(P, F, free, 1)
        print(tag, "relaxed rim vertices", int(zone.sum()))
        # --inflate: a harmonic cap over a half-embedded sleeve shell is flat, so the freed sleeve reads as a blade.
        # Bulge each cap into the hollow side of its shell: a Poisson bubble (L h = -1, rim held at 0, max scaled to
        # --inflate) along the cap's area-weighted mean normal (one direction per cap: a wrapping cap's own vertex normals point
        # sideways), signed away from its side's sleeve shell
        INF = float(a[a.index("--inflate") + 1]) if "--inflate" in a else 0.0
        if INF > 0:
            from scipy.sparse.csgraph import connected_components
            nf = len(P); Fn = F[np.isin(F, np.nonzero(free)[0]).any(1)]
            E_ = np.concatenate([Fn[:, [0, 1]], Fn[:, [1, 2]]])
            nc, lab = connected_components(sp.coo_matrix((np.ones(len(E_)), (E_[:, 0], E_[:, 1])), shape=(nf, nf)), directed=False)
            Ea = np.concatenate([F[:, [0, 1]], F[:, [1, 2]]])
            _, blk = connected_components(sp.coo_matrix((np.ones(len(Ea)), (Ea[:, 0], Ea[:, 1])), shape=(nf, nf)), directed=False)
            L = lap(P, F); fi = np.nonzero(free)[0]
            h = np.zeros(nf); h[fi] = sla.splu((-L[fi][:, fi]).tocsc()).solve(np.ones(len(fi)) / max(np.median(np.asarray((abs(L) > 0).sum(1)).ravel()), 1))
            T = P[Fn]; fnm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
            vn = np.zeros((nf, 3)); np.add.at(vn, Fn.ravel(), np.repeat(fnm, 3, axis=0))
            vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
            orig = used & ~free
            for c in np.unique(lab[fi]):
                cv = fi[lab[fi] == c]
                if not len(cv): continue
                capc = P[cv].mean(0)
                ov = np.nonzero(orig)[0]; ov = ov[blk[ov] == blk[cv[0]]]   # this cap's own sleeve shell (connected block)
                fc = np.isin(Fn, cv).any(1); nb_ = fnm[fc].sum(0); nb_ /= np.linalg.norm(nb_) + 1e-12   # cap's mean axis
                dirc = nb_ * np.sign(nb_ @ (capc - P[ov].mean(0)))                                     # away from shell
                hc = h[cv] / (h[cv].max() + 1e-12)
                P[cv] += INF * hc[:, None] * dirc[None]
                print(tag, "cap", int(c), "inflated", len(cv), "vertices along", np.round(dirc, 2).tolist())
    disp = np.linalg.norm(P[free] - d2[tag + "_pos"][free], axis=1)
    print(tag, "free", int(free.sum()), "mean move", float(disp.mean()) if len(disp) else 0)
    out[tag + "_pos"] = P
np.savez(a[2], **out)
