"""Haiku anim bench GPU side: one moderngl context (GL 4.3 compute) for skinning, the edge-stretch gate and the contact
sheet.

  skin     compute shader: rest + CS morph offsets (the clip's own morph weights) -> linear-blend skin, B poses at once
  stretch  compute shader: per (pose, edge) posed length / rest length; count > STRETCH_RATIO and worst, by atomics
           (patch_glb.edge_stretch's measure on the GPU; parity vs anim_core.edge_stretch_cpu in test_bench.py)
  draw     the posed SSBO drawn straight from the vertex shader (no re-upload), 4x MSAA, base colour + key light,
           plus the gaze ray (head joint along the head's beak axis) drawn on top in every 3D view
Sheet assembly after one readback: DEF tiles pasted and labels drawn on the CPU (a few small numpy slices and PIL text:
I/O, not per-pixel maths), JPEG encode.
"""
from __future__ import annotations

import io
import math
import time

import moderngl
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from anim_core import STRETCH_RATIO, Unit

BG = (196, 198, 202)
SHEET_W = 768
BIG = 192
FILM = 96
FILM_N = 8
SHEET_H = 2 * BIG + 3 * FILM
# views: (key, label, kind, elev, azimuth from the unit's front +Z toward its left +X)
BATTLE = (40.0, -60.0)                      # board.py BATTLE
PREVIEW = {"elevDeg": 13.7, "azimuthDeg": -68.0, "distanceWorld": 25.0, "yOffsetWorld": 1.95}   # board.py PREVIEW
ORBITS = {"battle": BATTLE, "front": (0.0, 0.0), "side": (0.0, 90.0), "top": (89.0, 0.0), "rear34": (20.0, 150.0),
          "q34": (15.0, 40.0)}           # q34 (round 5): a yawed front-left 3/4
ROW_A = [("def", "DEF"), ("sprite", "ours: sprite cam"), ("battle", "ours: battle cam"), ("preview", "ours: preview cam")]
ROW_B = [("front", "front (faces you)"), ("side", "side (unit's left)"), ("top", "top (front=down)"), ("rear34", "rear 3/4")]
FILM_ROWS = [("def", "DEF"), ("sprite", "sprite"), ("battle", "battle")]
# compact sheet (run3+): 512 wide, ~1/3 of the image tokens of the 768x672 sheet
C_W, C_BIG, C_FILM_MAX = 512, 128, 64
C_ROW_A = [("def", "DEF"), ("sprite", "ours sprite cam"), ("side", "side (unit's L)"), ("top", "top (front=down)")]
C_ROW_B = [("defhead", "DEF head"), ("spritehead", "our head"), ("front", "front + joints"), ("battle", "battle cam")]
VIEW_MAX = 8         # frames in one free-camera strip
VIEW_MODES = ("shaded", "wire", "normals", "heat", "skeleton")
MAX_CORR = 12        # corrective shapes (rig.MAX_CORRECTIVES)
MAX_J = 64           # joint buffer headroom for rig ops (new joints)
C_FILM = [("def", "DEF"), ("sprite", "ours"), ("side", "side")]
HEAD_BOX = 0.42      # head crop = this fraction of the sprite box, centred on our ORIGINAL head (fixed per frame)

SKIN_CS = """
#version 430
layout(local_size_x=128) in;
layout(std430, binding=0) readonly buffer RP { vec4 rp[]; };
layout(std430, binding=1) readonly buffer RN { vec4 rn[]; };
layout(std430, binding=2) readonly buffer JN { ivec4 jn[]; };
layout(std430, binding=3) readonly buffer WT { vec4 wt[]; };
layout(std430, binding=4) readonly buffer MD { vec4 md[]; };
layout(std430, binding=5) readonly buffer JMB { mat4 jm[]; };
layout(std430, binding=6) readonly buffer MWB { float mw[]; };
layout(std430, binding=7) writeonly buffer OP { vec4 op[]; };
layout(std430, binding=8) writeonly buffer ON { vec4 on[]; };
uniform int N; uniform int M; uniform int J;
void main() {
  int v = int(gl_GlobalInvocationID.x); int b = int(gl_GlobalInvocationID.y);
  if (v >= N) return;
  vec3 p = rp[v].xyz;
  for (int m = 0; m < M; m++) { float w = mw[b * M + m]; if (w != 0.0) p += w * md[m * N + v].xyz; }
  ivec4 j = jn[v]; vec4 w = wt[v]; int o = b * J;
  mat4 S = w.x * jm[o + j.x] + w.y * jm[o + j.y] + w.z * jm[o + j.z] + w.w * jm[o + j.w];
  op[b * N + v] = vec4((S * vec4(p, 1.0)).xyz, 1.0);
  on[b * N + v] = vec4(normalize(mat3(S) * rn[v].xyz), 0.0);
}
"""

EDGE_CS = """
#version 430
layout(local_size_x=256) in;
layout(std430, binding=7) readonly buffer OP { vec4 op[]; };
layout(std430, binding=9) readonly buffer ED { ivec2 ed[]; };
layout(std430, binding=10) readonly buffer RL { float rl[]; };
layout(std430, binding=11) buffer RES { uint res[]; };
layout(std430, binding=13) buffer EMX { uint emx[]; };
uniform int N; uniform int E; uniform float ratio; uniform int b0;
void main() {
  int e = int(gl_GlobalInvocationID.x); int b = b0 + int(gl_GlobalInvocationID.y);
  if (e >= E) return;
  ivec2 k = ed[e];
  float r = length(op[b * N + k.x].xyz - op[b * N + k.y].xyz) / rl[e];
  if (r > ratio) atomicAdd(res[2 * b], 1u);
  atomicMax(res[2 * b + 1], floatBitsToUint(r));
  atomicMax(emx[e], floatBitsToUint(r));   // per-edge max over the dispatched poses (the defect report)
}
"""

MESH_VS = """
#version 430
layout(std430, binding=7) readonly buffer OP { vec4 op[]; };
layout(std430, binding=8) readonly buffer ON { vec4 on[]; };
layout(std430, binding=12) readonly buffer UV { vec2 uv[]; };
layout(std430, binding=14) readonly buffer FL { float fl[]; };
layout(std430, binding=15) readonly buffer HT { float ht[]; };
uniform int base; uniform mat4 mvp; uniform float tint; uniform int hbase; uniform int mode; uniform float zbias;
out vec2 vuv; out vec3 vn; out float vfl; out vec3 vw; out float vh;
void main() {
  int i = base + gl_VertexID;
  vuv = uv[gl_VertexID]; vn = on[i].xyz; vfl = fl[gl_VertexID] * tint; vw = op[i].xyz;
  vh = mode == 3 ? ht[hbase + gl_VertexID] : 0.0;
  gl_Position = mvp * vec4(op[i].xyz, 1.0);
  gl_Position.z -= zbias * gl_Position.w;
}
"""
MESH_FS = """
#version 430
in vec2 vuv; in vec3 vn; in float vfl; in vec3 vw; in float vh; out vec4 frag;
uniform sampler2D tex; uniform vec3 L; uniform vec4 factor; uniform int mode; uniform vec3 flat_col; uniform mat3 vrot;
void main() {
  if (mode == 1) { frag = vec4(flat_col, 1.0); return; }
  vec3 n = normalize(vn); if (!gl_FrontFacing) n = -n;
  float d = max(dot(n, L), 0.0);
  if (mode == 2) {             // normals (view space) darkened where the face normal leaves the smooth normal (creases)
    vec3 fnm = normalize(cross(dFdx(vw), dFdy(vw)));
    if (dot(fnm, n) < 0.0) fnm = -fnm;
    float crease = clamp((1.0 - dot(fnm, n)) * 2.5, 0.0, 1.0);
    vec3 vn2 = vrot * n;
    frag = vec4((vn2 * 0.5 + 0.5) * (1.0 - 0.85 * crease), 1.0); return;
  }
  if (mode == 3) {             // stretch heat: grey = rest length, red = stretched (2x full), blue = squashed (0.5x full)
    float h = clamp(vh, -1.0, 1.0);
    vec3 g = vec3(0.72) * (0.5 + 0.5 * d);
    vec3 c = h > 0.0 ? mix(g, vec3(1.0, 0.1, 0.05), h) : mix(g, vec3(0.1, 0.3, 1.0), -h);
    frag = vec4(c, 1.0); return;
  }
  vec3 c = texture(tex, vuv).rgb * factor.rgb;
  c = c * (0.42 + 0.68 * d);
  frag = vec4(mix(c, vec3(1.0, 0.05, 0.05), clamp(vfl, 0.0, 1.0) * 0.9), 1.0);
}
"""
RAY_VS = """
#version 430
in vec3 pos; uniform mat4 mvp;
void main() { gl_Position = mvp * vec4(pos, 1.0); }
"""
RAY_GS = """
#version 430
layout(lines) in; layout(triangle_strip, max_vertices=4) out;
uniform vec2 vp; uniform float wpx;
void main() {
  vec4 a = gl_in[0].gl_Position, b = gl_in[1].gl_Position;
  vec2 sa = a.xy / a.w, sb = b.xy / b.w;
  vec2 d = (sb - sa) * vp; float l = length(d); d = l > 1e-6 ? d / l : vec2(1.0, 0.0);
  vec2 n = vec2(-d.y, d.x) * wpx / vp;
  gl_Position = vec4(sa + n, 0.0, 1.0); EmitVertex();
  gl_Position = vec4(sa - n, 0.0, 1.0); EmitVertex();
  gl_Position = vec4(sb + n, 0.0, 1.0); EmitVertex();
  gl_Position = vec4(sb - n, 0.0, 1.0); EmitVertex();
  EndPrimitive();
}
"""
PT_VS = """
#version 430
in vec4 pos; uniform mat4 mvp; uniform float ps; out float vnew;
void main() { gl_Position = mvp * vec4(pos.xyz, 1.0); gl_PointSize = ps; vnew = pos.w; }
"""
PT_FS = """
#version 430
in float vnew; out vec4 frag;
void main() {
  vec2 d = gl_PointCoord - vec2(0.5); if (dot(d, d) > 0.25) discard;
  frag = vec4(mix(vec3(1.0, 0.92, 0.1), vec3(0.0, 0.95, 1.0), vnew), 1.0);
}
"""
RAY_FS = """
#version 430
out vec4 frag; uniform vec3 col;
void main() { frag = vec4(col, 1.0); }
"""


def _norm(v):
    v = np.asarray(v, np.float64)
    return v / np.linalg.norm(v)


def orbit_dirs(elev_deg: float, az_deg: float) -> dict:
    """board.orbit_dirs: camera axes looking at the unit from azimuth az (front +Z toward left +X) and elevation."""
    a, e = math.radians(az_deg), math.radians(elev_deg)
    front, left, up = np.array([0, 0, 1.0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    to_cam = (front * math.cos(a) + left * math.sin(a)) * math.cos(e) + up * math.sin(e)
    fwd = -_norm(to_cam)
    right = _norm(np.cross(fwd, up))
    return {"to_cam": _norm(to_cam), "fwd": fwd, "right": right, "up": np.cross(right, fwd)}


class Cam:
    """A view as screen coordinates (sx right, sy down) of world points, ortho (affine) or perspective."""

    def __init__(self, kind, right, up, fwd, scale=1.0, cx=0.0, cy=0.0, eye=None):
        self.kind, self.right, self.up, self.fwd = kind, np.asarray(right, float), np.asarray(up, float), np.asarray(fwd, float)
        self.scale, self.cx, self.cy = scale, cx, cy
        self.eye = None if eye is None else np.asarray(eye, float)

    def screen(self, P):
        P = np.asarray(P, np.float64)
        if self.kind == "ortho":
            return np.stack([self.cx + self.scale * (P @ self.right), self.cy - self.scale * (P @ self.up)], -1)
        Q = P - self.eye
        z = np.maximum(Q @ self.fwd, 1e-6)
        return np.stack([(Q @ self.right) / z, -(Q @ self.up) / z], -1)

    def matrix(self, box, centre, radius) -> np.ndarray:
        """4x4 clip matrix mapping the square screen box (x0, y0, s) onto NDC."""
        x0, y0, s = box
        k = 2.0 / s
        M = np.zeros((4, 4))
        if self.kind == "ortho":
            M[0, :3] = k * self.scale * self.right; M[0, 3] = k * (self.cx - x0) - 1
            M[1, :3] = k * self.scale * self.up;    M[1, 3] = 1 - k * (self.cy - y0)
            M[2, :3] = self.fwd / radius;           M[2, 3] = -(centre @ self.fwd) / radius
            M[3, 3] = 1
            return M
        n = max(1e-3, float((centre - self.eye) @ self.fwd) - radius)
        f = float((centre - self.eye) @ self.fwd) + radius
        V = np.eye(4)
        V[0, :3], V[1, :3], V[2, :3] = self.right, self.up, self.fwd
        V[:3, 3] = -V[:3, :3] @ self.eye
        Pm = np.zeros((4, 4))
        Pm[0, 0], Pm[0, 2] = k, -(k * x0 + 1)
        Pm[1, 1], Pm[1, 2] = k, 1 + k * y0
        Pm[2, 2], Pm[2, 3] = (f + n) / (f - n), -2 * f * n / (f - n)
        Pm[3, 2] = 1
        return Pm @ V


def square_box(xy: np.ndarray, pad: float, extra=None) -> tuple[float, float, float]:
    lo, hi = xy.reshape(-1, 2).min(0), xy.reshape(-1, 2).max(0)
    if extra is not None:
        lo, hi = np.minimum(lo, extra[:2]), np.maximum(hi, extra[2:])
    c, s = (lo + hi) / 2, float((hi - lo).max()) * (1 + 2 * pad)
    return float(c[0] - s / 2), float(c[1] - s / 2), s


class DefFrame:
    """board.DefFrame without board's torch import: one DEF PNG kept as its opaque bbox."""

    def __init__(self, path: str, cam: dict):
        im = np.asarray(Image.open(path).convert("RGBA"))
        if im.shape[1] != cam["W"] or im.shape[0] != cam["H"]:
            raise SystemExit(f"DEF frame {path} is {im.shape[1]}x{im.shape[0]}, the sprite camera is {cam['W']}x{cam['H']}")
        ys, xs = np.nonzero(im[..., 3] > 0)
        self.bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else None
        self.data = im[self.bbox[1]:self.bbox[3], self.bbox[0]:self.bbox[2]].copy() if self.bbox else np.zeros((0, 0, 4), np.uint8)

    def crop(self, x0: int, y0: int, w: int, h: int) -> np.ndarray:
        out = np.zeros((h, w, 4), np.uint8)
        if not self.bbox:
            return out
        bx0, by0 = x0 - self.bbox[0], y0 - self.bbox[1]
        H, W = self.data.shape[:2]
        sx0, sy0, sx1, sy1 = max(0, bx0), max(0, by0), min(W, bx0 + w), min(H, by0 + h)
        if sx1 > sx0 and sy1 > sy0:
            out[sy0 - by0:sy1 - by0, sx0 - bx0:sx1 - bx0] = self.data[sy0:sy1, sx0:sx1]
        return out


def def_head_xy(path: str):
    """DEF head locator for the head crop (no keypoints exist for every unit): the saturated yellow cluster (beak)
    with the most pale head feathers around it; None if no yellow cluster. Canvas pixels (x, y). Heuristic, tuned on
    h3_roc (2026-10-07): lands on the beak in Move/Attack/Hitted, on the neck just below the head in Idle."""
    from scipy import ndimage
    im = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255
    rgb, a = im[..., :3], im[..., 3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = (mx - mn) / (mx + 1e-6)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    yellow = (a > 0.5) & (sat > 0.45) & (mx > 0.55) & (r >= g) & (g > b + 0.1) & (g > 0.45 * r)
    near = ndimage.uniform_filter(((a > 0.5) & (mx > 0.62) & (sat < 0.35)).astype(np.float32), 25)
    lab, n = ndimage.label(yellow)
    best = None
    for k in range(1, n + 1):
        m = lab == k
        if m.sum() < 10:
            continue
        sc = float(near[m].mean())
        if best is None or sc > best[0]:
            cy, cx = ndimage.center_of_mass(m)
            best = (sc, float(cx), float(cy))
    return None if best is None else (best[1], best[2])


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover
        return ImageFont.load_default()


class AnimGL:
    def __init__(self, unit: Unit, max_b: int = 96):
        t0 = time.perf_counter()
        self.u = unit
        s = unit.scene
        self.ctx = moderngl.create_standalone_context(require=430)
        ctx = self.ctx
        self.N, self.M, self.J = len(s.P), s.morphs.shape[0], len(s.joints)
        self.M0 = self.M
        unit.n_joints0 = getattr(unit, "n_joints0", len(s.joints))
        self.max_b = max_b
        f4 = lambda a: np.ascontiguousarray(a, np.float32).tobytes()  # noqa: E731
        pad4 = lambda a, w: np.c_[a, np.full((len(a), 1), w)]          # noqa: E731
        self.b_rp = ctx.buffer(f4(pad4(s.P, 1.0)))
        self.b_rn = ctx.buffer(f4(pad4(s.N, 0.0)))
        self.b_jn = ctx.buffer(np.ascontiguousarray(s.J, np.int32).tobytes())
        self.b_wt = ctx.buffer(f4(s.W))
        md = np.zeros((max(self.M, 1), self.N, 4), np.float32)
        if self.M:
            md[..., :3] = s.morphs
        self.b_md = ctx.buffer(reserve=(max(self.M, 1) + MAX_CORR) * self.N * 16)    # + room for corrective shapes
        self.b_md.write(md.tobytes())
        del md
        self.b_jm = ctx.buffer(reserve=max_b * MAX_J * 64)
        self.b_mw = ctx.buffer(reserve=max_b * (max(self.M, 1) + MAX_CORR) * 4)
        self.b_op = ctx.buffer(reserve=max_b * self.N * 16)
        self.b_on = ctx.buffer(reserve=max_b * self.N * 16)
        self.b_ed = ctx.buffer(np.ascontiguousarray(unit.edges, np.int32).tobytes())
        self.b_rl = ctx.buffer(f4(unit.rest_len))
        self.b_res = ctx.buffer(reserve=max_b * 8)
        self.b_uv = ctx.buffer(f4(s.UV))
        self.E = len(unit.edges)
        self.b_emx = ctx.buffer(reserve=self.E * 4)
        self.b_fl = ctx.buffer(np.zeros(self.N, np.float32).tobytes())
        self._fl = np.zeros(self.N, np.float32)
        self.b_ht = ctx.buffer(reserve=VIEW_MAX * self.N * 4)
        self._morphs_ref = s.morphs
        for i, b in enumerate([self.b_rp, self.b_rn, self.b_jn, self.b_wt, self.b_md, self.b_jm, self.b_mw, self.b_op,
                               self.b_on, self.b_ed, self.b_rl, self.b_res, self.b_uv, self.b_emx, self.b_fl, self.b_ht]):
            b.bind_to_storage_buffer(i)
        self.cs_skin = ctx.compute_shader(SKIN_CS)
        self.cs_edge = ctx.compute_shader(EDGE_CS)
        self.cs_skin["N"], self.cs_skin["M"], self.cs_skin["J"] = self.N, self.M, self.J
        self.cs_edge["N"], self.cs_edge["E"], self.cs_edge["ratio"] = self.N, self.E, float(STRETCH_RATIO)
        self.p_mesh = ctx.program(vertex_shader=MESH_VS, fragment_shader=MESH_FS)
        self.ibo = ctx.buffer(np.ascontiguousarray(s.F, np.int32).tobytes())
        self.vao = ctx.vertex_array(self.p_mesh, [], index_buffer=self.ibo, index_element_size=4)
        self.vao.vertices = len(s.F) * 3
        tex = (s.texture_rgba(1024) * 255).astype(np.uint8)
        self.tex = ctx.texture((tex.shape[1], tex.shape[0]), 4, tex.tobytes())
        self.tex.build_mipmaps()
        self.tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        self.p_mesh["tex"] = 0
        self.p_mesh["factor"] = tuple(float(x) for x in s.base_color_factor)
        self.p_ray = ctx.program(vertex_shader=RAY_VS, geometry_shader=RAY_GS, fragment_shader=RAY_FS)
        self.b_ray = ctx.buffer(reserve=4 * 3 * 4)
        self.vao_ray = ctx.vertex_array(self.p_ray, [(self.b_ray, "3f", "pos")])
        self.p_pt = ctx.program(vertex_shader=PT_VS, fragment_shader=PT_FS)
        self.b_pt = ctx.buffer(reserve=MAX_J * 16)
        self.vao_pt = ctx.vertex_array(self.p_pt, [(self.b_pt, "4f", "pos")])
        self.b_bones = ctx.buffer(reserve=MAX_J * 2 * 12)
        self.vao_bones = ctx.vertex_array(self.p_ray, [(self.b_bones, "3f", "pos")])
        ctx.enable(moderngl.PROGRAM_POINT_SIZE)
        self.p_mesh["tint"] = 1.0
        self.p_mesh["mode"] = 0
        self.p_mesh["hbase"] = 0
        self.p_mesh["zbias"] = 0.0
        W, H = SHEET_W, SHEET_H
        self.msaa = ctx.framebuffer(ctx.renderbuffer((W, H), 4, samples=4), ctx.depth_renderbuffer((W, H), samples=4))
        self.resolve = ctx.framebuffer(ctx.renderbuffer((W, H), 4))
        self.font = _font(11)
        self.views = {}              # clip -> per view (cam, box, matrix)
        self.head_boxes, self.defs, self.cycle, self.c_tiles, self.centre_radius = {}, {}, {}, {}, {}
        self.def_head_boxes = {}
        self.def_tiles = {}          # clip -> {size: [uint8 tiles]}
        self.thr = {}                # clip -> per-edge new-defect threshold (pristine rig, original clip)
        self.show_defects = True     # round 5: False = no red tint / worst-stretch close-up on the sheet (words only)
        self.init_ms = (time.perf_counter() - t0) * 1000

    # ---------------------------------------------------------------- compute
    def skin(self, Jm: np.ndarray, mw: np.ndarray) -> None:
        B = len(Jm)
        if B > self.max_b:
            raise ValueError(f"batch {B} > {self.max_b}")
        self.b_jm.write(np.ascontiguousarray(Jm.transpose(0, 1, 3, 2), np.float32).tobytes())
        if self.M:
            self.b_mw.write(np.ascontiguousarray(mw, np.float32).tobytes())
        self.cs_skin.run((self.N + 127) // 128, B, 1)
        self.ctx.memory_barrier()

    def upload_rig(self) -> None:
        """Re-upload what a rig/mesh replay changed (rig.RigEditor.apply): rest P/N, joints/weights, morphs (only if
        replaced), edge rest lengths, the joint count."""
        s, u = self.u.scene, self.u
        J = len(s.joints)
        if J > MAX_J:
            raise ValueError(f"{J} joints > {MAX_J}")
        f4 = lambda a: np.ascontiguousarray(a, np.float32).tobytes()  # noqa: E731
        self.b_rp.write(f4(np.c_[s.P, np.ones(len(s.P))]))
        self.b_rn.write(f4(np.c_[s.N, np.zeros(len(s.N))]))
        self.b_jn.write(np.ascontiguousarray(s.J, np.int32).tobytes())
        self.b_wt.write(f4(s.W))
        if s.morphs is not self._morphs_ref and s.morphs.shape[0]:
            M = s.morphs.shape[0]
            if M > self.M0 + MAX_CORR:
                raise ValueError("too many corrective shapes")
            md = np.zeros((M, self.N, 4), np.float32)
            md[..., :3] = s.morphs
            self.b_md.write(md.tobytes())
            self._morphs_ref = s.morphs
            self.M = M
            self.cs_skin["M"] = M
        self.b_rl.write(f4(u.rest_len))
        self.J = J
        self.cs_skin["J"] = J

    def edge_max(self, b0: int, nb: int) -> np.ndarray:
        """Per-edge max stretch ratio over poses b0..b0+nb-1 of the last skin dispatch."""
        self.b_emx.write(np.zeros(self.E, np.uint32).tobytes())
        self.b_res.write(np.zeros(2 * (b0 + nb), np.uint32).tobytes())
        self.cs_edge["b0"] = b0
        self.cs_edge.run((self.E + 255) // 256, nb, 1)
        self.ctx.memory_barrier()
        self.cs_edge["b0"] = 0
        return np.frombuffer(self.b_emx.read(), np.uint32).view(np.float32).astype(np.float64)

    def defects(self, clip: str, emax: np.ndarray, Jm: np.ndarray, mw: np.ndarray, g0: int) -> dict:
        """New mesh defects vs the original clip: edges whose max stretch over the clip's key grid passes
        max(STRETCH_RATIO, 1.05 x that edge's own original max). Uploads the red tint flags. The worst one is located
        (pose, posed position and normal) on the CPU from its two vertices."""
        u, s = self.u, self.u.scene
        thr = self.thr[clip]
        bad = emax > thr
        fl = np.zeros(self.N, np.float32)
        out = {"open": bool(bad.any()), "edges": int(bad.sum())}
        if bad.any():
            sev = np.where(bad, emax / thr, 0.0)
            e = int(np.argmax(sev))
            E = u.edges
            vs = np.unique(E[bad])
            ring = np.isin(E[:, 0], vs) | np.isin(E[:, 1], vs)
            fl[np.unique(E[ring])] = 0.55
            fl[vs] = 1.0
            i, j = (int(x) for x in E[e])
            P2 = []
            for v in (i, j):
                p = np.broadcast_to(s.P[v], (len(Jm), 3)).copy()
                if self.M:
                    p += mw @ s.morphs[:, v, :].astype(np.float64)
                M = np.einsum("k,bkij->bij", s.W[v], Jm[:, s.J[v]])
                P2.append(np.einsum("bij,bj->bi", M[:, :3, :3], p) + M[:, :3, 3])
            r = np.linalg.norm(P2[0] - P2[1], axis=1) / u.rest_len[e]
            k = g0 + int(np.argmax(r[g0:]))
            Mi = np.einsum("k,kij->ij", s.W[i], Jm[k][s.J[i]])
            n = Mi[:3, :3] @ (s.N[i] + s.N[j])
            out.update(edge=e, verts=[i, j], severity=round(float(sev[e]), 3), pose=k,
                       world=((P2[0][k] + P2[1][k]) / 2).tolist(), normal=(n / max(np.linalg.norm(n), 1e-9)).tolist(),
                       rest=((s.P[i] + s.P[j]) / 2).tolist(), restNormal=(s.N[i] + s.N[j]).tolist())
        if not np.array_equal(fl, self._fl):
            self.b_fl.write(fl.tobytes())
            self._fl = fl
        return out

    def stretch(self, B: int) -> tuple[np.ndarray, np.ndarray]:
        self.b_res.write(np.zeros(2 * B, np.uint32).tobytes())
        self.cs_edge.run((self.E + 255) // 256, B, 1)
        self.ctx.memory_barrier()
        r = np.frombuffer(self.b_res.read(size=8 * B), np.uint32).reshape(B, 2)
        return r[:, 0].astype(np.int64), r[:, 1].copy().view(np.float32).astype(np.float64)

    def read_posed(self, B: int) -> np.ndarray:
        return np.frombuffer(self.b_op.read(size=B * self.N * 16), np.float32).reshape(B, self.N, 4)[..., :3].astype(np.float64)

    # ---------------------------------------------------------------- framing (once per clip, from the original clip)
    def clip_defect_edges(self, clip: str, edits: list) -> int:
        """New-defect edge count on a whole clip's key grid (current rig + edits) vs the pristine thresholds. GPU,
        a few ms per clip: used after mesh/rig ops, which touch every clip, so a red spot elsewhere is not hidden."""
        u = self.u
        g = np.asarray(u.clips[clip]["grid"], float)
        _, Jg, mwg = u.pose(clip, g, edits)
        n = 0
        emax = np.zeros(self.E, np.float32)
        for i in range(0, len(g), self.max_b):
            self.skin(Jg[i:i + self.max_b], mwg[i:i + self.max_b])
            emax = np.maximum(emax, self.edge_max(0, len(Jg[i:i + self.max_b])))
        self.last_defect_mask = emax > self.thr[clip]
        n = int(self.last_defect_mask.sum())
        return n

    def setup_clip(self, clip: str) -> None:
        if clip in self.views:
            return
        u = self.u
        c = u.clips[clip]
        times = np.unique(np.r_[c["grid"], c["times"]])
        G, Jm, mw = u.pose(clip, times)
        Pall = []
        for i in range(0, len(times), self.max_b):
            self.skin(Jm[i:i + self.max_b], mw[i:i + self.max_b])
            Pall.append(self.read_posed(len(Jm[i:i + self.max_b])))
        P = np.concatenate(Pall)
        hp, gd = u.gaze(G)
        tips = hp + gd * u.gaze_len * 2.5
        pts = np.concatenate([P.reshape(-1, 3)[::7], hp, tips])
        centre = (pts.min(0) + pts.max(0)) / 2
        radius = float(np.linalg.norm(pts.max(0) - pts.min(0))) * 0.75 + 1e-3
        views = {}
        self.centre_radius[clip] = (centre, radius)
        sc = u.spritecam
        spr = Cam("ortho", sc["right"], sc["up"], sc["fwd"], sc["scale"], sc["cx"], sc["cy"])
        # sprite box: union of the clip's DEF opaque boxes and our projection (the board's per clip box)
        defs = [DefFrame(p, sc) for p in c["frames"]]
        db = [d.bbox for d in defs if d.bbox]
        extra = np.array([min(b[0] for b in db), min(b[1] for b in db), max(b[2] for b in db), max(b[3] for b in db)], float) if db else None
        box = square_box(spr.screen(pts), 0.04, extra)
        views["sprite"] = (spr, box, spr.matrix(box, centre, radius))
        for key, (el, az) in ORBITS.items():
            d = orbit_dirs(el, az)
            cam = Cam("ortho", d["right"], d["up"], d["fwd"])
            box = square_box(cam.screen(pts), 0.06)
            views[key] = (cam, box, cam.matrix(box, centre, radius))
        d = orbit_dirs(PREVIEW["elevDeg"], PREVIEW["azimuthDeg"])
        k_world = 2.0 / max(u.H, 1e-6)          # board's no-framing-row rule: unit height normalised to 2.0 world
        feet = float(P[0, :, 1].min())
        target = np.array([0.0, feet + PREVIEW["yOffsetWorld"] / k_world, 0.0])
        eye = target + d["to_cam"] * PREVIEW["distanceWorld"] / k_world
        cam = Cam("persp", d["right"], d["up"], d["fwd"], eye=eye)
        box = square_box(cam.screen(pts), 0.05)
        views["preview"] = (cam, box, cam.matrix(box, centre, radius))
        self.views[clip] = views
        g = np.asarray(c["grid"], float)
        _, Jg, mwg = u.pose(clip, g)
        self.skin(Jg, mwg)
        base = self.edge_max(0, len(g))
        self.thr[clip] = np.where(base > STRETCH_RATIO, base * 1.05, STRETCH_RATIO)
        # compact sheet: per DEF frame head boxes (sprite cam, original pose) and the loop-cycle film keys
        ss_ = views["sprite"][1][2]
        Gf, _, _ = u.pose(clip, c["times"])
        hpf, _ = u.gaze(Gf)
        hs = ss_ * HEAD_BOX
        self.head_boxes[clip] = [(float(x - hs / 2), float(y - hs * 0.55), hs) for x, y in spr.screen(hpf)]
        dh = [def_head_xy(pth) for pth in c["frames"]]
        self.def_head_boxes[clip] = [hb if d is None else (d[0] - hs / 2, d[1] - hs / 2, hs)
                                     for hb, d in zip(self.head_boxes[clip], dh)]
        self.defs[clip] = defs
        g = np.asarray(c["grid"], float)
        loop = c["isLoop"] and c["period"] > 0
        lo, hi = c["start"], (c["start"] + c["period"]) if loop else c["end"]
        keys = [float(t) for t in g if lo - 1e-5 <= t <= hi + 1e-5]
        fmap = []
        for t in keys:
            i = int(round((t - c["start"]) / c["step"]))
            if loop and abs(t - hi) < 1e-5:
                fmap.append(("wrap", 0))
            elif 0 <= i < c["n"] and abs(u.frame_time(clip, i) - t) < 0.25 * c["step"]:
                fmap.append(("def", i))
            else:
                fmap.append(("tk", None))
        # film rows: the DEF frames (+ the wrap) and at most ONE transition key (the last, toward the loop wrap); a clip
        # whose grid has many in-between keys would otherwise shrink the film tiles to unreadable stamps
        tks = [i for i, (k, _) in enumerate(fmap) if k == "tk"]
        keep = [i for i, (k, _) in enumerate(fmap) if k != "tk"] + tks[-1:]
        keep.sort()
        keys, fmap = [keys[i] for i in keep], [fmap[i] for i in keep]
        self.cycle[clip] = (keys, fmap)
        # DEF tiles at the sprite box, over BG
        x0, y0, s = views["sprite"][1]
        tiles = {BIG: [], FILM: []}
        for df in defs:
            ix0, iy0, isz = int(math.floor(x0)), int(math.floor(y0)), int(math.ceil(s))
            rgba = df.crop(ix0, iy0, isz, isz).astype(np.float32) / 255.0
            rgb = rgba[..., :3] * rgba[..., 3:4] + (1 - rgba[..., 3:4]) * (np.array(BG, np.float32) / 255.0)
            im = Image.fromarray((rgb * 255 + 0.5).astype(np.uint8))
            for size in tiles:
                tiles[size].append(np.asarray(im.resize((size, size), Image.BILINEAR)))
        self.def_tiles[clip] = tiles

    # ---------------------------------------------------------------- drawing
    def _draw(self, clip, view, b, rect, ray, M=None):
        x, y, w, h = rect
        cam, box, M0 = self.views[clip][view]
        M = M0 if M is None else M
        self.msaa.viewport = (x, SHEET_H - y - h, w, h)
        self.p_mesh["base"] = b * self.N
        self.p_mesh["mvp"].write(np.ascontiguousarray(M.T, np.float32).tobytes())
        L = _norm(-0.55 * cam.fwd + 0.75 * np.array([0, 1.0, 0]) - 0.25 * cam.right)
        self.p_mesh["L"] = tuple(float(v) for v in L)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.tex.use(0)
        self.vao.render(moderngl.TRIANGLES)
        if ray is not None:
            self.ctx.disable(moderngl.DEPTH_TEST)
            self.b_ray.write(np.ascontiguousarray(ray, np.float32).tobytes())
            self.p_ray["mvp"].write(np.ascontiguousarray(M.T, np.float32).tobytes())
            self.p_ray["vp"] = (float(w), float(h))
            self.p_ray["wpx"] = 1.6 if w > 72 else 1.1
            self.p_ray["col"] = (1.0, 0.55, 0.0)
            self.vao_ray.render(moderngl.LINES, vertices=2)

    def sheet(self, clip: str, focus: float, film_frames: list[int], edits: list[dict], extra_times=()) -> dict:
        """Render the contact sheet for clip at DEF frame `focus` with the given edit stack. Also skins `extra_times`
        (the gate grid) in the same dispatch and returns their stretch. Returns timings, jpeg bytes and gate data."""
        t0 = time.perf_counter()
        u = self.u
        self.setup_clip(clip)
        c = u.clips[clip]
        times = [u.frame_time(clip, focus)] + [u.frame_time(clip, f) for f in film_frames] + list(extra_times)
        G, Jm, mw = u.pose(clip, times, edits)
        hp, gd = u.gaze(G)
        rays = np.stack([hp, hp + gd * u.gaze_len * 2.5], 1)
        t1 = time.perf_counter()
        self.skin(Jm, mw)
        nf = 1 + len(film_frames)
        st = None
        if len(extra_times):
            cnt, worst = self.stretch(len(times))
            st = {"edgesOver2x": int(cnt[nf:].sum()), "worst": round(float(worst[nf:].max()), 3)}
        t2 = time.perf_counter()
        self.msaa.use()
        self.msaa.viewport = (0, 0, SHEET_W, SHEET_H)
        self.msaa.clear(BG[0] / 255, BG[1] / 255, BG[2] / 255, 1.0, depth=1.0)
        for col, (key, _) in enumerate(ROW_A):
            if key != "def":
                self._draw(clip, key, 0, (col * BIG, 0, BIG, BIG), rays[0])
        for col, (key, _) in enumerate(ROW_B):
            self._draw(clip, key, 0, (col * BIG, BIG, BIG, BIG), rays[0])
        for r, (key, _) in enumerate(FILM_ROWS):
            if key == "def":
                continue
            for k in range(len(film_frames)):
                self._draw(clip, key, 1 + k, (k * FILM, 2 * BIG + r * FILM, FILM, FILM), rays[1 + k])
        self.ctx.copy_framebuffer(self.resolve, self.msaa)
        img = np.frombuffer(self.resolve.read(components=3), np.uint8).reshape(SHEET_H, SHEET_W, 3)[::-1].copy()
        t3 = time.perf_counter()
        fi = int(round(focus))
        tiles = self.def_tiles[clip]
        img[0:BIG, 0:BIG] = tiles[BIG][fi]
        for k, f in enumerate(film_frames):
            img[2 * BIG:2 * BIG + FILM, k * FILM:(k + 1) * FILM] = tiles[FILM][f]
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im)
        for col, (key, lab) in enumerate(ROW_A):
            dr.text((col * BIG + 3, 2), f"{lab}" + (f" f{fi}" if key in ("def", "sprite") else ""), fill=(10, 10, 10), font=self.font)
        for col, (key, lab) in enumerate(ROW_B):
            dr.text((col * BIG + 3, BIG + 2), lab, fill=(10, 10, 10), font=self.font)
        for r, (key, lab) in enumerate(FILM_ROWS):
            for k, f in enumerate(film_frames):
                y = 2 * BIG + r * FILM
                dr.text((k * FILM + 3, y + 1), f"{lab} f{f}" if k == 0 else f"f{f}", fill=(10, 10, 10), font=self.font)
                if f == fi:
                    dr.rectangle((k * FILM, y, (k + 1) * FILM - 1, y + FILM - 1), outline=(230, 60, 20), width=2)
        for x in range(1, 4):
            dr.line((x * BIG, 0, x * BIG, 2 * BIG), fill=(150, 150, 150))
        dr.line((0, BIG, SHEET_W, BIG), fill=(150, 150, 150))
        dr.line((0, 2 * BIG, SHEET_W, 2 * BIG), fill=(150, 150, 150))
        dr.text((SHEET_W - 230, SHEET_H - 12), f"{clip} f{fi}/{c['n'] - 1}  orange ray = gaze", fill=(20, 20, 20), font=self.font)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        t4 = time.perf_counter()
        return {"jpeg": buf.getvalue(), "stretch": st,
                "ms": {"pose": round((t1 - t0) * 1000, 2), "gpuSkinGate": round((t2 - t1) * 1000, 2),
                       "draw": round((t3 - t2) * 1000, 2), "compose": round((t4 - t3) * 1000, 2),
                       "total": round((t4 - t0) * 1000, 2)}}

    def _def_tile(self, clip, f, size, box=None):
        key = (clip, f, size, box)
        t = self.c_tiles.get(key)
        if t is None:
            x0, y0, s = box if box else self.views[clip]["sprite"][1]
            ix0, iy0, isz = int(math.floor(x0)), int(math.floor(y0)), max(1, int(math.ceil(s)))
            rgba = self.defs[clip][f].crop(ix0, iy0, isz, isz).astype(np.float32) / 255.0
            rgb = rgba[..., :3] * rgba[..., 3:4] + (1 - rgba[..., 3:4]) * (np.array(BG, np.float32) / 255.0)
            t = np.asarray(Image.fromarray((rgb * 255 + 0.5).astype(np.uint8)).resize((size, size), Image.BILINEAR))
            self.c_tiles[key] = t
        return t

    def _closeup(self, d: dict, H: float):
        """Ortho camera looking at the worst defect along its posed normal, a box of 0.28 H around it."""
        n = _norm(d["normal"])
        fwd = -n
        up0 = np.array([0, 1.0, 0]) if abs(fwd[1]) < 0.9 else np.array([0, 0, 1.0])
        right = _norm(np.cross(fwd, up0))
        up = np.cross(right, fwd)
        cam = Cam("ortho", right, up, fwd)
        c = np.asarray(d["world"])
        sx, sy = cam.screen(c[None])[0]
        s = 0.28 * H
        return cam, cam.matrix((sx - s / 2, sy - s / 2, s), c, 0.35 * H)

    def _skeleton(self, clip, G, b, rect, M=None):
        """Joint dots (yellow; joints added by rig ops cyan) and parent-child lines, on top, in one tile."""
        u, s = self.u, self.u.scene
        x, y, w, h = rect
        M = self.views[clip]["front"][2] if M is None else M
        pos = G[b, s.joints, :3, 3]
        new = np.zeros(len(pos))
        new[u.n_joints0:] = 1.0
        jset = {nd: k for k, nd in enumerate(s.joints)}
        segs = [(pos[jset[s.parent[nd]]], pos[k]) for k, nd in enumerate(s.joints) if s.parent.get(nd) in jset]
        self.msaa.viewport = (x, SHEET_H - y - h, w, h)
        self.ctx.disable(moderngl.DEPTH_TEST)
        mvp = np.ascontiguousarray(M.T, np.float32).tobytes()
        if segs:
            self.b_bones.write(np.ascontiguousarray(np.array(segs).reshape(-1, 3), np.float32).tobytes())
            self.p_ray["mvp"].write(mvp)
            self.p_ray["vp"] = (float(w), float(h))
            self.p_ray["wpx"] = 0.6
            self.p_ray["col"] = (0.95, 0.95, 0.95)
            self.vao_bones.render(moderngl.LINES, vertices=2 * len(segs))
        self.b_pt.write(np.ascontiguousarray(np.c_[pos, new], np.float32).tobytes())
        self.p_pt["mvp"].write(mvp)
        self.p_pt["ps"] = 4.0
        self.vao_pt.render(moderngl.POINTS, vertices=len(pos))

    def sheet_compact(self, clip: str, focus: float, edits: list[dict], extra_times=()) -> dict:
        """512-wide sheet: row A DEF | ours sprite | side | top; row B DEF head | our head (same sprite camera, same
        crop) | front + joint dots | battle cam, or the WORST NEW STRETCH close-up when the mesh report is open; then
        ONE LOOP CYCLE as film rows (DEF, ours sprite, ours side). The clip's key grid is skinned in the same dispatch
        and its per-edge stretch is the mesh report (returned as "defect"); stretched faces are tinted red."""
        t0 = time.perf_counter()
        u = self.u
        self.setup_clip(clip)
        c = u.clips[clip]
        keys, fmap = self.cycle[clip]
        fi = int(round(focus))
        grid = [float(t) for t in c["grid"]]
        times = [u.frame_time(clip, focus)] + keys + grid
        G, Jm, mw = u.pose(clip, times, edits)
        hp, gd = u.gaze(G)
        rays = np.stack([hp, hp + gd * u.gaze_len * 2.5], 1)
        t1 = time.perf_counter()
        self.skin(Jm, mw)
        nf = 1 + len(keys)
        emax = self.edge_max(nf, len(grid))
        cnt, worst = (np.frombuffer(self.b_res.read(size=8 * len(times)), np.uint32).reshape(-1, 2)[nf:].T)
        st = {"edgesOver2x": int(cnt.astype(np.int64).sum()),
              "worst": round(float(worst.copy().view(np.float32).max()), 3)}
        defect = self.defects(clip, emax, Jm, mw, nf)
        if defect["open"]:
            defect["gridKey"] = defect["pose"] - nf
        t2 = time.perf_counter()
        B, fs = C_BIG, min(C_FILM_MAX, C_W // len(keys))
        body_h = 2 * B + len(C_FILM) * fs
        H = body_h + 13
        self.msaa.use()
        self.msaa.viewport = (0, 0, SHEET_W, SHEET_H)
        self.msaa.clear(BG[0] / 255, BG[1] / 255, BG[2] / 255, 1.0, depth=1.0)
        spr = self.views[clip]["sprite"]
        hb = self.head_boxes[clip][fi]
        show = self.show_defects and defect["open"]
        self.p_mesh["tint"] = 1.0 if self.show_defects else 0.0
        for col, (key, _) in enumerate(C_ROW_A):
            if key != "def":
                self._draw(clip, key, 0, (col * B, 0, B, B), rays[0])
        for col, (key, _) in enumerate(C_ROW_B):
            if key == "spritehead":
                self._draw(clip, "sprite", 0, (col * B, B, B, B), rays[0], M=spr[0].matrix(hb, *self.centre_radius[clip]))
            elif key == "battle" and show:
                cam, M = self._closeup(defect, u.H)
                self._draw(clip, "front", defect["pose"], (col * B, B, B, B), None, M=M)
            elif key != "defhead":
                self._draw(clip, key, 0, (col * B, B, B, B), rays[0])
                if key == "front":
                    self._skeleton(clip, G, 0, (col * B, B, B, B))
        for r, (key, _) in enumerate(C_FILM):
            if key == "def":
                continue
            for k in range(len(keys)):
                self._draw(clip, key, 1 + k, (k * fs, 2 * B + r * fs, fs, fs), rays[1 + k])
        self.p_mesh["tint"] = 1.0
        self.ctx.copy_framebuffer(self.resolve, self.msaa)
        full = np.frombuffer(self.resolve.read(components=3), np.uint8).reshape(SHEET_H, SHEET_W, 3)[::-1]
        img = np.empty((H, C_W, 3), np.uint8)
        img[:] = BG
        img[:body_h] = full[:body_h, :C_W]
        t3 = time.perf_counter()
        img[0:B, 0:B] = self._def_tile(clip, fi, B)
        img[B:2 * B, 0:B] = self._def_tile(clip, fi, B, self.def_head_boxes[clip][fi])
        for k, (kind, f) in enumerate(fmap):
            if kind != "tk":
                img[2 * B:2 * B + fs, k * fs:(k + 1) * fs] = self._def_tile(clip, f, fs)
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im)

        def T(xy, txt, col=(10, 10, 10)):
            w = dr.textlength(txt, font=self.font)
            dr.rectangle((xy[0] - 1, xy[1], xy[0] + w + 1, xy[1] + 11), fill=BG)
            dr.text(xy, txt, fill=col, font=self.font)
        for col, (key, lab) in enumerate(C_ROW_A):
            T((col * B + 3, 2), lab + (f" f{fi}" if key in ("def", "sprite") else ""))
        for col, (key, lab) in enumerate(C_ROW_B):
            if key == "battle" and show:
                cx, cy = col * B + B // 2, B + B // 2
                dr.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), outline=(255, 30, 30), width=2)
                T((col * B + 3, B + 2), "WORST NEW STRETCH", (170, 0, 0))
            else:
                T((col * B + 3, B + 2), lab)
        for r, (key, lab) in enumerate(C_FILM):
            y = 2 * B + r * fs
            for k, (kind, f) in enumerate(fmap):
                tag = {"def": f"f{f}", "tk": "tk", "wrap": "f0 loop"}[kind]
                T((k * fs + 2, y + 1), (f"{lab} " if k == 0 else "") + tag)
                if kind == "def" and f == fi:
                    dr.rectangle((k * fs, y, (k + 1) * fs - 1, y + fs - 1), outline=(230, 60, 20), width=2)
        # level guide in the side views: a dashed horizontal line through the hips (flight attitude is judged against it)
        Ms = self.views[clip]["side"][2]
        hi = u.names.index("Hips") if "Hips" in u.names else None
        if hi is not None:
            def level(b, x0, y0, w):
                q = Ms @ np.r_[G[b, hi, :3, 3], 1.0]
                yy = y0 + (1 - q[1] / q[3]) / 2 * w
                if y0 + 12 < yy < y0 + w - 2:
                    for xx in range(x0 + 2, x0 + w - 4, 8):
                        dr.line((xx, yy, xx + 4, yy), fill=(40, 110, 230), width=1)
            level(0, 2 * B, 0, B)
            ri = [k for k, _ in C_FILM].index("side")
            for k in range(len(keys)):
                level(1 + k, k * fs, 2 * B + ri * fs, fs)
        for x in range(1, 4):
            dr.line((x * B, 0, x * B, 2 * B), fill=(150, 150, 150))
        for y in (B, 2 * B):
            dr.line((0, y, C_W, y), fill=(150, 150, 150))
        foot = (f"{clip} f{fi}/{c['n'] - 1}; film = one loop; orange ray = our gaze; blue dashes = level; "
                + (("RED = new stretch" if defect["open"] else "mesh clean") if self.show_defects else "mesh: see the text"))
        dr.text((3, H - 12), foot, fill=(150, 0, 0) if show else (20, 20, 20), font=self.font)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        t4 = time.perf_counter()
        return {"jpeg": buf.getvalue(), "stretch": st, "defect": defect,
                "ms": {"pose": round((t1 - t0) * 1000, 2), "gpuSkinGate": round((t2 - t1) * 1000, 2),
                       "draw": round((t3 - t2) * 1000, 2), "compose": round((t4 - t3) * 1000, 2),
                       "total": round((t4 - t0) * 1000, 2)}}

    # ---------------------------------------------------------------- A/B try sheet and zoomed looks
    def _level(self, dr, clip, G, b, x0, y0, w):
        """Dashed blue level line through the hips in a side tile."""
        u = self.u
        if "Hips" not in u.names:
            return
        q = self.views[clip]["side"][2] @ np.r_[G[b, u.names.index("Hips"), :3, 3], 1.0]
        yy = y0 + (1 - q[1] / q[3]) / 2 * w
        if y0 + 12 < yy < y0 + w - 2:
            for xx in range(x0 + 2, x0 + w - 4, 8):
                dr.line((xx, yy, xx + 4, yy), fill=(40, 110, 230), width=1)

    def _label(self, dr, xy, txt, col=(10, 10, 10)):
        w = dr.textlength(txt, font=self.font)
        dr.rectangle((xy[0] - 1, xy[1], xy[0] + w + 1, xy[1] + 11), fill=BG)
        dr.text(xy, txt, fill=col, font=self.font)

    def _read(self, w, h):
        self.ctx.copy_framebuffer(self.resolve, self.msaa)
        full = np.frombuffer(self.resolve.read(components=3), np.uint8).reshape(SHEET_H, SHEET_W, 3)[::-1]
        return full[:h, :w].copy()

    def try_sheet(self, clip: str, focus: int, base: list, pa: list, pb: list) -> dict:
        """One small sheet for an A/B direction choice: columns DEF | NOW | A | B, rows sprite cam, side, top (128 px
        tiles, 512 x 397). No red tint here (the state line words the mesh for A and B)."""
        t0 = time.perf_counter()
        u = self.u
        self.setup_clip(clip)
        T = C_BIG
        t = [u.frame_time(clip, focus)]
        Gs, Js, Ms = [], [], []
        for ed in (base, base + pa, base + pb):
            G, Jm, mw = u.pose(clip, t, ed)
            Gs.append(G); Js.append(Jm); Ms.append(mw)
        G, Jm, mw = np.concatenate(Gs), np.concatenate(Js), np.concatenate(Ms)
        hp, gd = u.gaze(G)
        rays = np.stack([hp, hp + gd * u.gaze_len * 2.5], 1)
        self.skin(Jm, mw)
        self.msaa.use()
        self.msaa.viewport = (0, 0, SHEET_W, SHEET_H)
        self.msaa.clear(BG[0] / 255, BG[1] / 255, BG[2] / 255, 1.0, depth=1.0)
        self.p_mesh["tint"] = 0.0
        try:
            for b in range(3):
                for r, view in enumerate(("sprite", "side", "top")):
                    self._draw(clip, view, b, ((1 + b) * T, r * T, T, T), rays[b])
        finally:
            self.p_mesh["tint"] = 1.0
        H = 3 * T + 13
        img = np.empty((H, 4 * T, 3), np.uint8)
        img[:] = BG
        img[:3 * T] = self._read(4 * T, 3 * T)
        img[0:T, 0:T] = self._def_tile(clip, focus, T)
        img[T:2 * T, 0:T] = self._def_tile(clip, focus, T, self.def_head_boxes[clip][focus])
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im)
        for b in range(3):
            self._level(dr, clip, G, b, (1 + b) * T, T, T)
        self._label(dr, (3, 2), f"DEF f{focus}")
        self._label(dr, (3, T + 2), "DEF head")
        dr.text((4, 2 * T + 6), "A = the change as", fill=(10, 10, 10), font=self.font)
        dr.text((4, 2 * T + 20), "you wrote it;", fill=(10, 10, 10), font=self.font)
        dr.text((4, 2 * T + 34), "B = every angle", fill=(10, 10, 10), font=self.font)
        dr.text((4, 2 * T + 48), "flipped.", fill=(10, 10, 10), font=self.font)
        for b, lab in enumerate(("NOW", "A", "B")):
            for r, rl in enumerate(("sprite cam", "side", "top")):
                self._label(dr, ((1 + b) * T + 3, r * T + 2), f"{lab}  {rl}", (150, 0, 0) if lab != "NOW" else (10, 10, 10))
        for x in range(1, 4):
            dr.line((x * T, 0, x * T, 3 * T), fill=(150, 150, 150))
        for y in (T, 2 * T):
            dr.line((0, y, 4 * T, y), fill=(150, 150, 150))
        dr.text((3, H - 12), f"{clip} f{focus}: TRY - pick A, B or none; orange ray = gaze; blue dashes = level",
                fill=(20, 20, 20), font=self.font)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return {"jpeg": buf.getvalue(), "ms": {"total": round((time.perf_counter() - t0) * 1000, 2)}}

    # ---------------------------------------------------------------- round 5: candidates, judge panels, boards
    VIEW_NAMES = {"sprite": "sprite cam", "side": "side (faces left)", "top": "top (front=down)", "front": "front",
                  "battle": "battle cam", "preview": "preview cam", "q34": "3/4 front-left", "rear34": "rear 3/4"}

    def panel(self, clip: str, frame: int, edits: list, views=("sprite", "side", "q34"), T: int = 160,
              film=None, ft: int = 0) -> np.ndarray:
        """One version of the unit as an image: the given views at `frame` (T px each) and, below, an optional film
        row of `film` frames from the sprite camera (ft px each). No red tint, no DEF, no labels (the caller adds
        them). Uses the CURRENT rig (callers swap rigs around it for an original-vs-now comparison)."""
        u = self.u
        self.setup_clip(clip)
        film = list(film or [])
        times = [u.frame_time(clip, frame)] + [u.frame_time(clip, f) for f in film]
        G, Jm, mw = u.pose(clip, times, edits)
        hp, gd = u.gaze(G)
        rays = np.stack([hp, hp + gd * u.gaze_len * 2.5], 1)
        self.skin(Jm, mw)
        self.msaa.use()
        self.msaa.viewport = (0, 0, SHEET_W, SHEET_H)
        self.msaa.clear(BG[0] / 255, BG[1] / 255, BG[2] / 255, 1.0, depth=1.0)
        self.p_mesh["tint"] = 0.0
        try:
            for i, v in enumerate(views):
                self._draw(clip, v, 0, (i * T, 0, T, T), rays[0])
            for k in range(len(film)):
                self._draw(clip, "sprite", 1 + k, (k * ft, T, ft, ft), rays[1 + k])
        finally:
            self.p_mesh["tint"] = 1.0
        W = max(len(views) * T, len(film) * ft)
        img = self._read(W, T + (ft if film else 0))
        if film and len(views) * T < W:
            img[:T, len(views) * T:] = BG
        return img

    def variants_sheet(self, clip: str, focus: int, base: list, variants: list[list], labels: list[str],
                       rows=("sprite", "side", "q34")) -> dict:
        """Candidates for one intent: columns DEF | NOW | V1..V4 (128 px), rows = the views that matter for the goal.
        768 x (3 x 128 + 13). No red tint (the text words each candidate's mesh)."""
        t0 = time.perf_counter()
        u = self.u
        self.setup_clip(clip)
        T = C_BIG
        nv = len(variants)
        t = [u.frame_time(clip, focus)]
        Gs, Js, Ms = [], [], []
        for ed in [base] + [base + v for v in variants]:
            G, Jm, mw = u.pose(clip, t, ed)
            Gs.append(G); Js.append(Jm); Ms.append(mw)
        G, Jm, mw = np.concatenate(Gs), np.concatenate(Js), np.concatenate(Ms)
        hp, gd = u.gaze(G)
        rays = np.stack([hp, hp + gd * u.gaze_len * 2.5], 1)
        self.skin(Jm, mw)
        self.msaa.use()
        self.msaa.viewport = (0, 0, SHEET_W, SHEET_H)
        self.msaa.clear(BG[0] / 255, BG[1] / 255, BG[2] / 255, 1.0, depth=1.0)
        self.p_mesh["tint"] = 0.0
        try:
            for b in range(1 + nv):
                for r, view in enumerate(rows):
                    self._draw(clip, view, b, ((1 + b) * T, r * T, T, T), rays[b])
        finally:
            self.p_mesh["tint"] = 1.0
        W, H = (2 + nv) * T, len(rows) * T + 13
        img = np.empty((H, W, 3), np.uint8)
        img[:] = BG
        img[:len(rows) * T] = self._read(W, len(rows) * T)
        img[0:T, 0:T] = self._def_tile(clip, focus, T)
        img[T:2 * T, 0:T] = self._def_tile(clip, focus, T, self.def_head_boxes[clip][focus])
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im)
        for b in range(1 + nv):
            if "side" in rows:
                self._level(dr, clip, G, b, (1 + b) * T, rows.index("side") * T, T)
        self._label(dr, (3, 2), f"DEF f{focus}")
        self._label(dr, (3, T + 2), "DEF head")
        if len(rows) > 2:
            for k, line in enumerate(("columns:", "NOW = current", "V1..: candidates", "rows: " + rows[0], rows[1], rows[2])):
                dr.text((4, 2 * T + 4 + 14 * k), line, fill=(10, 10, 10), font=self.font)
        for b, lab in enumerate(["NOW"] + labels):
            for r, view in enumerate(rows):
                self._label(dr, ((1 + b) * T + 3, r * T + 2), f"{lab}  {self.VIEW_NAMES.get(view, view)}" if r == 0 else
                            self.VIEW_NAMES.get(view, view), (150, 0, 0) if b else (10, 10, 10))
        for x in range(1, 2 + nv):
            dr.line((x * T, 0, x * T, len(rows) * T), fill=(150, 150, 150))
        for y in range(1, len(rows)):
            dr.line((0, y * T, W, y * T), fill=(150, 150, 150))
        dr.text((3, H - 12), f"{clip} f{focus}: CANDIDATES - pick one (or none); orange ray = gaze; blue dashes = level",
                fill=(20, 20, 20), font=self.font)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return {"jpeg": buf.getvalue(), "ms": {"total": round((time.perf_counter() - t0) * 1000, 2)}}

    ZOOM_VIEWS = ("sprite", "side", "top", "front", "battle", "head", "film")

    def zoom(self, clip: str, focus: int, view: str, edits: list) -> dict:
        """A look at one view, bigger and smaller than the sheet: DEF | ours, 256 px each (512 x 269); "head" = the head
        crops; "film" = the sheet's three film rows only."""
        u = self.u
        if view not in self.ZOOM_VIEWS:
            raise ValueError(f"view must be one of {list(self.ZOOM_VIEWS)}")
        if view == "film":
            r = self.sheet_compact(clip, focus, edits)
            keys, _ = self.cycle[clip]
            fs = min(C_FILM_MAX, C_W // len(keys))
            im = Image.open(io.BytesIO(r["jpeg"]))
            im = im.crop((0, 2 * C_BIG, C_W, 2 * C_BIG + len(C_FILM) * fs))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            return {"jpeg": buf.getvalue()}
        self.setup_clip(clip)
        T = 256
        G, Jm, mw = u.pose(clip, [u.frame_time(clip, focus)], edits)
        hp, gd = u.gaze(G)
        rays = np.stack([hp, hp + gd * u.gaze_len * 2.5], 1)
        self.skin(Jm, mw)
        self.msaa.use()
        self.msaa.viewport = (0, 0, SHEET_W, SHEET_H)
        self.msaa.clear(BG[0] / 255, BG[1] / 255, BG[2] / 255, 1.0, depth=1.0)
        if view == "head":
            spr = self.views[clip]["sprite"]
            self._draw(clip, "sprite", 0, (T, 0, T, T), rays[0], M=spr[0].matrix(self.head_boxes[clip][focus], *self.centre_radius[clip]))
        else:
            self._draw(clip, view, 0, (T, 0, T, T), rays[0])
        H = T + 13
        img = np.empty((H, 2 * T, 3), np.uint8)
        img[:] = BG
        img[:T] = self._read(2 * T, T)
        img[:T, :T] = self._def_tile(clip, focus, T, self.def_head_boxes[clip][focus] if view == "head" else None)
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im)
        if view == "side":
            self._level(dr, clip, G, 0, T, 0, T)
        self._label(dr, (3, 2), f"DEF f{focus}" + (" head" if view == "head" else ""))
        self._label(dr, (T + 3, 2), f"ours {view}" + (" (unit's L, faces left)" if view == "side" else
                                                      " (front = down)" if view == "top" else ""))
        dr.line((T, 0, T, T), fill=(150, 150, 150))
        dr.text((3, H - 12), f"{clip} f{focus}: zoomed look; orange ray = gaze; red = stretched skin", fill=(20, 20, 20), font=self.font)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return {"jpeg": buf.getvalue()}

    # ---------------------------------------------------------------- free camera (round 3)
    def vertex_heat(self, P: np.ndarray) -> np.ndarray:
        """Per vertex: the signed log2 length ratio (posed / rest) of its most deformed edge; +1 = 2x stretched,
        -1 = squashed to half. Absolute (the original mesh's own stretch shows too)."""
        u = self.u
        E = u.edges
        r = np.log2(np.maximum(np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1) / u.rest_len, 1e-6))
        hi = np.zeros(self.N); lo = np.zeros(self.N)
        for k in (0, 1):
            np.maximum.at(hi, E[:, k], r)
            np.minimum.at(lo, E[:, k], r)
        return np.where(hi >= -lo, hi, lo)

    def heat_words(self, h: np.ndarray) -> str:
        """Where the skin is most stretched / squashed, by the joints that carry it (words, no numbers)."""
        from anim_core import friendly
        s = self.u.scene
        out = []
        for lab, m in (("stretched", h > 0.6), ("squashed", h < -0.6)):
            if m.sum() < 3:
                continue
            w = np.zeros(len(s.joints))
            np.add.at(w, s.J[m].ravel(), s.W[m].ravel())
            top = [friendly(self.u.jnames[j]) for j in np.argsort(-w)[:2] if w[j] > 0.25 * w.max()]
            amt = "a few spots" if m.sum() < 30 else "a patch" if m.sum() < 200 else "a wide area"
            out.append(f"{amt} {lab} near the {' / '.join(top)}")
        return "; ".join(out) or "no strongly stretched or squashed skin in view"

    def view(self, clip: str, frames: list[int], yaw: float, pitch: float, dist: float, at: str, mode: str,
             edits: list) -> dict:
        """Free camera: any clip, any frame (or a strip of up to VIEW_MAX frames), orbit yaw (0 = the unit's front,
        90 = its left side, 180 = behind) and pitch (+ = from above), box size `dist` x body height, centred on a joint
        or the whole body; modes shaded | wire (shaded + wireframe) | normals (creases dark) | heat (stretch) |
        skeleton (shaded + joints). One image back, no red tint, no DEF."""
        t0 = time.perf_counter()
        u = self.u
        if mode not in VIEW_MODES:
            raise ValueError(f"mode must be one of {list(VIEW_MODES)}")
        self.setup_clip(clip)
        n = len(frames)
        times = [u.frame_time(clip, f) for f in frames]
        G, Jm, mw = u.pose(clip, times, edits)
        self.skin(Jm, mw)
        P = self.read_posed(n)
        node = u.names.index(at) if at not in (None, "", "body") else None
        d = orbit_dirs(float(np.clip(pitch, -89, 89)), float(yaw))
        cam = Cam("ortho", d["right"], d["up"], d["fwd"])
        size = float(np.clip(dist, 0.1, 4.0)) * u.H
        T = 384 if n == 1 else min(256, SHEET_W // n)
        Mats = []
        for b in range(n):
            c = G[b, node, :3, 3] if node is not None else (P[b].min(0) + P[b].max(0)) / 2
            sx, sy = cam.screen(c[None])[0]
            R = float(np.linalg.norm(P[b] - c, axis=1).max()) * 1.05 + 1e-3
            Mats.append(cam.matrix((sx - size / 2, sy - size / 2, size), c, R))
        heat_txt = None
        if mode == "heat":
            hs = [self.vertex_heat(P[b]) for b in range(n)]
            self.b_ht.write(np.ascontiguousarray(np.stack(hs), np.float32).tobytes())
            Hs = np.stack(hs)
            k = np.argmax(np.abs(Hs), 0)
            heat_txt = self.heat_words(np.take_along_axis(Hs, k[None], 0)[0])
        t1 = time.perf_counter()
        self.msaa.use()
        self.msaa.viewport = (0, 0, SHEET_W, SHEET_H)
        self.msaa.clear(BG[0] / 255, BG[1] / 255, BG[2] / 255, 1.0, depth=1.0)
        L = _norm(-0.55 * cam.fwd + 0.75 * np.array([0, 1.0, 0]) - 0.25 * cam.right)
        self.p_mesh["L"] = tuple(float(v) for v in L)
        self.p_mesh["vrot"].write(np.ascontiguousarray(np.stack([cam.right, cam.up, -cam.fwd]), np.float32).tobytes())
        self.p_mesh["tint"] = 0.0
        self.p_mesh["mode"] = {"normals": 2, "heat": 3}.get(mode, 0)
        try:
            for b in range(n):
                self.msaa.viewport = (b * T, SHEET_H - T, T, T)
                self.p_mesh["base"] = b * self.N
                self.p_mesh["hbase"] = b * self.N
                self.p_mesh["mvp"].write(np.ascontiguousarray(Mats[b].T, np.float32).tobytes())
                self.ctx.enable(moderngl.DEPTH_TEST)
                self.tex.use(0)
                self.vao.render(moderngl.TRIANGLES)
                if mode == "wire":
                    self.p_mesh["mode"] = 1
                    self.p_mesh["flat_col"] = (0.08, 0.08, 0.1)
                    self.p_mesh["zbias"] = 0.0015
                    self.ctx.wireframe = True
                    self.vao.render(moderngl.TRIANGLES)
                    self.ctx.wireframe = False
                    self.p_mesh["zbias"] = 0.0
                    self.p_mesh["mode"] = 0
                if mode == "skeleton":
                    self._skeleton(clip, G, b, (b * T, 0, T, T), M=Mats[b])
        finally:
            self.ctx.wireframe = False
            self.p_mesh["tint"] = 1.0
            self.p_mesh["mode"] = 0
            self.p_mesh["zbias"] = 0.0
        img = np.empty((T + 13, n * T, 3), np.uint8)
        img[:] = BG
        img[:T] = self._read(n * T, T)
        t2 = time.perf_counter()
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im)
        for b, f in enumerate(frames):
            self._label(dr, (b * T + 3, 2), f"f{f}")
            if b:
                dr.line((b * T, 0, b * T, T), fill=(150, 150, 150))
        side = ("front" if abs(((yaw + 180) % 360) - 180) < 30 else "behind" if abs(((yaw + 180) % 360) - 180) > 150
                else "its left" if ((yaw % 360) < 180) else "its right")
        cap = (f"{clip} {mode}; from {side}, yaw {yaw:g} pitch {pitch:g}; box {dist:g} H on {at or 'body'}"
               + ("; heat: red stretched, blue squashed" if mode == "heat" else ""))
        dr.text((3, T + 1), cap, fill=(20, 20, 20), font=self.font)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        t3 = time.perf_counter()
        return {"jpeg": buf.getvalue(), "heat": heat_txt,
                "ms": {"pose_skin": round((t1 - t0) * 1000, 1), "draw": round((t2 - t1) * 1000, 1),
                       "jpeg": round((t3 - t2) * 1000, 1), "total": round((t3 - t0) * 1000, 1)}}

    def baseline_stretch(self, clip: str) -> dict:
        u = self.u
        g = u.clips[clip]["grid"]
        _, Jm, mw = u.pose(clip, g)
        self.skin(Jm, mw)
        cnt, worst = self.stretch(len(g))
        return {"edgesOver2x": int(cnt.sum()), "worst": round(float(worst.max()), 3)}

    def gate_stretch(self, clip: str, edits: list[dict]) -> dict:
        u = self.u
        g = u.clips[clip]["grid"]
        _, Jm, mw = u.pose(clip, g, edits)
        self.skin(Jm, mw)
        cnt, worst = self.stretch(len(g))
        return {"edgesOver2x": int(cnt.sum()), "worst": round(float(worst.max()), 3)}
