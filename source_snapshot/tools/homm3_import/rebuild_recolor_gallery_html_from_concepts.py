#!/usr/bin/env python3
"""Point recolor_galleries/index.html at alternate_upgrade_concepts battle-sprite edits."""

from __future__ import annotations

import html
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONCEPT = ROOT / "tools" / "homm3_import" / "alternate_upgrade_concepts"
OUT = ROOT / "tools" / "homm3_import" / "recolor_galleries"


def main() -> int:
	index = json.loads((CONCEPT / "index.json").read_text(encoding="utf-8-sig"))
	galleries = index["galleries"]
	parts: list[str] = [
		"<!doctype html>",
		'<html lang="en"><head><meta charset="utf-8">',
		'<meta name="viewport" content="width=device-width,initial-scale=1">',
		"<title>Factory / Bulwark Alternate Upgrade Concepts</title>",
		"<style>",
		":root{--bg:#0b0e12;--card:#151a21;--line:#2c3540;--text:#f1f3f5;--muted:#9aa3ad;--warn:#c9785a}",
		"*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 Segoe UI,Arial,sans-serif}",
		"nav{position:sticky;top:0;z-index:3;display:flex;gap:10px;padding:10px 16px;background:#0d1116f0;border-bottom:1px solid #2c3540}",
		"nav a{color:var(--text);text-decoration:none;background:#1a222b;border:1px solid #3a4653;border-radius:5px;padding:7px 11px}",
		"main{max-width:1400px;margin:0 auto;padding:18px}",
		"h1{font-size:28px;margin:8px 0 6px}.note{color:var(--muted);margin:0 0 10px}.warn{color:var(--warn);margin:0 0 18px}",
		".line{margin:0 0 28px;padding:16px;background:var(--card);border:1px solid var(--line);border-radius:8px}",
		".line h2{margin:0 0 4px;font-size:18px}.line p{margin:0 0 12px;color:var(--muted)}",
		".row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}",
		".tile{background:#0f141a;border:1px solid var(--line);border-radius:6px;padding:8px}",
		".tile img{width:100%;height:220px;object-fit:contain;image-rendering:pixelated;",
		"background:repeating-conic-gradient(#1c232b 0 25%,#222a33 0 50%) 0/16px 16px}",
		".tile strong{display:block;margin-top:6px}.tile span{color:var(--muted);font-size:13px}",
		"</style></head><body>",
		'<nav><a href="#factory">Factory</a><a href="#bulwark">Bulwark</a></nav>',
		"<main>",
		"<h1>Factory / Bulwark alternate upgrades</h1>",
		'<p class="note">Battle standing sprites (animation group 2) with authored prop/kit edits — '
		"not HotA portrait icons, and not a global color filter.</p>",
		'<p class="warn">Evidence: static concept previews only. Animation / Golden Era runtime not proven. Nothing locked.</p>',
	]

	current = None
	for gallery in galleries:
		faction = str(gallery["faction"])
		if faction != current:
			if current is not None:
				parts.append("</section>")
			parts.append(f'<section id="{html.escape(faction)}"><h1>{html.escape(faction.title())}</h1>')
			current = faction

		slug_parts = [faction, f"t{gallery['tier']}", str(gallery["baseSid"])]
		if gallery.get("line"):
			slug_parts.append(str(gallery["line"]))
		slug = "__".join(slug_parts)
		title = f"T{gallery['tier']} — {gallery.get('sourceName') or gallery['upgradeSid']}"
		parts.append(f'<article class="line" id="{html.escape(slug)}">')
		parts.append(f"<h2>{html.escape(title)}</h2>")
		parts.append(f"<p>{html.escape(str(gallery.get('lineRole') or ''))}</p>")
		parts.append('<div class="row">')

		def concept_href(repo_rel: str) -> str:
			abs_path = (ROOT / repo_rel).resolve()
			try:
				return abs_path.relative_to(OUT.resolve()).as_posix()
			except ValueError:
				return (pathlib.PurePosixPath("..") / abs_path.relative_to(OUT.parent.resolve()).as_posix()).as_posix()

		src_href = concept_href(gallery["sourcePreviewPath"])
		parts.append('<div class="tile">')
		parts.append(f'<img src="{html.escape(src_href)}" alt="Source">')
		parts.append(f"<strong>Source: {html.escape(str(gallery.get('sourceName') or gallery['upgradeSid']))}</strong>")
		parts.append("<span>Canonical upgrade battle sprite</span></div>")

		for concept in gallery.get("concepts") or []:
			href = concept_href(concept["previewPath"])
			parts.append('<div class="tile">')
			parts.append(f'<img src="{html.escape(href)}" alt="{html.escape(concept["name"])}">')
			parts.append(f"<strong>{html.escape(concept['id'])}. {html.escape(concept['name'])}</strong>")
			parts.append(f"<span>{html.escape(str(concept.get('gameplayIdentity') or ''))}</span></div>")
		parts.append("</div></article>")

	if current is not None:
		parts.append("</section>")
	parts.append("</main></body></html>")

	OUT.mkdir(parents=True, exist_ok=True)
	path = OUT / "index.html"
	path.write_text("\n".join(parts) + "\n", encoding="utf-8")
	print(f"wrote {path.relative_to(ROOT).as_posix()} ({path.stat().st_size} bytes)")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
