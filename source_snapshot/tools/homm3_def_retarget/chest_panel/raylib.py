import numpy as np
def ray_z(O, T, sign=1):
    """ray along sign*Z from each origin: z of the nearest hit on triangles T (n,3,3), or nan"""
    A_, B_, C_ = T[:, 0], T[:, 1], T[:, 2]
    res = np.full(len(O), np.nan)
    def cr(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
    for i0 in range(0, len(O), 256):
        o = O[i0:i0 + 256][:, None, :]
        w0, w1, w2 = cr(B_, C_, o), cr(C_, A_, o), cr(A_, B_, o)
        area = w0 + w1 + w2; okA = np.abs(area) > 1e-12
        inside = (((w0 >= 0) & (w1 >= 0) & (w2 >= 0)) | ((w0 <= 0) & (w1 <= 0) & (w2 <= 0))) & okA
        zz = (w0 * A_[..., 2] + w1 * B_[..., 2] + w2 * C_[..., 2]) / np.where(okA, area, 1)
        t = sign * (zz - o[..., 2])
        t = np.where(inside & (t > 0), t, np.inf).min(1)
        res[i0:i0 + 256] = np.where(np.isfinite(t), O[i0:i0 + 256, 2] + sign * t, np.nan)
    return res
