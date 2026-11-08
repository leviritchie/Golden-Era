"""Swept-tube tail rebuild (h3_naga_upg, 2026-10-10 user send-back: "tail deformed in most clips").

The Meshy naga tail is a tight coil whose laps Meshy merged at every contact: the lap surfaces have no wall where
they touch, so once the tail uncoils (Move, MoveStart, MoveEnd) the contact leaves holes and fins however the
fused edges are cut (cove_tailpath fuseCut / dropStraddling / capCuts, chains 1-3). This hook replaces the tail
beyond the waist with a clean tube swept along the hand-placed centreline the Tail_* bones already sit on
(cove_tailpath must run first), welded to the waist and textured from the old tail's own scales.

Config: "coveTube": {"weldS": 0.1, "weldRadius": 0.3, "ringsPerBone": 10, "blendRings": 3, "tipTaper": 0.15,
                     "radiusPct": 75, "uvGrid": 512}
after_skin:
  1. centreline = the Tail_* bone heads + the last tail (TPts); arc length s, parallel-transported frames;
  2. radius profile r(s) = the radiusPct percentile of the old tail vertices' distance to the centreline per s bin
     (smoothed; tapered over the last tipTaper of the length);
  3. the body is bisected by the plane through C(weldS x length) normal to the centreline (only geometry within
     weldRadius of that point), and every tail-weighted vertex past the plane / past weldS is deleted;
  4. the plane's boundary loop is the tube's first ring (its near-duplicate bisect vertices welded, weldMergeFrac of
     the median loop edge): ring k blends the loop's own polar shape and uneven angles into the round, evenly
     sided profile over blendRings rings, then rings follow the centreline to a single tip vertex;
  5. weights: the two nearest tail bones by arc length (hat functions on the bone midpoints, as cove_tailpath), with
     the loop's own torso weights falling to zero over the tail config's waistBlend bones;
  6. UVs: the largest square of the atlas that only the deleted tail used (rasterised at uvGrid) holds the tube,
     ping-pong mapped in both directions (around and along) so the texture is continuous without UV seams; the
     along-period keeps the texel aspect (half the mean circumference per square height).
Pure helpers (radius_profile, transport_frames, largest_square, pingpong, hat_weights) are tested outside Blender
(test_cove_tube.py).
"""
import numpy as np
try:                                  # Blender only; the pure helpers below are unit-tested outside it
    import bmesh
    import bpy
    from mathutils import Vector
except ImportError:
    bmesh = bpy = Vector = None


def arc(C):
    seg = np.linalg.norm(np.diff(C, axis=0), axis=1)
    return seg, np.r_[0, np.cumsum(seg)]


def at_s(C, S, s):
    return np.stack([np.interp(s, S, C[:, i]) for i in range(3)], -1)


def project_s(Q, C):
    """Arc length of each point's nearest centreline point, and its distance."""
    seg, S = arc(C)
    best = np.full(len(Q), np.inf); sv = np.zeros(len(Q))
    for k in range(len(C) - 1):
        a, ab = C[k], C[k + 1] - C[k]
        t = np.clip(((Q - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        d = np.linalg.norm(Q - (a + t[:, None] * ab), axis=1)
        m = d < best; best[m] = d[m]; sv[m] = S[k] + t[m] * seg[k]
    return sv, best


def radius_profile(sv, dist, length, bins=40, pct=75, min_count=10):
    """Per-bin percentile distance -> (bin centres, smoothed radius); empty bins interpolated."""
    edges = np.linspace(0, length, bins + 1); rad = np.full(bins, np.nan)
    for i in range(bins):
        m = (sv >= edges[i]) & (sv < edges[i + 1])
        if m.sum() >= min_count:
            rad[i] = np.percentile(dist[m], pct)
    ok = ~np.isnan(rad)
    if not ok.any():
        raise ValueError("no tail vertices to measure the tube radius from")
    idx = np.arange(bins); rad = np.interp(idx, idx[ok], rad[ok])
    rad = np.convolve(np.pad(rad, 2, mode="edge"), np.ones(5) / 5, "valid")
    return (edges[:-1] + edges[1:]) / 2, rad


def transport_frames(cen, n0=None):
    """Unit tangents and parallel-transported normals/binormals along a polyline of ring centres."""
    tan = np.gradient(cen, axis=0); tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    if n0 is None:
        n0 = np.cross(tan[0], [0.0, 0.0, 1.0])
        if np.linalg.norm(n0) < 1e-6:
            n0 = np.cross(tan[0], [1.0, 0.0, 0.0])
    n0 = np.asarray(n0, float) - tan[0] * (np.asarray(n0, float) @ tan[0]); N = [n0 / np.linalg.norm(n0)]
    for i in range(1, len(cen)):
        n = N[-1] - tan[i] * (N[-1] @ tan[i]); N.append(n / np.linalg.norm(n))
    N = np.array(N)
    return tan, N, np.cross(tan, N)


def largest_square(free):
    """(row, col, size) of the largest all-True axis-aligned square in a boolean grid."""
    h, w = free.shape; dp = np.zeros((h + 1, w + 1), np.int32); best = (0, 0, 0)
    for i in range(h):
        row = free[i]
        for j in range(w):
            if row[j]:
                v = 1 + min(dp[i, j + 1], dp[i + 1, j], dp[i, j])
                dp[i + 1, j + 1] = v
                if v > best[2]:
                    best = (i - v + 1, j - v + 1, v)
    return best


def pingpong(x):
    """Triangle wave in [0, 1] with period 2: continuous, so a mirrored texture tile needs no UV seam."""
    f = np.mod(x, 2.0)
    return 1 - np.abs(1 - f)


def hat_weights(u, nbones):
    """Bone weights at bone-unit coordinate u (bone k spans [k, k+1]): hats on the bone midpoints, as cove_tailpath."""
    w = {k: max(0.0, 1 - abs(u - (k + 0.5))) for k in range(nbones)}
    w = {k: x for k, x in w.items() if x > 1e-4} or {min(nbones - 1, max(0, int(u))): 1.0}
    s = sum(w.values())
    return {k: x / s for k, x in w.items()}


def short_loop_drops(pts, frac=0.25):
    """Indices of a closed loop's vertices to weld into their predecessor: the bisect leaves near-duplicate vertices
    (sliver edges far below the loop's median edge) that any later rotation tears; greedy, the loop stays >= 3."""
    pts = np.asarray(pts, float); keep = list(range(len(pts))); drop = []
    med = float(np.median(np.linalg.norm(pts - np.roll(pts, -1, 0), axis=1)))
    i = 0
    while i < len(keep) and len(keep) > 3:
        a, b = keep[i], keep[(i + 1) % len(keep)]
        if np.linalg.norm(pts[b] - pts[a]) < frac * med:
            drop.append(b); keep.remove(b)
            continue
        i += 1
    return drop


def winding(pts, P0, tan):
    """Turns a closed loop makes about the axis through P0 along tan (signed; ~ +-1 for the loop around the tail)."""
    q = np.asarray(pts, float) - P0; q = q - np.outer(q @ tan, tan)
    e1 = q[np.argmax(np.linalg.norm(q, axis=1))]; e1 = e1 / max(np.linalg.norm(e1), 1e-12); e2 = np.cross(tan, e1)
    a = np.arctan2(q @ e2, q @ e1); d = np.diff(np.r_[a, a[0]])
    d = (d + np.pi) % (2 * np.pi) - np.pi
    return float(d.sum() / (2 * np.pi))


def uniform_phi(phi):
    """The loop's (counter-clockwise) polar angles unwrapped, and the evenly spaced angles nearest to them: rings
    blend from the first to the second, so the tube's sides are even (the bisect loop's uneven angles would otherwise
    carry sliver edges down the whole tube and collapse to sub-millimetre edges at the tapered tip)."""
    pu = np.unwrap(np.asarray(phi, float)); M = len(pu); j = np.arange(M) * 2 * np.pi / M
    return pu, float(np.mean(pu - j)) + j


def _raster(free, tris_uv, val):
    G = free.shape[0]
    for t in tris_uv:
        p = t * (G - 1)
        x0, y0 = np.floor(p.min(0)).astype(int); x1, y1 = np.ceil(p.max(0)).astype(int)
        xs, ys = np.meshgrid(np.arange(max(x0, 0), min(x1, G - 1) + 1), np.arange(max(y0, 0), min(y1, G - 1) + 1))
        q = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], 1)
        a, b, c = p
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            free[np.clip(np.round(p[:, 1]).astype(int), 0, G - 1), np.clip(np.round(p[:, 0]).astype(int), 0, G - 1)] = val
            continue
        l1 = ((b[1] - c[1]) * (q[:, 0] - c[0]) + (c[0] - b[0]) * (q[:, 1] - c[1])) / d
        l2 = ((c[1] - a[1]) * (q[:, 0] - c[0]) + (a[0] - c[0]) * (q[:, 1] - c[1])) / d
        m = (l1 >= -0.5 / G) & (l2 >= -0.5 / G) & (1 - l1 - l2 >= -0.5 / G)
        # conservative: any texel the triangle touches (dilated by half a texel)
        free[ys.ravel()[m], xs.ravel()[m]] = val
        free[np.clip(np.round(p[:, 1]).astype(int), 0, G - 1), np.clip(np.round(p[:, 0]).astype(int), 0, G - 1)] = val


def after_skin(g):
    cfg = g["cfg"]; spec = cfg.get("coveTube")
    TAILB, TPts = g["TAILB"], g["TPts"]
    if not spec or not TAILB:
        return
    body = g["body"]; NT = len(TAILB)
    C = np.array([p[:] for p in TPts], float)
    seg, S = arc(C); L = S[-1]
    gi = {vg.name: vg.index for vg in body.vertex_groups}
    tail_ids = {gi[n]: k for k, n in enumerate(TAILB)}
    bm = bmesh.new(); bm.from_mesh(body.data)
    dl = bm.verts.layers.deform.verify(); uvl = bm.loops.layers.uv.active
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    share = lambda v: sum(w for gk, w in v[dl].items() if gk in tail_ids)
    sh = np.array([share(v) for v in bm.verts])
    Q = np.array([v.co[:] for v in bm.verts])
    sv, dist = project_s(Q, C)
    s0 = spec.get("weldS", 0.1) * L
    tailv = (sh > 0.3) & (sv > s0)
    bc, rad = radius_profile(sv[tailv], dist[tailv], L, pct=spec.get("radiusPct", 75))
    # UV coverage: texels used by kept faces vs by the tail faces about to go
    G = spec.get("uvGrid", 512)
    used_tail = np.zeros((G, G), bool); used_kept = np.zeros((G, G), bool)
    for f in bm.faces:
        uv = np.array([lp[uvl].uv[:] for lp in f.loops]); uv = np.clip(uv, 0, 1)
        tris = [uv[[0, i, i + 1]] for i in range(1, len(uv) - 1)]
        gone = all(tailv[v.index] for v in f.verts)
        _raster(used_tail if gone else used_kept, tris, True)
    r0, c0, size = largest_square(used_tail & ~used_kept)
    if size < spec.get("minSquare", 24):
        raise SystemExit(f"coveTube: largest free tail UV square is {size}/{G} texels; too small to texture the tube")
    # 3. bisect near the weld point, delete the tail beyond it
    P0 = at_s(C, S, s0); tan0 = at_s(C, S, s0 + 1e-3) - at_s(C, S, s0 - 1e-3); tan0 /= np.linalg.norm(tan0)
    WR = spec.get("weldRadius", 0.3)
    near_f = [f for f in bm.faces if any(np.linalg.norm(np.array(v.co[:]) - P0) < WR for v in f.verts)]
    near_e = list({e for f in near_f for e in f.edges}); near_v = list({v for f in near_f for v in f.verts})
    bmesh.ops.bisect_plane(bm, geom=near_f + near_e + near_v, plane_co=Vector(P0), plane_no=Vector(tan0), dist=1e-6)
    bm.verts.ensure_lookup_table()
    kill = []
    for v in bm.verts:
        p = np.array(v.co[:]); t = share(v)
        if t <= 0.05:
            continue
        sp = project_s(p[None], C)[0][0]
        if sp > s0 + WR:                                   # another lap, wherever it is
            kill.append(v)
        elif np.linalg.norm(p - P0) < WR:                  # the weld neighbourhood: cut exactly at the plane
            if (p - P0) @ tan0 > 1e-5:
                kill.append(v)
        elif sp > s0:
            kill.append(v)
    bmesh.ops.delete(bm, geom=kill, context='VERTS')
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table()
    # re-join the fused-lap cuts (split seams) that the tail delete left in the weld neighbourhood: the laps they
    # separated are gone, and a seam crossing the weld plane would break the plane's boundary loop in two
    seam = [v for v in bm.verts if v.is_boundary and np.linalg.norm(np.array(v.co[:]) - P0) < WR]
    n_before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=seam, dist=1e-5)
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table()
    print("HOOK COVE tube weld seams re-joined", n_before - len(bm.verts))
    on_plane = lambda v: abs((np.array(v.co[:]) - P0) @ tan0) < 1e-4 and np.linalg.norm(np.array(v.co[:]) - P0) < WR
    bnd = [e for e in bm.edges if e.is_boundary and on_plane(e.verts[0]) and on_plane(e.verts[1])]
    # order the boundary edges into loops; keep the one around the centreline
    adj = {}
    for e in bnd:
        a, b = e.verts
        adj.setdefault(a, []).append(b); adj.setdefault(b, []).append(a)
    loops, seen = [], set()
    for st in adj:
        if st in seen:
            continue
        lp, prev, cur = [st], None, st; seen.add(st)
        while True:
            nx = [w for w in adj[cur] if w is not prev and w not in seen]
            if not nx:
                break
            prev, cur = cur, nx[0]; lp.append(cur); seen.add(cur)
        loops.append(lp)
    # the weld loop is the one that winds once around the centreline (the bisect can also leave small holes nearby)
    wind = [winding([v.co[:] for v in lp], P0, tan0) for lp in loops]
    print("HOOK COVE tube plane loops", [(len(lp), round(w, 2)) for lp, w in zip(loops, wind)])
    around = [lp for lp, w in zip(loops, wind) if abs(abs(w) - 1) < 0.25]
    if not around:
        import os
        if os.environ.get("COVE_TUBE_DUMP"):              # diagnostics: the cut neighbourhood for an offline look
            be = [e for e in bm.edges if e.is_boundary and min(np.linalg.norm(np.array(v.co[:]) - P0) for v in e.verts) < WR]
            np.savez(os.environ["COVE_TUBE_DUMP"], Q=Q, sh=sh, sv=sv, P0=P0, tan0=tan0, WR=WR, s0=s0, C=C,
                     bnd=np.array([[e.verts[0].co[:], e.verts[1].co[:]] for e in be]).reshape(-1, 2, 3),
                     onp=np.array([on_plane(e.verts[0]) and on_plane(e.verts[1]) for e in be]),
                     kept=np.array([v.co[:] for v in bm.verts]))
        raise SystemExit("coveTube: no boundary loop on the weld plane winds around the centreline")
    loop = max(around, key=len)
    drops = short_loop_drops([v.co[:] for v in loop], spec.get("weldMergeFrac", 0.25))
    print("HOOK COVE tube weld loop", len(loop), "welded near-duplicates", len(drops))
    if drops:                                          # weld the bisect's near-duplicate loop vertices
        tmap = {}
        for i in drops:
            j = i - 1
            while j in drops:
                j -= 1
            tmap[loop[i]] = loop[j % len(loop)]
        loop = [v for i, v in enumerate(loop) if i not in set(drops)]
        bmesh.ops.weld_verts(bm, targetmap=tmap)
        bm.verts.ensure_lookup_table()
    if len(loop) < 8:
        raise SystemExit(f"coveTube: weld loop has {len(loop)} vertices")
    # 4. rings
    rpb = spec.get("ringsPerBone", 10); nr = max(4, int(round(rpb * NT * (L - s0) / L)))
    s = np.linspace(s0, L, nr + 1)
    cen = at_s(C, S, s)
    lp_pts = np.array([v.co[:] for v in loop]) - P0
    n0 = lp_pts[0] - tan0 * (lp_pts[0] @ tan0)
    tan, N, B = transport_frames(cen, n0)
    phi = np.arctan2(lp_pts @ B[0], lp_pts @ N[0]); rho = np.linalg.norm(lp_pts - np.outer(lp_pts @ tan[0], tan[0]), axis=1)
    if np.mean(np.diff(np.unwrap(phi))) < 0:           # walk the loop counter-clockwise about the tangent
        loop = loop[::-1]; phi = phi[::-1]; rho = rho[::-1]
    phi_l, phi_u = uniform_phi(phi)
    tip = spec.get("tipTaper", 0.15)
    r = np.interp(s, bc, rad) * np.clip((L - s) / (tip * L), 0.05, 1) ** 0.5
    nb = spec.get("blendRings", 3)
    M = len(loop); rings = [loop]
    for k in range(1, nr):
        a = min(1.0, k / nb); a = a * a * (3 - 2 * a)
        rr = (1 - a) * rho + a * r[k]; ph = (1 - a) * phi_l + a * phi_u
        pts = cen[k] + rr[:, None] * (np.cos(ph)[:, None] * N[k] + np.sin(ph)[:, None] * B[k])
        rings.append([bm.verts.new(Vector(p)) for p in pts])
    tipv = bm.verts.new(Vector(cen[-1]))
    newf = []
    for k in range(nr - 1):
        A, Bb = rings[k], rings[k + 1]
        for j in range(M):
            newf.append(bm.faces.new((A[j], A[(j + 1) % M], Bb[(j + 1) % M], Bb[j])))
    for j in range(M):
        newf.append(bm.faces.new((rings[-1][j], rings[-1][(j + 1) % M], tipv)))
    # material of the faces we removed (the body is one material in practice)
    for f in newf:
        f.material_index = 0; f.smooth = True
    bmesh.ops.recalc_face_normals(bm, faces=newf)
    # 5. weights
    WB = cfg.get("tail", {}).get("waistBlend", 0.6)
    torso = {}
    for v in loop:
        for gk, w in v[dl].items():
            if gk not in tail_ids:
                torso[gk] = torso.get(gk, 0.0) + w
    ts = sum(torso.values()) or 1.0; torso = {gk: w / ts for gk, w in torso.items()} or {gi["Hips"]: 1.0}
    allr = rings[1:] + [[tipv]]
    for k, rv in enumerate(allr, start=1):
        sk = s[min(k, nr)]; u = np.interp(sk, S, np.arange(NT + 1))
        tw = hat_weights(u, NT); keep = max(0.0, 1.0 - u / WB) if WB > 0 else 0.0
        new = {gk: w * keep for gk, w in torso.items()}
        for kk, w in tw.items():
            new[gi[TAILB[kk]]] = new.get(gi[TAILB[kk]], 0.0) + (1 - keep) * w
        top = sorted(new.items(), key=lambda x: -x[1])[:4]; tot = sum(w for _, w in top)
        for v in rv:
            d = v[dl]; d.clear()
            for gk, w in top:
                if w > 1e-5:
                    d[gk] = w / tot
    # 6. UVs: ping-pong in the free square
    circ = 2 * np.pi * float(np.mean(r[: max(2, nr // 2)]))
    per = circ / 2                                       # along-length per square side
    u0, v0, side = c0 / G, r0 / G, size / G
    pad = 1.5 / G; u0 += pad; v0 += pad; side -= 2 * pad
    ringidx = {}
    for k, rv in enumerate(rings):
        for j, v in enumerate(rv):
            ringidx[v] = (k, j)
    for f in newf:
        for lp in f.loops:
            v = lp.vert
            if v is tipv:
                k, t = nr, 0.5
            else:
                k, j = ringidx[v]; a = min(1.0, k / nb); a = a * a * (3 - 2 * a)
                t = (((1 - a) * phi_l[j] + a * phi_u[j]) % (2 * np.pi)) / (2 * np.pi)
            x = float(pingpong(2 * t)); y = float(pingpong((s[k] - s0) / per))
            lp[uvl].uv = (u0 + side * x, v0 + side * y)
    # triangles, like the rest of the Meshy body: the delivery's numpy corrective smooth (patch lane, cs_rekey) welds
    # the exported GLB triangles, so a quad here would smooth over a diagonal edge Blender's bake never saw and the
    # parity gate refuses every Blender-free patch (tube chain 2: parity p99 0.013 of the height on the tube rings)
    bmesh.ops.triangulate(bm, faces=[f for f in newf if f.is_valid and len(f.verts) > 3], quad_method='FIXED')
    bm.to_mesh(body.data); bm.free()
    print("HOOK COVE tube rings", nr, "sides", M, "deleted", len(kill), "uv square", size, "/", G,
          "radius", round(float(rad.min()), 3), "-", round(float(rad.max()), 3), "weld s", round(float(s0), 3))
