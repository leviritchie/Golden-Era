"""Stronghold full-3D: fast offline preview renderer (moderngl, standalone GL 3.3) for iterating before Unity.

Draws the same pieces the bundle carries, in the painting world, with the Hex/Lit diffuse model of
Homm3TownLabHexLit.shader (trilight ambient + key + fill; albedo in linear, output sRGB). Sky pieces are unlit.
Proof tier: a preview only. The review set uses Unity editor renders.
"""
from __future__ import annotations

import math

import numpy as np

VS = """
#version 330
uniform mat4 mvp;
in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv;
out vec3 v_n; out vec2 v_uv;
void main(){ gl_Position = mvp * vec4(in_pos, 1.0); v_n = in_nrm; v_uv = in_uv; }
"""
FS = """
#version 330
uniform sampler2D tex; uniform int unlit; uniform float cutout;
uniform vec3 sunDir, sunColor, ambSky, ambEq, ambGround, fillDir, fillColor;
in vec3 v_n; in vec2 v_uv; out vec4 o;
vec3 lin(vec3 c){ return mix(c/12.92, pow((c+0.055)/1.055, vec3(2.4)), step(0.04045, c)); }
vec3 srgb(vec3 c){ c = clamp(c, 0.0, 1.0); return mix(c*12.92, 1.055*pow(c, vec3(1.0/2.4))-0.055, step(0.0031308, c)); }
void main(){
  vec4 t = texture(tex, v_uv);
  if (t.a < cutout) discard;
  if (unlit == 1) { o = vec4(t.rgb, 1.0); return; }
  vec3 n = normalize(v_n);
  float ny = n.y;
  vec3 amb = ny >= 0.0 ? mix(ambEq, ambSky, sqrt(max(ny,0.0))) : mix(ambEq, ambGround, sqrt(max(-ny,0.0)));
  vec3 L = amb + sunColor * max(dot(n, -sunDir), 0.0) + fillColor * max(dot(n, -fillDir), 0.0);
  o = vec4(srgb(lin(t.rgb) * L), 1.0);
}
"""


def perspective(fov_deg, aspect, near, far):
    f = 1 / math.tan(math.radians(fov_deg) / 2)
    return np.array([[f / aspect, 0, 0, 0], [0, f, 0, 0],
                     [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)], [0, 0, -1, 0]], np.float64)


def view(pos, fwd, up, right):
    R = np.stack([right, up, -np.asarray(fwd)], 0)
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = -R @ np.asarray(pos)
    return M


class Renderer:
    def __init__(self, rig: dict, sun_dir, w=1920, h=1080):
        import moderngl
        self.ctx = moderngl.create_standalone_context()
        self.prog = self.ctx.program(vertex_shader=VS, fragment_shader=FS)
        self.rig, self.sun = rig, np.asarray(sun_dir, np.float32)
        self.pieces = []
        self.resize(w, h)

    def resize(self, w, h):
        self.w, self.h = w, h
        self.fbo = self.ctx.simple_framebuffer((w, h), components=4, samples=4)
        self.out = self.ctx.simple_framebuffer((w, h), components=4)

    def add(self, name, P, n, uv, tris, img, unlit=False, cutout=0.0):
        """img: HxWx3/4 uint8 sRGB (albedo); P/n in the painting world."""
        img = np.ascontiguousarray(np.asarray(img, np.uint8)[::-1])
        if img.shape[2] == 3:
            img = np.concatenate([img, np.full(img.shape[:2] + (1,), 255, np.uint8)], 2)
        tex = self.ctx.texture((img.shape[1], img.shape[0]), 4, img.tobytes())
        tex.build_mipmaps()
        import moderngl
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.anisotropy = 8.0
        vb = np.concatenate([np.asarray(P, np.float32), np.asarray(n, np.float32), np.asarray(uv, np.float32)], 1)
        vbo = self.ctx.buffer(vb.astype(np.float32).tobytes())
        ibo = self.ctx.buffer(np.asarray(tris, np.int32).tobytes())
        vao = self.ctx.vertex_array(self.prog, [(vbo, "3f 3f 2f", "in_pos", "in_nrm", "in_uv")], ibo)
        self.pieces.append({"name": name, "vao": vao, "tex": tex, "unlit": unlit, "cutout": cutout})

    def render(self, cam: dict, near=1.0, far=2000.0, only=None) -> np.ndarray:
        import moderngl
        mvp = perspective(cam["fov"], self.w / self.h, near, far) @ view(cam["pos"], cam["fwd"], cam["up"], cam["right"])
        self.fbo.use()
        self.ctx.clear(1.0, 0.0, 1.0, 1.0)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.CULL_FACE)
        p = self.prog
        p["mvp"].write(mvp.T.astype(np.float32).tobytes())
        for k in ("sunColor", "ambSky", "ambEq", "ambGround"):
            p[k].value = tuple(float(x) for x in self.rig[k])
        p["sunDir"].value = tuple(float(x) for x in self.sun)
        p["fillDir"].value = tuple(float(x) for x in self.rig.get("fillDir", (0, -1, 0)))
        p["fillColor"].value = tuple(float(x) for x in self.rig.get("fillColor", (0, 0, 0)))
        for pc in sorted(self.pieces, key=lambda q: not q["unlit"]):
            if only and not any(pc["name"].startswith(o) for o in only):
                continue
            p["unlit"].value = int(pc["unlit"])
            p["cutout"].value = float(pc["cutout"])
            if pc["unlit"]:
                self.ctx.disable(moderngl.DEPTH_TEST)
            else:
                self.ctx.enable(moderngl.DEPTH_TEST)
            pc["tex"].use(0)
            p["tex"].value = 0
            pc["vao"].render()
        self.ctx.copy_framebuffer(self.out, self.fbo)
        a = np.frombuffer(self.out.read(components=3), np.uint8).reshape(self.h, self.w, 3)
        return a[::-1].copy()
