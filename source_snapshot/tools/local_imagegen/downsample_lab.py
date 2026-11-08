#!/usr/bin/env python3
"""Interactive downsample probe: HI render -> TwCrPort-sized crop.

Scrub mirror, crop, scale, and PIL resample filters against the portrait.
Proof: local lab utility only.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import numpy as np
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HI = ROOT / "artifacts/collapse_authentic_upscale/surviving_masters/h3_hobgoblin_hi_render.png"
DEFAULT_TARGET = ROOT / "artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png"

METHODS = {
    "nearest": Image.Resampling.NEAREST,
    "box": Image.Resampling.BOX,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS,
}

VIEW_SCALE = 8  # nearest-neighbor blowup for pixel inspection


def ensure_hi_alpha(im: Image.Image, thr: float = 8.0) -> Image.Image:
    rgba = np.asarray(im.convert("RGBA")).copy()
    rgb = rgba[:, :, :3].astype(np.float32)
    alpha = rgba[:, :, 3]
    lum = rgb.mean(axis=2)
    pure = (lum <= thr) & (rgb.max(axis=2) <= thr)
    alpha = np.where((alpha == 0) | pure, 0, 255).astype(np.uint8)
    rgba[:, :, 3] = alpha
    rgba[alpha == 0, :3] = 0
    return Image.fromarray(rgba, "RGBA")


def fg_bbox(im: Image.Image) -> tuple[int, int, int, int]:
    a = np.asarray(im.convert("RGBA"))
    ys, xs = np.where(a[:, :, 3] > 0)
    if len(xs) == 0:
        rgb = a[:, :, :3].astype(np.float32)
        ys, xs = np.where(rgb.mean(axis=2) > 12)
    if len(xs) == 0:
        return 0, 0, im.size[0], im.size[1]
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def score_hi_fg(down: Image.Image, target: Image.Image) -> tuple[float, float, float]:
    d = np.asarray(down.convert("RGBA"), dtype=np.float32)
    t = np.asarray(target.convert("RGB"), dtype=np.float32)
    m = d[:, :, 3] >= 128
    if int(m.sum()) < 32:
        m = d[:, :, :3].mean(axis=2) > 12
    n = int(m.sum())
    if n < 32:
        return float("nan"), float("nan"), 0.0
    mae = float(np.abs(d[:, :, :3][m] - t[m]).mean())
    a = d[:, :, :3].mean(axis=2)[m]
    b = t.mean(axis=2)[m]
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    corr = float((a * b).mean())
    cov = n / float(d.shape[0] * d.shape[1])
    return mae, corr, cov


def to_photo(im: Image.Image, scale: int = VIEW_SCALE) -> ImageTk.PhotoImage:
    rgb = im.convert("RGB")
    if scale != 1:
        rgb = rgb.resize((rgb.size[0] * scale, rgb.size[1] * scale), Image.Resampling.NEAREST)
    return ImageTk.PhotoImage(rgb)


def checkerboard_composite(im: Image.Image, scale: int = VIEW_SCALE) -> Image.Image:
    rgba = im.convert("RGBA")
    w, h = rgba.size
    out = Image.new("RGB", (w, h))
    px = out.load()
    src = rgba.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = src[x, y]
            if a < 128:
                c = 170 if ((x // 4) + (y // 4)) % 2 == 0 else 110
                px[x, y] = (c, c, c)
            else:
                px[x, y] = (r, g, b)
    if scale != 1:
        out = out.resize((w * scale, h * scale), Image.Resampling.NEAREST)
    return out


class DownsampleLab(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("HoMM3 downsample lab — HI render vs TwCrPort")
        self.geometry("1280x820")
        self.minsize(1000, 700)

        self.hi_path = tk.StringVar(value=str(DEFAULT_HI))
        self.target_path = tk.StringVar(value=str(DEFAULT_TARGET))
        self.method = tk.StringVar(value="box")
        self.mirror = tk.BooleanVar(value=True)
        self.mode = tk.StringVar(value="h_frac")  # h_frac | integer
        self.h_frac = tk.DoubleVar(value=0.85)
        self.int_scale = tk.IntVar(value=5)
        self.crop_x = tk.IntVar(value=0)
        self.crop_y = tk.IntVar(value=0)
        self.right_bias = tk.IntVar(value=6)  # shift crop left => figure right
        self.ignore_hi_black = tk.BooleanVar(value=True)
        self.show_diff = tk.BooleanVar(value=True)

        self._hi_raw: Image.Image | None = None
        self._target: Image.Image | None = None
        self._fg: Image.Image | None = None
        self._photos: list[ImageTk.PhotoImage] = []
        self._rebuild_job: str | None = None

        self._build_ui()
        self.load_images()
        self.bind_all("<Left>", lambda e: self.nudge(-1, 0))
        self.bind_all("<Right>", lambda e: self.nudge(1, 0))
        self.bind_all("<Up>", lambda e: self.nudge(0, -1))
        self.bind_all("<Down>", lambda e: self.nudge(0, 1))

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="HI render").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.hi_path, width=72).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="Browse", command=self.browse_hi).grid(row=0, column=2)

        ttk.Label(top, text="Target portrait").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.target_path, width=72).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="Browse", command=self.browse_target).grid(row=1, column=2)
        ttk.Button(top, text="Reload", command=self.load_images).grid(row=1, column=3, padx=4)
        top.columnconfigure(1, weight=1)

        ctrls = ttk.LabelFrame(self, text="Controls", padding=8)
        ctrls.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        ttk.Checkbutton(ctrls, text="Mirror HI", variable=self.mirror, command=self.on_source_change).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Checkbutton(
            ctrls, text="Score/ignore HI black", variable=self.ignore_hi_black, command=self.schedule_rebuild
        ).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Checkbutton(ctrls, text="Show |diff|", variable=self.show_diff, command=self.schedule_rebuild).grid(
            row=0, column=2, sticky="w"
        )

        ttk.Label(ctrls, text="Method").grid(row=1, column=0, sticky="w", pady=4)
        mbox = ttk.Combobox(ctrls, textvariable=self.method, values=list(METHODS.keys()), state="readonly", width=12)
        mbox.grid(row=1, column=1, sticky="w")
        mbox.bind("<<ComboboxSelected>>", lambda e: self.schedule_rebuild())

        ttk.Label(ctrls, text="Mode").grid(row=1, column=2, sticky="w", padx=(12, 0))
        mode = ttk.Combobox(
            ctrls, textvariable=self.mode, values=["h_frac", "integer"], state="readonly", width=10
        )
        mode.grid(row=1, column=3, sticky="w")
        mode.bind("<<ComboboxSelected>>", lambda e: self.on_mode_change())

        self.h_frac_label = ttk.Label(ctrls, text="h_frac 0.85")
        self.h_frac_label.grid(row=2, column=0, sticky="w")
        self.h_frac_scale = ttk.Scale(
            ctrls,
            from_=0.35,
            to=1.0,
            variable=self.h_frac,
            command=lambda _v: self.on_hfrac_slide(),
        )
        self.h_frac_scale.grid(row=2, column=1, columnspan=3, sticky="ew", pady=2)

        self.int_label = ttk.Label(ctrls, text="integer scale 5")
        self.int_label.grid(row=3, column=0, sticky="w")
        self.int_scale_widget = ttk.Scale(
            ctrls,
            from_=2,
            to=8,
            variable=self.int_scale,
            command=lambda _v: self.on_int_slide(),
        )
        self.int_scale_widget.grid(row=3, column=1, columnspan=3, sticky="ew", pady=2)

        ttk.Label(ctrls, text="crop X").grid(row=4, column=0, sticky="w")
        self.x_scale = ttk.Scale(ctrls, from_=0, to=100, variable=self.crop_x, command=lambda _v: self.schedule_rebuild())
        self.x_scale.grid(row=4, column=1, columnspan=2, sticky="ew")
        ttk.Label(ctrls, text="crop Y").grid(row=5, column=0, sticky="w")
        self.y_scale = ttk.Scale(ctrls, from_=0, to=100, variable=self.crop_y, command=lambda _v: self.schedule_rebuild())
        self.y_scale.grid(row=5, column=1, columnspan=2, sticky="ew")

        ttk.Label(ctrls, text="right bias (px on HI)").grid(row=4, column=3, sticky="w", padx=(12, 0))
        ttk.Spinbox(
            ctrls,
            from_=-40,
            to=40,
            textvariable=self.right_bias,
            width=6,
            command=self.apply_bias_seed,
        ).grid(row=4, column=4, sticky="w")
        ttk.Button(ctrls, text="Seed centered−bias", command=self.apply_bias_seed).grid(row=5, column=3, columnspan=2, sticky="w", padx=(12, 0))

        ttk.Label(ctrls, text="Arrow keys nudge crop 1px").grid(row=6, column=0, columnspan=3, sticky="w", pady=4)
        ctrls.columnconfigure(1, weight=1)

        self.status = tk.StringVar(value="Load images to begin.")
        ttk.Label(self, textvariable=self.status, padding=8).pack(side=tk.TOP, fill=tk.X)

        views = ttk.Frame(self, padding=8)
        views.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.panel_labels = []
        self.panel_images = []
        titles = ["HI crop", "Downsampled", "TwCrPort target", "Diff / checker"]
        for i, title in enumerate(titles):
            f = ttk.LabelFrame(views, text=title, padding=4)
            f.grid(row=0, column=i, sticky="nsew", padx=4)
            lab = ttk.Label(f)
            lab.pack()
            self.panel_labels.append(lab)
            views.columnconfigure(i, weight=1)
        views.rowconfigure(0, weight=1)

        self.on_mode_change()

    def browse_hi(self) -> None:
        p = filedialog.askopenfilename(initialdir=str(DEFAULT_HI.parent), filetypes=[("PNG", "*.png"), ("All", "*.*")])
        if p:
            self.hi_path.set(p)
            self.load_images()

    def browse_target(self) -> None:
        p = filedialog.askopenfilename(
            initialdir=str(DEFAULT_TARGET.parent), filetypes=[("PNG", "*.png"), ("All", "*.*")]
        )
        if p:
            self.target_path.set(p)
            self.load_images()

    def load_images(self) -> None:
        try:
            hi = Image.open(self.hi_path.get())
            self._hi_raw = ensure_hi_alpha(hi) if self.ignore_hi_black.get() else hi.convert("RGBA")
            self._target = Image.open(self.target_path.get()).convert("RGBA")
        except Exception as exc:
            self.status.set(f"Load failed: {exc}")
            return
        self.on_source_change()

    def on_source_change(self) -> None:
        if self._hi_raw is None:
            return
        src = self._hi_raw.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if self.mirror.get() else self._hi_raw
        x0, y0, x1, y1 = fg_bbox(src)
        self._fg = src.crop((x0, y0, x1, y1))
        self.apply_bias_seed()

    def on_mode_change(self) -> None:
        is_frac = self.mode.get() == "h_frac"
        state_frac = tk.NORMAL if is_frac else tk.DISABLED
        state_int = tk.NORMAL if not is_frac else tk.DISABLED
        self.h_frac_scale.configure(state=state_frac)
        self.int_scale_widget.configure(state=state_int)
        self.schedule_rebuild()

    def on_hfrac_slide(self) -> None:
        self.h_frac_label.configure(text=f"h_frac {self.h_frac.get():.3f}")
        self._update_crop_limits(reset_xy=False)
        self.schedule_rebuild()

    def on_int_slide(self) -> None:
        s = int(round(self.int_scale.get()))
        self.int_scale.set(s)
        self.int_label.configure(text=f"integer scale {s}")
        self._update_crop_limits(reset_xy=False)
        self.schedule_rebuild()

    def apply_bias_seed(self) -> None:
        if self._fg is None or self._target is None:
            return
        fw, fh = self._fg.size
        tw, th = self._target.size
        ww, hh = self._window_size(fw, fh, tw, th)
        sx = max(0, (fw - ww) // 2 - int(self.right_bias.get()))
        sy = 0
        self._update_crop_limits(reset_xy=False, ww=ww, hh=hh)
        self.crop_x.set(min(sx, int(self.x_scale.cget("to"))))
        self.crop_y.set(min(sy, int(self.y_scale.cget("to"))))
        self.schedule_rebuild()

    def _window_size(self, fw: int, fh: int, tw: int, th: int) -> tuple[int, int]:
        if self.mode.get() == "integer":
            s = max(2, int(round(self.int_scale.get())))
            return tw * s, th * s
        hh = int(round(fh * float(self.h_frac.get())))
        ww = int(round(hh * (tw / float(th))))
        return ww, hh

    def _update_crop_limits(self, reset_xy: bool, ww: int | None = None, hh: int | None = None) -> None:
        if self._fg is None or self._target is None:
            return
        fw, fh = self._fg.size
        tw, th = self._target.size
        if ww is None or hh is None:
            ww, hh = self._window_size(fw, fh, tw, th)
        max_x = max(0, fw - ww)
        max_y = max(0, fh - hh)
        self.x_scale.configure(to=max(0, max_x))
        self.y_scale.configure(to=max(0, max_y))
        if reset_xy:
            self.crop_x.set(0)
            self.crop_y.set(0)
        else:
            self.crop_x.set(min(int(self.crop_x.get()), max_x))
            self.crop_y.set(min(int(self.crop_y.get()), max_y))

    def nudge(self, dx: int, dy: int) -> None:
        self.crop_x.set(max(0, min(int(self.x_scale.cget("to")), int(self.crop_x.get()) + dx)))
        self.crop_y.set(max(0, min(int(self.y_scale.cget("to")), int(self.crop_y.get()) + dy)))
        self.schedule_rebuild()

    def schedule_rebuild(self) -> None:
        if self._rebuild_job is not None:
            self.after_cancel(self._rebuild_job)
        self._rebuild_job = self.after(40, self.rebuild)

    def rebuild(self) -> None:
        self._rebuild_job = None
        if self._fg is None or self._target is None:
            return
        fw, fh = self._fg.size
        tw, th = self._target.size
        ww, hh = self._window_size(fw, fh, tw, th)
        if ww > fw or hh > fh or ww < 1 or hh < 1:
            self.status.set(f"Window {ww}x{hh} does not fit FG {fw}x{fh}")
            return
        self._update_crop_limits(reset_xy=False, ww=ww, hh=hh)
        x = int(self.crop_x.get())
        y = int(self.crop_y.get())
        x = max(0, min(x, fw - ww))
        y = max(0, min(y, fh - hh))

        crop = self._fg.crop((x, y, x + ww, y + hh))
        method = self.method.get()
        down = crop.resize((tw, th), METHODS[method])

        # Preview crop fitted into a fixed-ish panel via letterbox NN of a thumbnail
        crop_prev = crop.convert("RGBA")
        # Fit crop preview to ~ target*VIEW_SCALE height
        target_h = th * VIEW_SCALE
        sc = target_h / max(1, crop_prev.size[1])
        crop_disp = crop_prev.resize(
            (max(1, int(round(crop_prev.size[0] * sc))), target_h),
            Image.Resampling.NEAREST,
        )

        mae, corr, cov = score_hi_fg(down, self._target)
        scale_x = ww / tw
        scale_y = hh / th

        down_rgb = down.convert("RGB")
        tgt_rgb = self._target.convert("RGB")
        if self.show_diff.get():
            d = np.abs(np.asarray(down_rgb, dtype=np.float32) - np.asarray(tgt_rgb, dtype=np.float32))
            if self.ignore_hi_black.get():
                a = np.asarray(down.convert("RGBA"))[:, :, 3] < 128
                d[a] = 0
            fourth_im = Image.fromarray(np.clip(d * 3.0, 0, 255).astype(np.uint8))
            fourth_photo = to_photo(fourth_im)
        else:
            fourth_photo = ImageTk.PhotoImage(checkerboard_composite(down, scale=VIEW_SCALE))

        photos = [
            to_photo(crop_disp, scale=1),
            to_photo(down_rgb),
            to_photo(tgt_rgb),
            fourth_photo,
        ]
        self._photos = photos
        for lab, ph in zip(self.panel_labels, photos):
            lab.configure(image=ph)

        self.status.set(
            f"FG {fw}x{fh}  crop xy=({x},{y}) wh=({ww},{hh})  "
            f"scale≈{scale_x:.3f}x/{scale_y:.3f}y  method={method}  mirror={self.mirror.get()}  "
            f"mae_fg={mae:.2f}  corr={corr:.3f}  cov={cov:.3f}"
        )


def main() -> int:
    app = DownsampleLab()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
