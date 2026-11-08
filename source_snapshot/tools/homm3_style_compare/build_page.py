"""Build the comparison page + PNG contact sheets from render/ and metrics.json.

    python tools/homm3_style_compare/build_page.py
Writes artifacts/homm3_style_compare/index.html, img/*.png and sheets/*.png (images alongside the page).
Proof tier: generated artifact (offline renders + measurements).
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "homm3_unit_look"))
import pairs as PR  # noqa: E402
from measure import PX_PER_WU, SAND, crop_box, load, resize_h  # noqa: E402

OUT = PR.OUT
RENDER = OUT / "render"
IMG = OUT / "img"
SHEETS = OUT / "sheets"
BG = SAND


def font(size):
    for f in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def on_bg(im, bg=BG):
    base = Image.new("RGBA", (im.shape[1], im.shape[0]), (*bg, 255))
    return Image.alpha_composite(base, Image.fromarray(im)).convert("RGB")


def pad(b, frac, lim):
    w, h = b[2] - b[0], b[3] - b[1]
    p = int(max(w, h) * frac)
    return (max(0, b[0] - p), max(0, b[1] - p), min(lim, b[2] + p), min(lim, b[3] + p))


def row(imgs, gap=12, bg=BG, labels=None, lab_h=0):
    h = max(i.height for i in imgs) + lab_h
    w = sum(i.width for i in imgs) + gap * (len(imgs) - 1)
    c = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(c)
    x = 0
    for k, i in enumerate(imgs):
        c.paste(i, (x, h - i.height - 0))
        if labels:
            d.text((x + 6, 4), labels[k], font=font(18), fill=(40, 34, 24))
        x += i.width + gap
    return c


def col(imgs, gap=12, bg=(30, 30, 30)):
    w = max(i.width for i in imgs)
    c = Image.new("RGB", (w, sum(i.height for i in imgs) + gap * (len(imgs) - 1)), bg)
    y = 0
    for i in imgs:
        c.paste(i, (0, y)); y += i.height + gap
    return c


def pair_crop(files, frac=0.05):
    ims = [load(f) for f in files]
    b = pad(crop_box(*ims), frac, ims[0].shape[0])
    return [im[b[1]:b[3], b[0]:b[2]] for im in ims]


def fit_h(pil, h):
    return pil.resize((max(1, round(pil.width * h / pil.height)), h), Image.LANCZOS)


def battle_size(lit_path, h_world, scale=1.0):
    im = load(lit_path)
    b = Image.fromarray(im).getchannel("A").getbbox()
    im = im[b[1]:b[3], b[0]:b[2]]
    return resize_h(im, max(4, round(h_world * PX_PER_WU * scale)))


def battle_strip(items, zoom=1, width=None):
    """items: [(rgba, label)] standing on one ground line at true battle px; zoom = nearest upscale."""
    gap = 18
    H = max(i.shape[0] for i, _ in items) + 34
    W = sum(i.shape[1] for i, _ in items) + gap * (len(items) + 1)
    c = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(c)
    x = gap
    for im, lab in items:
        p = Image.fromarray(im)
        c.paste(p, (x, H - 22 - im.shape[0]), p)
        d.text((x, H - 18), lab, font=font(11), fill=(50, 40, 25))
        x += im.shape[1] + gap
    if zoom != 1:
        c = c.resize((c.width * zoom, c.height * zoom), Image.NEAREST)
    return c


def fmt(x, n=1):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{n}f}"


def main():
    met = json.loads((OUT / "metrics.json").read_text())
    IMG.mkdir(exist_ok=True); SHEETS.mkdir(exist_ok=True)
    anchor = met["scaleAnchor"]
    k_anchor = anchor["perHexAnchored"] / anchor["perHexInstalled"]
    sheet_detail, sheet_turn, sheet_alb, army_o, army_v = [], [], [], [], []
    for p in met["pairs"]:
        u = p["ours"]; d = RENDER / u
        # detail views: one crop per view shared by the pair (same world scale)
        ob, vb = pair_crop([d / "ours/lit_battle.png", d / "vanilla/lit_battle.png"])
        of, vf = pair_crop([d / "ours/lit_front34.png", d / "vanilla/lit_front34.png"])
        H = 460
        det = row([fit_h(on_bg(ob), H), fit_h(on_bg(vb), H), fit_h(on_bg(of), H), fit_h(on_bg(vf), H)],
                  labels=["ours - battle view", "vanilla - battle view", "ours - front 3/4", "vanilla - front 3/4"], lab_h=28)
        det.save(IMG / f"{u}_detail.png")
        sheet_detail.append(row([fit_h(on_bg(ob), 300), fit_h(on_bg(vb), 300)], labels=[u, p["vanillaName"]], lab_h=26))
        # flat albedo (+ vanilla emission)
        alb = [d / "ours/albedo_battle.png", d / "vanilla/albedo_battle.png"]
        if (d / "vanilla/emi_battle.png").is_file():
            alb.append(d / "vanilla/emi_battle.png")
        ac = pair_crop(alb)
        labs = ["ours - flat base colour", "vanilla - flat albedo", "vanilla - lit + emission map"][:len(ac)]
        a_img = row([fit_h(on_bg(x, (128, 128, 128)), 360) for x in ac], bg=(128, 128, 128), labels=labs, lab_h=26)
        a_img.save(IMG / f"{u}_albedo.png")
        sheet_alb.append(fit_h(a_img, 240))
        # turntable: one crop across all 16 frames
        tf = [d / f"ours/lit_turn_{i}.png" for i in range(8)] + [d / f"vanilla/lit_turn_{i}.png" for i in range(8)]
        tc = pair_crop(tf, 0.03)
        t_img = col([row([fit_h(on_bg(x), 170) for x in tc[:8]], gap=4), row([fit_h(on_bg(x), 170) for x in tc[8:]], gap=4)],
                    gap=4, bg=BG)
        t_img.save(IMG / f"{u}_turn.png")
        sheet_turn.append(t_img)
        # battle size
        hb_o, hb_v = p["pair"]["heightOurs"], p["pair"]["heightVanilla"]
        bo = battle_size(d / "ours/lit_battle.png", hb_o)
        bv = battle_size(d / "vanilla/lit_battle.png", hb_v)
        bo_a = battle_size(d / "ours/lit_battle.png", hb_o * k_anchor)
        items = [(bo, "ours (installed per-hex)"), (bo_a, "ours (skeleton-anchored)"), (bv, "vanilla")]
        battle_strip(items).save(IMG / f"{u}_battle1x.png")
        battle_strip(items, zoom=3).save(IMG / f"{u}_battle3x.png")
        army_o.append((bo, u.replace("h3_", ""))); army_v.append((bv, p["vanilla"]))
    col(sheet_detail, gap=8).save(SHEETS / "sheet_battle_view_detail.png")
    col([fit_h(t, 220) for t in sheet_turn], gap=10).save(SHEETS / "sheet_turntables.png")
    col(sheet_alb, gap=8, bg=(128, 128, 128)).save(SHEETS / "sheet_albedo.png")
    army = col([battle_strip(army_o), battle_strip(army_v)], gap=0, bg=BG)
    army.save(SHEETS / "sheet_battle_size_1x.png")
    army.resize((army.width * 2, army.height * 2), Image.NEAREST).save(SHEETS / "sheet_battle_size_2x.png")
    variants_sheet(met)
    write_html(met, k_anchor)
    print("PAGE", OUT / "index.html")


def variants_sheet(met):
    vj = OUT / "variants/variants.json"
    if not vj.is_file():
        return
    doc = json.loads(vj.read_text())
    rows = []
    for u, vs in doc.items():
        d = RENDER / u
        names = ["lit"] + list(vs)
        files = [d / f"ours/{n}_battle.png" for n in names] + [d / "vanilla/lit_battle.png"]
        if not all(f.is_file() for f in files):
            continue
        cs = pair_crop(files)
        r = row([fit_h(on_bg(x), 340) for x in cs], labels=["ours (as shipped)"] + [f"ours: {n}" for n in vs] + ["vanilla"],
                lab_h=26)
        r.save(IMG / f"{u}_ab.png")
        # battle size A/B
        pj = json.loads((d / "pair.json").read_text())
        its = [(battle_size(f, pj["heightOurs"] if i < len(names) else pj["heightVanilla"]), lab)
               for i, (f, lab) in enumerate(zip(files, ["shipped"] + list(vs) + ["vanilla"]))]
        battle_strip(its, zoom=3).save(IMG / f"{u}_ab_battle3x.png")
        rows.append(r)
    if rows:
        col(rows, gap=10).save(SHEETS / "sheet_ab_variants.png")


AXES = [  # key, label, getter, digits, kind (ratio|delta)
    ("Lmean", "Brightness: mean L* (lit)", lambda s: s["Lmean"], 1, "delta"),
    ("Lspread", "Contrast: L* p95-p5 (lit)", lambda s: s["Lspread"], 1, "delta"),
    ("albedoLmean", "Albedo mean L* (unlit)", lambda s: s["albedoLmean"], 1, "delta"),
    ("Cmean", "Saturation: mean C* (lit)", lambda s: s["Cmean"], 1, "ratio"),
    ("Cp90", "Saturation: C* p90 (lit)", lambda s: s["Cp90"], 1, "ratio"),
    ("hueConcentration", "Palette unity: hue concentration (0-1)", lambda s: s["hueConcentration"], 2, "delta"),
    ("detailFineRms", "Texture detail: fine band RMS (L*, 400 px tall)", lambda s: s["detailFineRms"], 2, "ratio"),
    ("detailMidRms", "Texture detail: mid band RMS", lambda s: s["detailMidRms"], 2, "ratio"),
    ("speckleFrac", "Noise: speckle fraction (|L-median3|>6, albedo)", lambda s: s["speckleFrac"], 3, "ratio"),
    ("albedoLowpassSpread", "Baked shading/AO: low-pass albedo L* p95-p5", lambda s: s["albedoLowpassSpread"], 1, "delta"),
    ("liveShadingStd", "Live shading: std of (lit - albedo) L*", lambda s: s["liveShadingStd"], 2, "delta"),
    ("edgeContrastVsSand", "Battle: silhouette edge dL* vs sand", lambda s: s["edgeContrastVsSand"], 1, "delta"),
    ("internalEdgeMean", "Battle: interior edge strength (Sobel L*)", lambda s: s["internalEdgeMean"], 2, "ratio"),
    ("silhouetteIsoperimetric", "Silhouette complexity: perimeter^2/(4 pi A)", lambda s: s["silhouetteIsoperimetric"], 2, "ratio"),
    ("silhouetteSolidity", "Silhouette solidity: area/convex hull", lambda s: s["silhouetteSolidity"], 2, "delta"),
    ("triangles", "Polycount: triangles", lambda s: s["triangles"], 0, "ratio"),
    ("heightWorld", "Battle height (world units)", lambda s: s["heightWorld"], 2, "ratio"),
    ("battlePxHeight", "Battle height (px @ assumed 55 px/unit)", lambda s: s["battlePxHeight"], 0, "ratio"),
    ("metalFrac", "Metal proxy: neutral-light texel share", lambda s: s["metalProxy"]["frac"], 2, "ratio"),
    ("metalLitL", "Metal proxy: lit L*", lambda s: s["metalProxy"]["litL"], 1, "delta"),
    ("metalSheen", "Metal proxy: sheen L* p95-p50", lambda s: s["metalProxy"]["litSheenP95minusP50"], 1, "delta"),
]


def summary(met):
    out = []
    for key, lab, g, dg, kind in AXES:
        vals = [(g(p["o"]), g(p["v"])) for p in met["pairs"] if g(p["o"]) is not None and g(p["v"]) is not None
                and not (key == "heightWorld" and p["pair"]["vanillaHeightAuthoredOnly"])
                and not (key == "battlePxHeight" and p["pair"]["vanillaHeightAuthoredOnly"])]
        if not vals:
            continue
        o = np.array([a for a, _ in vals], float); v = np.array([b for _, b in vals], float)
        eff = np.median(o / np.maximum(v, 1e-9)) if kind == "ratio" else np.median(o - v)
        out.append({"key": key, "label": lab, "kind": kind, "oursMedian": float(np.median(o)),
                    "vanillaMedian": float(np.median(v)), "effect": float(eff), "digits": dg,
                    "oursHigher": int((o > v).sum()), "n": len(vals)})
    return out


CSS = """
:root{--bg:#f6f3ec;--fg:#1f1b16;--muted:#6b6358;--card:#fffdf8;--line:#e3dccf;--accent:#8a5a1c;--hi:#b3261e;--lo:#1d5fa8}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#17150f;--fg:#ece6da;--muted:#a79f92;--card:#221f18;--line:#3a352b;--accent:#e0a55a;--hi:#f2847b;--lo:#7fb3f0}}
:root[data-theme="dark"]{--bg:#17150f;--fg:#ece6da;--muted:#a79f92;--card:#221f18;--line:#3a352b;--accent:#e0a55a;--hi:#f2847b;--lo:#7fb3f0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1500px;margin:0 auto;padding:24px 16px 80px}h1{font-size:28px;margin:0 0 4px}h2{margin-top:44px;border-bottom:1px solid var(--line);padding-bottom:6px}
.note{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}
img{max-width:100%;height:auto;display:block;border-radius:6px}.pix{image-rendering:pixelated}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:right}
th:first-child,td:first-child{text-align:left}th{background:var(--card);position:sticky;top:0}.scroll{overflow-x:auto}
.hi{color:var(--hi);font-weight:600}.lo{color:var(--lo);font-weight:600}.sw{display:inline-block;width:22px;height:16px;border-radius:3px;margin-right:2px;vertical-align:middle;border:1px solid var(--line)}
nav a{margin-right:10px;color:var(--accent)}code{font-size:12.5px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:800px){.grid2{grid-template-columns:1fr}}
"""


def write_html(met, k_anchor):
    summ = summary(met)
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1))
    a = met["scaleAnchor"]
    fac = json.loads((OUT / "variants/factors.json").read_text()) if (OUT / "variants/factors.json").is_file() else None
    h = [f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>Unit Style Comparison</title><style>{CSS}</style></head><body><main>"]
    h.append("<h1>Our prebaked HoMM3 units vs vanilla Olden Era</h1>")
    h.append("<p class=note>Proof tier: <b>offline renders</b> (Blender Eevee) and measurements on them. Not an in-game capture. "
             "Both sides use the same relight model, camera, sand-arena sun and ground colour, so the differences are style, not renderer.</p>")
    h.append("<nav>" + "".join(f"<a href='#{x}'>{t}</a>" for x, t in [("method", "Method"), ("summary", "Systematic differences"),
             ("knobs", "Knobs"), ("ab", "A/B variants"), ("table", "Axis table"), ("pairs", "Pairs"), ("sheets", "Contact sheets")]) + "</nav>")
    # ---- method
    h.append("<h2 id=method>Method and how the vanilla relight differs from the game</h2><div class=card><ul>")
    h += [f"<li>{x}</li>" for x in [
        "<b>Shader:</b> every vanilla material we read is the game's own <code>Hex/Lit</code> shader, the same shader our units ship with. "
        "Both are relit with <code>showcase_render.py</code>'s model: albedo &times; (sun &middot; N&middot;L &middot; shadow + ambient), no specular. "
        "Sun = the sand arena's serialized MainLight direction and colour; ambient = the probed RenderSettings ambient.",
        "<b>Not modelled for vanilla:</b> the per-material Hex/Lit floats (<code>_Lumin</code>, <code>_ColIntense</code>, <code>_MinLight/_MaxLight</code>, contour lines, "
        "dither fade); vanilla <b>emission maps</b> (<code>HEX_EMISSION_MAP_ENABLED</code>: Angel, Black Dragon, Lich, Titan) are shown in a separate panel, added at weight 1 "
        "(an assumption; the real emission scale is not decoded). Vanilla normals are the mesh's own skinned vertex normals; no normal map is used on either side "
        "(the esquire-family materials reference none).",
        "<b>Pose:</b> ours = the retarget build at its first idle frame. Vanilla = the prefab skinned at t=0 of its own <code>22.Idle</code> override clip "
        "(decoded from <code>resources.assets</code>, read-only). Vanilla fliers are shown standing at their idle, not at flight height.",
        "<b>Facing:</b> ours from the unit-look's resolved front (<code>metrics.json lighting.frontResolved</code>); vanilla from the prefab's +Z. "
        "Battle view = orthographic, 40&deg; elevation, unit facing screen-right, camera along the arena's forward axis (the prebake's battle-camera hypothesis). "
        "Front 3/4 = 15&deg; elevation, 45&deg; off the front. Turntable = 8 &times; 45&deg; at 30&deg;, the sun turning with the camera.",
        f"<b>Scale:</b> ours = <code>battleHeightHexes &times; battleWorldHeightPerHex</code> ({a['perHexInstalled']}) at the idle pose, the runtime "
        "<code>FitSkinnedBattleMesh</code> rule. Vanilla = the prefab's skinned idle height with the first child's scale replaced by <code>UnitViewConfig.scale</code> "
        "(the UiModelsSpawner contract; assumed to hold for battle spawns too). The vanilla Titan prefab has no unit view, so it is shown at our Titan's height and excluded from scale statistics. "
        f"Battle-size panels use an <b>assumed</b> {PX_PER_WU:.0f} px per world unit at 1080p; relative sizes are exact under the two rules, absolute pixels are not measured.",
        "<b>In-game screenshot:</b> none of vanilla battle units was found in the repo, and the game was not launched (another agent is deploying). "
        "One runtime check would settle the scale finding below: the <code>Homm3Import skinned fit source=hex</code> log line prints <code>donorY</code> next to <code>targetY</code>.",
        "<b>Measurement scales:</b> colour on the full render; detail, noise and silhouette shape after resampling each unit to 400 px tall (so taller units are not credited with more texels); "
        "readability at battle size on the sand colour. Our units are measured without their VFX layers (the showcase composite is not reproduced here); layer counts are listed."]]
    h.append("</ul></div>")
    # ---- summary
    h.append("<h2 id=summary>Systematic differences (median over pairs)</h2>")
    h.append(f"<div class=card><p><b>Scale anchor.</b> The vanilla skeleton is {a['vanillaSkeletonWorldHeight']:.2f} world units tall at its idle; "
             f"HoMM3's skeleton is {a['h3SkeletonHexes']:.3f} hexes, so a skeleton-anchored <code>battleWorldHeightPerHex</code> would be "
             f"<b>{a['perHexAnchored']:.3f}</b> against the installed {a['perHexInstalled']}. Under the two rules above our units stand "
             f"<b>{1 / k_anchor:.2f}&times;</b> taller than a skeleton-anchored fit.</p></div>")
    h.append("<div class=scroll><table><tr><th>axis</th><th>ours (median)</th><th>vanilla (median)</th><th>ours vs vanilla</th><th>pairs where ours is higher</th></tr>")
    for s in summ:
        eff = f"&times;{s['effect']:.2f}" if s["kind"] == "ratio" else f"{s['effect']:+.{max(1, s['digits'])}f}"
        big = (s["kind"] == "ratio" and (s["effect"] > 1.3 or s["effect"] < 0.77)) or (s["kind"] == "delta" and abs(s["effect"]) >= 5)
        cls = ("hi" if (s["effect"] > 1 if s["kind"] == "ratio" else s["effect"] > 0) else "lo") if big else ""
        h.append(f"<tr><td>{s['label']}</td><td>{fmt(s['oursMedian'], s['digits'])}</td><td>{fmt(s['vanillaMedian'], s['digits'])}</td>"
                 f"<td class='{cls}'>{eff}</td><td>{s['oursHigher']}/{s['n']}</td></tr>")
    h.append("</table></div><p class=note>Red = ours markedly higher, blue = markedly lower (ratio beyond &times;1.3 / &times;0.77 or |&Delta;| &ge; 5).</p>")
    h.append("<div class=card id=findings>" + (OUT / "findings.html").read_text(encoding="utf-8") + "</div>"
             if (OUT / "findings.html").is_file() else "")
    # ---- knobs
    h.append("<h2 id=knobs>Stylistic knobs you can choose between</h2>")
    h.append((OUT / "knobs.html").read_text(encoding="utf-8") if (OUT / "knobs.html").is_file() else "")
    # ---- A/B
    h.append("<h2 id=ab>A/B variants (texture-space stand-ins for the knobs)</h2>")
    if fac:
        h.append(f"<p class=note>Roster-wide factors (median over the {len(met['pairs'])} pairs): saturation &times;{fac['k_C']:.2f}; "
                 f"fine detail kept &times;{fac['a_detail']:.2f} (band below a {fac['detailSigmaTexels']:.0f}-texel gaussian); albedo L* {fac['dL']:+.1f}. "
                 "Applied to a copy of each unit's <code>basecolor.png</code> and re-rendered with the same relight. They approximate what the pipeline knobs would do; they are not look.py outputs.</p>")
    for u in (json.loads((OUT / "variants/variants.json").read_text()) if (OUT / "variants/variants.json").is_file() else {}):
        if (IMG / f"{u}_ab.png").is_file():
            h.append(f"<div class=card><h3>{u}</h3><img src='img/{u}_ab.png' alt='{u} A/B'>"
                     f"<p class=note>At battle size (3&times; nearest):</p><img class=pix src='img/{u}_ab_battle3x.png' alt='{u} A/B battle size'></div>")
    h.append("<div class=card><h3>Scale A/B</h3><p class=note>Every pair's battle-size panel shows ours at the installed per-hex, ours skeleton-anchored, and vanilla. "
             "Whole roster:</p><img class=pix src='sheets/sheet_battle_size_2x.png' alt='army at battle size'></div>")
    # ---- axis table
    h.append("<h2 id=table>Axis table (ours / vanilla per pair)</h2><div class=scroll><table><tr><th>axis</th>" +
             "".join(f"<th>{p['ours'].replace('h3_', '')}<br><span class=note>{html.escape(p['vanillaName'])}</span></th>" for p in met["pairs"]) + "</tr>")
    for key, lab, g, dg, kind in AXES:
        cells = []
        for p in met["pairs"]:
            o, v = g(p["o"]), g(p["v"])
            cells.append(f"<td>{fmt(o, dg)} / {fmt(v, dg)}</td>")
        h.append(f"<tr><td>{lab}</td>{''.join(cells)}</tr>")
    h.append("<tr><td>VFX: our layers (not drawn) / vanilla emission share (lit px with dL*&gt;3)</td>" + "".join(
        f"<td>{p['o']['vfx']['layers']} / {fmt(p['v'].get('emission', {}).get('fracLit'), 2) if p['v'].get('emission') else '-'}</td>" for p in met["pairs"]) + "</tr>")
    h.append("<tr><td>Our look (mode, applied, metal baked)</td>" + "".join(
        f"<td>{p['o']['lookMode']}, {'yes' if p['o']['lookApplied'] else 'preview'}, {'metal' if p['o']['metalBaked'] else '-'}</td>" for p in met["pairs"]) + "</tr>")
    h.append("</table></div>")
    # ---- pairs
    h.append("<h2 id=pairs>Pairs</h2>")
    for p in met["pairs"]:
        u = p["ours"]; o, v = p["o"], p["v"]
        sw = lambda pal: "".join(f"<span class=sw title='{c['share']:.0%}' style='background:rgb({c['rgb'][0]},{c['rgb'][1]},{c['rgb'][2]})'></span>" for c in pal)
        h.append(f"<div class=card id='{u}'><h3>{u} &harr; {html.escape(p['vanillaName'])} <span class=note>({p['category']}: {html.escape(p['why'])})</span></h3>")
        h.append(f"<p class=note>palette ours {sw(o['palette'])} &nbsp; vanilla {sw(v['palette'])} &nbsp; | L* {o['Lmean']:.1f} / {v['Lmean']:.1f}, "
                 f"C* {o['Cmean']:.1f} / {v['Cmean']:.1f}, fine detail {o['detailFineRms']:.2f} / {v['detailFineRms']:.2f}, "
                 f"speckle {o['speckleFrac']:.3f} / {v['speckleFrac']:.3f}, tris {o['triangles']} / {v['triangles']}, "
                 f"height {o['heightWorld']:.2f} / {v['heightWorld']:.2f}{' (vanilla shown at ours: no unit view)' if p['pair']['vanillaHeightAuthoredOnly'] else ''}</p>")
        h.append(f"<img src='img/{u}_detail.png' alt='{u} detail'>")
        h.append(f"<div class=grid2><div><p class=note>Battle size, 1&times; and 3&times; nearest</p><img class=pix src='img/{u}_battle1x.png' alt=''>"
                 f"<img class=pix src='img/{u}_battle3x.png' alt='{u} battle size'></div><div><p class=note>Flat albedo (and vanilla emission)</p>"
                 f"<img src='img/{u}_albedo.png' alt='{u} albedo'></div></div>")
        h.append(f"<p class=note>Turntable (top ours, bottom vanilla)</p><img src='img/{u}_turn.png' alt='{u} turntable'></div>")
    h.append("<h2 id=sheets>Contact sheets (PNG)</h2><ul>" + "".join(
        f"<li><a href='sheets/{f.name}'>{f.name}</a></li>" for f in sorted(SHEETS.glob("*.png"))) + "</ul>")
    h.append("</main></body></html>")
    (OUT / "index.html").write_text("\n".join(h), encoding="utf-8")


if __name__ == "__main__":
    main()
